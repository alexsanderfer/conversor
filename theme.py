"""
Tema verde da aplicação.

Constrói um tema ttk 'conversor' derivado de 'clam' (o único que aceita
personalização de cor de forma fiável no Windows) e expõe a paleta em
constantes, para o resto do código não repetir números hex.
"""

import tkinter.ttk as ttk

# --- paleta ---------------------------------------------------------------
# Os verdes/vermelhos de sucesso e erro já eram usados pela app original
# (verde #E8F5E9/#2E7D32, vermelho #FFEBEE/#C62828) e mantêm-se.
GREEN_900 = "#1B5E20"   # cabeçalhos, texto sobre fundo verde-claro
GREEN_700 = "#2E7D32"   # botões, molduras
GREEN_500 = "#43A047"   # hover dos botões
GREEN_100 = "#E8F5E9"   # fundo de sucesso
GREEN_50 = "#F1F8E9"    # fundo das tabs / área de arraste
GRAY_800 = "#333333"    # texto corrido (contraste ~12:1 sobre branco)
GRAY_600 = "#555555"    # texto secundário
GRAY_100 = "#F5F5F5"    # fundo neutro
WHITE = "#FFFFFF"
BG_WINDOW = "#FFFFFF"

ERROR_BG = "#FFEBEE"
ERROR_FG = "#C62828"

FOOTER_TEXT = (
    "Reservados os direitos de autor e comercialização, é proibida "
    "a reprodução e venda por agente não autorizado."
)


def apply_theme(root):
    """Cria e aplica o tema. Devolve o objeto Style."""
    style = ttk.Style(root)
    try:
        style.theme_create("conversor", parent="clam")
    except Exception:
        # Se já existe (recriação da janela), seguimos com a instância atual.
        pass
    style.theme_use("conversor")

    style.configure(".", background=WHITE, foreground=GRAY_800,
                    font=("Segoe UI", 10))

    style.configure("TFrame", background=WHITE)
    style.configure("TLabel", background=WHITE, foreground=GRAY_800)
    style.configure("TLabel.Secondary", foreground=GRAY_600)
    style.configure("TLabel.Footer", foreground=GRAY_800,
                    font=("Segoe UI", 7))
    style.configure("TLabel.Title", foreground=GREEN_900,
                    font=("Segoe UI", 15, "bold"))

    # Notebook: separadores
    style.configure("TNotebook", background=BG_WINDOW, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=GREEN_50,
        foreground=GRAY_800,
        padding=[16, 6],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", GREEN_700), ("active", GREEN_100)],
        foreground=[("selected", WHITE), ("active", GRAY_800)],
    )

    # Botões
    style.configure(
        "TButton",
        background=GREEN_700,
        foreground=WHITE,
        borderwidth=0,
        padding=[10, 6],
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "TButton",
        background=[("active", GREEN_500), ("disabled", "#BDBDBD")],
        foreground=[("disabled", "#F5F5F5")],
    )
    # Botão discreto (escolher ficheiro / sair)
    style.configure(
        "TButton.Tonal",
        background=GREEN_100,
        foreground=GREEN_900,
        font=("Segoe UI", 10),
    )
    style.map(
        "TButton.Tonal",
        background=[("active", "#C8E6C9")],
    )

    # Campos
    style.configure("TEntry", fieldbackground=WHITE, borderwidth=1,
                    bordercolor="#BDBDBD", padding=3)
    style.configure("TCheckbutton", background=WHITE, foreground=GRAY_800)

    return style


def style_drop_area(widget):
    """
    Aplica a moldura verde à área de arraste.

    É um tk.Text puro, não um widget ttk, portanto ignora o tema: a
    moldura verde faz-se pelo realce (highlight*).
    """
    widget.config(
        highlightbackground=GREEN_700,
        highlightcolor=GREEN_700,
        highlightthickness=1,
        relief="solid",
        borderwidth=0,
        bg=GRAY_100,
    )
    return widget
