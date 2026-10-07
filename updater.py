"""
Placeholder for update checking functionality.
Will be implemented to check for new releases from GitHub.
"""

import json
import urllib.request
from pathlib import Path
from tkinter import messagebox


def get_github_release_info() -> dict | None:
    """
    Consulta a API do GitHub para obter informações da última release.
    Retorna None em caso de erro.
    """
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
    """
    Obtém a versão actual do programa.
    Tentar ler de um ficheiro VERSION.txt na pasta do programa,
    ou usar um fallback.
    """
    version_file = Path(__file__).parent / "VERSION.txt"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.1.0"


def check_for_updates(show_message: bool = True, parent=None) -> tuple[bool, str]:
    """
    Verifica se há atualizações disponíveis.

    Returns:
        tuple: (has_update, message)
        - has_update: True se houver nova versão disponível
        - message: mensagem descritiva
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

    # Comparação simples de versões (supostamente semver)
    current_parts = [int(x) for x in current.split(".") if x.isdigit()]
    latest_parts = [int(x) for x in latest_tag.split(".") if x.isdigit()]

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

    message = (
        f"Já está na última versão: {current}\n"
        f"Próxima: {latest_tag}"
    )
    if show_message:
        messagebox.showinfo("Atualização", message, parent=parent)
    return False, message


def open_releases_page():
    """Abre a página de releases no navegador."""
    url = "https://github.com/alexsanderfernandes/conversor-jumpseller/releases"
    import webbrowser
    webbrowser.open(url)