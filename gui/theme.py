"""
Tema azul corporativo e ciano da aplicação (rebranding completo).

Constrói um tema ttk 'conversor' derivado de 'clam' e expõe a paleta em
constantes para uniformizar a interface em tons de azul escuro, ciano e neutros.
"""

import tkinter.ttk as ttk
from core.i18n import translate, DEFAULT_LANGUAGE

# --- paleta corporativa moderna (Azul / Ciano / Dourado) -------------------
BLUE_900 = "#1E3A8A"   # cabeçalhos, texto sobre fundo azul-claro
BLUE_700 = "#2563EB"   # botões principais, molduras
BLUE_500 = "#3B82F6"   # hover dos botões
BLUE_100 = "#EFF6FF"   # fundo de sucesso / destaque leve
BLUE_50 = "#F8FAFC"    # fundo das tabs / área de arraste
GRAY_800 = "#1E293B"   # texto corrido
GRAY_600 = "#64748B"   # texto secundário
GRAY_100 = "#F1F5F9"   # fundo neutro
WHITE = "#FFFFFF"
BG_WINDOW = "#FFFFFF"

ERROR_BG = "#FEF2F2"
ERROR_FG = "#DC2626"

FOOTER_TEXT = translate(
    "Reservados os direitos de autor e comercialização, é proibida "
    "a reprodução e venda por agente não autorizado.",
    DEFAULT_LANGUAGE
)


def apply_theme(root):
    """Cria e aplica o tema corporativo. Devolve o objeto Style."""
    style = ttk.Style(root)
    try:
        style.theme_create("conversor", parent="clam")
    except Exception:
        pass
    style.theme_use("conversor")

    style.configure(".", background=WHITE, foreground=GRAY_800,
                    font=("Segoe UI", 10))

    style.configure("TFrame", background=WHITE)
    style.configure("TLabel", background=WHITE, foreground=GRAY_800)
    style.configure("TLabel.Secondary", foreground=GRAY_600)
    style.configure("TLabel.Footer", foreground=GRAY_800,
                    font=("Segoe UI", 7))
    style.configure("TLabel.Title", foreground=BLUE_900,
                    font=("Segoe UI", 15, "bold"))

    # Notebook: separadores
    style.configure("TNotebook", background=BG_WINDOW, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=BLUE_50,
        foreground=GRAY_800,
        padding=[16, 6],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BLUE_700), ("active", BLUE_100)],
        foreground=[("selected", WHITE), ("active", GRAY_800)],
    )

    # Botões
    style.configure(
        "TButton",
        background=BLUE_700,
        foreground=WHITE,
        borderwidth=0,
        padding=[10, 6],
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "TButton",
        background=[("active", BLUE_500), ("disabled", "#CBD5E1")],
        foreground=[("disabled", "#F8FAFC")],
    )
    # Botão discreto
    style.configure(
        "TButton.Tonal",
        background=BLUE_100,
        foreground=BLUE_900,
        font=("Segoe UI", 10),
    )
    style.map(
        "TButton.Tonal",
        background=[("active", "#DBEAFE")],
    )

    # Campos
    style.configure("TEntry", fieldbackground=WHITE, borderwidth=1,
                    bordercolor="#CBD5E1", padding=3)
    style.configure("TCheckbutton", background=WHITE, foreground=GRAY_800)

    return style


function = None


def style_drop_area(widget):
    """
    Aplica a moldura azul corporativa à área de arraste.
    """
    widget.config(
        highlightbackground=BLUE_700,
        highlightcolor=BLUE_700,
        highlightthickness=1,
        relief="solid",
        borderwidth=0,
        bg=GRAY_100,
    )
    return widget
