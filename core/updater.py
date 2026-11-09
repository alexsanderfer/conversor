"""
Verificação de atualizações — não afeta licenças válidas.

Consulta um ficheiro de versão simples hospedado na página pública (GitHub Pages),
sem expor o repositório GitHub. A verificação de licença é totalmente independente:
se a licença for válida, o programa simplesmente prossegue; a atualização é
apenas informativa.
"""

import re
import urllib.request
from pathlib import Path
from tkinter import messagebox


def _parse_version(v: str) -> tuple[int, ...]:
    """Extrai partes numericas de uma string de versão."""
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
    Obtém a versão mais recente a partir de um ficheiro version.txt
    hospedado na página pública (GitHub Pages).
    Retorna None em caso de erro.
    """
    try:
        # Aponta para o ficheiro version.txt no site público (GitHub Pages)
        # O site é gerado a partir da branch gh-pages ou da pasta docs/
        url = "https://alexsanderfer.github.io/conversor/version.txt"
        req = urllib.request.Request(
            url, headers={"User-Agent": "ConversorJumpseller-Updater"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            version = response.read().decode("utf-8").strip()
            # Remove prefixo 'v' se existir
            return version.lstrip("v")
    except Exception:
        return None


def get_current_version() -> str:
    """Obtém a versão actual do programa (de VERSION.txt ou fallback)."""
    version_file = Path(__file__).parent / "VERSION.txt"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.1.0"


def check_for_updates(show_message: bool = True, parent=None) -> tuple[bool, str]:
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
        message = "Não foi possível verificar atualizações no momento."
        if show_message:
            messagebox.showwarning("Atualização", message, parent=parent)
        return False, message

    current_parts = _parse_version(current)
    latest_parts = _parse_version(latest)

    if current_parts and latest_parts and latest_parts > current_parts:
        message = (
            f"Nova versão disponível: {latest}\n\n"
            f"Clique em OK para abrir a página de download."
        )
        if show_message:
            import webbrowser
            if messagebox.askyesno("Atualização disponível", message, parent=parent):
                webbrowser.open("https://alexsanderfer.github.io/conversor/")
        return True, message

    message = f"Já está na última versão: {current}"
    if show_message:
        messagebox.showinfo("Atualização", message, parent=parent)
    return False, message


def open_releases_page():
    """Abre a página pública no navegador."""
    url = "https://alexsanderfer.github.io/conversor/"
    import webbrowser
    webbrowser.open(url)