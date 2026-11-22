"""
Janela de ativação / renovação de licença.

Mostrada quando não há licença válida. O utilizador cola a chave de ativação
(enviada por email/WhatsApp pelo fornecedor); o diálogo valida-a e só se fecha
quando a chave é aceite, para que a recusa apareça no ecrã onde ele está a trabalhar.
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from core.license_manager import check_license
from core.i18n import translate, DEFAULT_LANGUAGE
from gui.theme import (
    BG_WINDOW,
    ERROR_BG,
    ERROR_FG,
    FOOTER_TEXT,
    GRAY_100,
    GRAY_600,
    GRAY_800,
    BLUE_100,
    BLUE_700,
    BLUE_900,
    WHITE,
)


class LicenseDialog:
    """
    Diálogo modal de ativação por chave.

    `on_submit(key)` valida a chave de ativação e devolve (ok, motivo).
    O diálogo fecha-se sozinho quando ok é True, ou quando o utilizador desiste.
    """

    def __init__(self, root, license_dir, on_submit, on_cancel=None, reason="", language=DEFAULT_LANGUAGE):
        self._root = root
        self._license_dir = Path(license_dir)
        self._on_submit = on_submit
        self._on_cancel = on_cancel or (lambda: None)
        self._closing = False
        self.language = language

        self.win = tk.Toplevel(root)
        self.win.title(translate("Licença — CsvFast-FileConverter", self.language))
        self.win.geometry("540x400")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.configure(bg=BG_WINDOW)
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)

        self._build(reason)
        self.win.grab_set()
        self.win.focus_set()

    # -- construção da UI ------------------------------------------------

    def _build(self, reason: str):
        frm = tk.Frame(self.win, bg=BG_WINDOW, padx=18, pady=14)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm,
            text=translate("Este Conversor precisa de uma chave de ativação para funcionar.", self.language),
            bg=BG_WINDOW,
            fg=BLUE_900,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        tk.Label(
            frm,
            text=(
                translate("Cole abaixo a chave de ativação enviada pelo fornecedor (por email ou WhatsApp). "
                          "A chave é guardada neste computador.", self.language)
            ),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=504,
        ).pack(anchor="w", pady=(4, 8))

        self.key_text = tk.Text(
            frm,
            height=4,
            relief="solid",
            bg=GRAY_100,
            fg=GRAY_800,
            font=("Consolas", 10),
            borderwidth=0,
            highlightbackground=BLUE_700,
            highlightcolor=BLUE_700,
            highlightthickness=1,
            wrap="word",
            padx=8,
            pady=8,
        )
        self.key_text.pack(fill="both", expand=True)

        if reason:
            inicial = translate("A chave anterior foi recusada:", self.language) + f"\n{reason}"
        else:
            inicial = translate("Nenhuma chave aceite.", self.language)
        self._set_status(
            inicial,
            ERROR_BG if reason else GRAY_100,
            ERROR_FG if reason else GRAY_800,
        )

        # botões
        frm_btn = tk.Frame(frm, bg=BG_WINDOW)
        frm_btn.pack(fill="x", pady=(10, 0))

        tk.Button(
            frm_btn,
            text=translate("Sair", self.language),
            command=self._cancel,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            relief="flat",
            font=("Segoe UI", 10),
            width=10,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="right")

        tk.Button(
            frm_btn,
            text=translate("Ativar", self.language),
            command=self._activate,
            bg=BLUE_700,
            fg=WHITE,
            activebackground=BLUE_900,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            width=14,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="right", padx=(0, 8))

        tk.Label(
            frm,
            text=FOOTER_TEXT,
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 7),
            justify="center",
            wraplength=504,
        ).pack(anchor="w", pady=(10, 0))

    def _set_status(self, text: str, bg: str, fg: str):
        self.key_text.config(state="normal", bg=bg, fg=fg)
        self.key_text.delete("1.0", "end")
        self.key_text.insert("1.0", text)
        self.key_text.config(state="disabled")

    # -- handlers -------------------------------------------------------

    def _activate(self):
        """Valida a chave digitada/colada."""
        if self._closing:
            return
        key = self.key_text.get("1.0", "end").strip()
        if not key:
            messagebox.showwarning(
                translate("Chave vazia", self.language),
                translate("Por favor, cole a chave de ativação antes de continuar.", self.language),
                parent=self.win,
            )
            return

        self._set_status(translate("A verificar chave…", self.language), BLUE_100, BLUE_900)
        self.win.update_idletasks()

        # Criar um ficheiro temporário com a chave para reutilizar a lógica de verificação
        import tempfile
        import json
        lic_path = None
        try:
            lic_path = Path(tempfile.mktemp(suffix=".lic", dir=str(self._license_dir.parent)))
            lic_path.write_text(key, encoding="utf-8")
            ok, message = self._on_submit(lic_path)
        finally:
            if lic_path and lic_path.exists():
                try:
                    lic_path.unlink()
                except OSError:
                    pass

        if ok:
            self._closing = True
            self._set_status(f"{translate('Chave aceite.', self.language)}\n{message}", BLUE_100, BLUE_700)
            self.win.after(700, self._close)
        else:
            # a recusa fica no ecrã; o utilizador pode tentar outra chave
            self._set_status(message, ERROR_BG, ERROR_FG)

    def _cancel(self):
        if self._closing:
            return
        self._on_cancel()
        self._close()

    def _close(self):
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
