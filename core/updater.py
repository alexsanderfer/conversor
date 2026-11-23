"""
Verificação de atualizações — não afeta licenças válidas.

Consulta a API pública do GitHub para saber a tag da release mais recente.
A verificação de licença é totalmente independente: se a licença for válida,
o programa simplesmente prossegue; a atualização é apenas informativa.
"""

import re
import sys
import urllib.request
import urllib.error
import tempfile
import subprocess
import os
import shutil
from pathlib import Path
from tkinter import messagebox
from core.i18n import translate, DEFAULT_LANGUAGE

# Repositório público onde são publicadas as releases
GITHUB_REPO = "alexsanderfer/conversor"


def _parse_version(v: str) -> tuple[int, ...]:
    """Extrai partes numericas de uma string de versão."""
    if not v:
        return (0,)
    v = v.lstrip("v")
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", v)
    if not m:
        return (0,)
    parts = [int(m.group(1))]
    if m.group(2) is not None:
        parts.append(int(m.group(2)))
    if m.group(3) is not None:
        parts.append(int(m.group(3)))
    return tuple(parts)


def get_latest_version() -> str | None:
    """
    Obtém a versão mais recente a partir da API pública do GitHub (releases/latest)
    ou do ficheiro público de version.txt.
    Retorna None em caso de erro.
    """
    import json
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(
            url, headers={"User-Agent": "ConversorJumpseller-Updater"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            version = data.get("tag_name") or data.get("name") or ""
            return version.lstrip("v") or None
    except Exception:
        # Fallback para o version.txt bruto no GitHub se a API REST falhar ou der rate limit
        try:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/master/docs/version.txt"
            req = urllib.request.Request(
                url, headers={"User-Agent": "ConversorJumpseller-Updater"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                version = response.read().decode("utf-8").strip()
                return version.lstrip("v") or None
        except Exception:
            return None


def get_current_version() -> str:
    """Obtém a versão actual do programa (de VERSION.txt ou fallback)."""
    # Procurar VERSION.txt na raiz do projeto (sibling do pacote core/)
    for candidate in (
        Path(__file__).resolve().parent.parent / "VERSION.txt",
        Path(__file__).resolve().parent / "VERSION.txt",
    ):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    # No modo congelado, o VERSION.txt é empacotado ao lado do exe / sys._MEIPASS
    if getattr(sys, "frozen", False):
        for candidate in (
            Path(sys.executable).parent / "VERSION.txt",
            Path(sys._MEIPASS) / "VERSION.txt",
        ):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip()
    return "0.1.0"


def check_for_updates(show_message: bool = True, parent=None, language: str = DEFAULT_LANGUAGE) -> tuple[bool, str]:
    """
    Verifica se há atualizações disponíveis.
    NÃO afeta licenças válidas — apenas lê a versão do site público
    e mostra mensagem ao utilizador.

    Returns:
        tuple: (has_update, message)
    """
    current = get_current_version()
    latest = get_latest_version()

    if latest is None:
        message = translate("Não foi possível verificar atualizações no momento.", language)
        if show_message:
            messagebox.showwarning(translate("Atualização", language), message, parent=parent)
        return False, message

    current_parts = _parse_version(current)
    latest_parts = _parse_version(latest)

    if current_parts and latest_parts and latest_parts > current_parts:
        message = (
            f"{translate('Nova versão disponível:', language)} {latest}\n\n"
            f"{translate('Pretende instalar agora?', language)}"
        )
        if show_message:
            if messagebox.askyesno(translate("Atualização disponível", language), message, parent=parent):
                # Inicia o fluxo de instalação em thread para não bloquear a UI.
                # Sem UI (fallback) executa diretamente.
                start_auto_update_flow(latest, parent=parent, language=language)
        return True, message

    message = f"{translate('Já está na última versão:', language)} {current}"
    if show_message:
        messagebox.showinfo(translate("Atualização", language), message, parent=parent)
    return False, message


def open_releases_page():
    """Abre a página pública no navegador."""
    url = "https://alexsanderfer.github.io/conversor/"
    import webbrowser
    webbrowser.open(url)


def download_installer(latest_version: str) -> tuple[Path | None, str | None]:
    """Descarrega o instalador para uma pasta temporária."""
    try:
        temp_dir = Path(tempfile.gettempdir()) / "ConversorJumpseller-Update"
        temp_dir.mkdir(parents=True, exist_ok=True)

        url = f"https://github.com/{GITHUB_REPO}/releases/download/v{latest_version}/ConversorJumpseller-Setup-v{latest_version}-x64.exe"
        installer_path = temp_dir / f"ConversorJumpseller-Setup-v{latest_version}-x64.exe"

        req = urllib.request.Request(url, headers={"User-Agent": "ConversorJumpseller-Updater"})
        with urllib.request.urlopen(req, timeout=300) as response, open(installer_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

        return installer_path, None
    except urllib.error.URLError:
        return None, translate("Erro de rede ao descarregar o instalador.", DEFAULT_LANGUAGE)
    except Exception as e:
        return None, f"{translate('Erro inesperado:', DEFAULT_LANGUAGE)} {str(e)}"


def install_update(latest_version: str) -> tuple[bool, str]:
    """Executa o instalador descarregado e encerra a app para permitir a substituição."""
    installer_path, error = download_installer(latest_version)
    if error:
        return False, error

    try:
        # Lança o instalador em modo detached (sem /NORESTART)
        subprocess.Popen(
            [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        return True, translate("Instalação iniciada com sucesso.", DEFAULT_LANGUAGE)
    except Exception as e:
        return False, f"{translate('Erro na instalação:', DEFAULT_LANGUAGE)} {str(e)}"


def install_update_and_restart(latest_version: str, parent=None, language: str = DEFAULT_LANGUAGE) -> None:
    """Executa o instalador e reinicia o conversor (chamado em thread pela GUI)."""
    success, msg = install_update(latest_version)
    if success:
        restart_conversor()
    elif parent is not None and hasattr(parent, "after"):
        parent.after(0, lambda: messagebox.showerror(translate("Erro", language), msg, parent=parent))
    else:
        print(msg)


def start_auto_update_flow(latest_version: str, parent=None, language: str = DEFAULT_LANGUAGE) -> None:
    """Inicia o download e utiliza um script batch temporário para aguardar o fecho total da app e abrir o instalador gráfico."""
    def worker():
        installer_path, error = download_installer(latest_version)
        if error:
            if parent is not None and hasattr(parent, "after"):
                parent.after(0, lambda: messagebox.showerror(translate("Erro", language), error, parent=parent))
            else:
                print(error)
            return

        try:
            def _notify_and_launch():
                if parent is not None:
                    messagebox.showinfo(
                        translate("Atualização", language),
                        translate("A aplicação vai fechar e abrir o assistente de instalação da nova versão.", language),
                        parent=parent
                    )

                # Criar um script batch temporário para garantir que a app fecha
                # e liberta todos os handles de DLL do Python antes de o instalador correr.
                bat_path = Path(tempfile.gettempdir()) / "conversor_update.bat"
                pid = os.getpid()
                bat_content = f"""@echo off
echo A aguardar o encerramento da aplicacao...
:WAITLOOP
tasklist /fi "pid eq {pid}" 2>NUL | find /i "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto WAITLOOP
)
echo A iniciar o instalador...
start "" "{installer_path}"
del "%~f0"
"""
                bat_path.write_text(bat_content, encoding="utf-8")

                # Lança o batch em segundo plano destacado
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

                # Fecha a app atual imediatamente
                os._exit(0)

            if parent is not None and hasattr(parent, "after"):
                parent.after(0, _notify_and_launch)
            else:
                bat_path = Path(tempfile.gettempdir()) / "conversor_update.bat"
                pid = os.getpid()
                bat_content = f"""@echo off
:WAITLOOP
tasklist /fi "pid eq {pid}" 2>NUL | find /i "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto WAITLOOP
)
start "" "{installer_path}"
del "%~f0"
"""
                bat_path.write_text(bat_content, encoding="utf-8")
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                os._exit(0)
        except Exception as e:
            msg = f"{translate('Erro na instalação:', language)} {str(e)}"
            if parent is not None and hasattr(parent, "after"):
                parent.after(0, lambda: messagebox.showerror(translate("Erro", language), msg, parent=parent))
            else:
                print(msg)

    import threading
    threading.Thread(target=worker, daemon=True).start()


def restart_conversor() -> None:
    """Reabre o executável."""
    if not getattr(sys, "frozen", False):
        print("Em modo de desenvolvimento. Não é possível reiniciar.")
        return

    # In frozen mode, exe is at sys.executable
    executable = sys.executable

    # Detached process
    subprocess.Popen([executable], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    os._exit(0)
