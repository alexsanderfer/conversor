"""
Verificação de atualizações — não afeta licenças válidas.

Consulta a API do GitHub para obter informações da última release.
A verificação de licença é totalmente independente: se a licença
for válida, o programa simplesmente prossegue; a atualização é
apenas informativa.
"""

import json
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


def get_github_release_info() -> dict | None:
    """Consulta a API do GitHub para a última release. Retorna None em caso de erro."""
    try:
        url = "https://api.github.com/repos/alexsanderfernandes/conversor-jumpseller/releases/latest"
        req = urllib.request.Request(
            url, headers={"User-Agent": "ConversorJumpseller-Updater"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
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
    NÃO afeta licenças válidas — apenas lê a API do GitHub e
    mostra mensagem ao utilizador.

    Returns:
        tuple: (has_update, message)
    """
    current = get_current_version()
    release = get_github_release_info()

    if release is None:
        message = "Não foi possível verificar atualizações no momento."
        if show_message:
            messagebox.showwarning("Atualização", message, parent=parent)
        return False, message

    latest_tag = release.get("tag_name", "").lstrip("v")
    latest_name = release.get("name", "Nova versão")
    latest_url = release.get("html_url", "")
    published_at = release.get("published_at", "")

    if not latest_tag:
        message = "Não foi possível determinar a versão mais recente."
        if show_message:
            messagebox.showwarning("Atualização", message, parent=parent)
        return False, message

    current_parts = _parse_version(current)
    latest_parts = _parse_version(latest_tag)

    if current_parts and latest_parts and latest_parts > current_parts:
        message = (
            f"Nova versão disponível: {latest_tag}\n\n"
            f"{latest_name}\n"
            f"Publicada em: {published_at[:10] if published_at else '—'}\n\n"
            f"Clique em OK para abrir a página de download."
        )
        if show_message:
            import webbrowser
            if messagebox.askyesno("Atualização disponível", message, parent=parent):
                webbrowser.open(latest_url)
        return True, message

    message = f"Já está na última versão: {current}"
    if show_message:
        messagebox.showinfo("Atualização", message, parent=parent)
    return False, message


def open_releases_page():
    """Abre a página de releases no navegador."""
    url = "https://github.com/alexsanderfernandes/conversor-jumpseller/releases"
    import webbrowser
    webbrowser.open(url)