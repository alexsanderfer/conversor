"""
Janela de ativação / renovação de licença.

Mostrada quando não há licença válida. O utilizador arrasta (ou procura) um
ficheiro .lic; o diálogo valida-o e só se fecha quando a licença é aceite,
para que a recusa apareça no ecrã onde ele está a trabalhar.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from tkinterdnd2 import DND_FILES

from license_manager import compute_machine_fingerprint
from theme import (
    BG_WINDOW,
    ERROR_BG,
    ERROR_FG,
    FOOTER_TEXT,
    GRAY_100,
    GRAY_600,
    GRAY_800,
    GREEN_100,
    GREEN_700,
    GREEN_900,
    WHITE,
)


class LicenseDialog:
    """
    Diálogo modal de ativação.

    `on_submit(path)` valida a licença e devolve (ok, motivo). O diálogo
    fecha-se sozinho quando ok é True, ou quando o utilizador desiste.
    """

    def __init__(self, root, license_dir, on_submit, on_cancel=None, reason=""):
        self._root = root
        self._license_dir = Path(license_dir)
        self._on_submit = on_submit
        self._on_cancel = on_cancel or (lambda: None)
        self._closing = False

        self.win = tk.Toplevel(root)
        self.win.title("Licença — Conversor Jumpseller")
        self.win.geometry("540x340")
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
            text="Este Conversor precisa de uma licença para funcionar.",
            bg=BG_WINDOW,
            fg=GREEN_900,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")

        tk.Label(
            frm,
            text=(
                "Arraste para baixo o ficheiro .lic que lhe foi enviado, ou "
                "clique em «Procurar…». A licença é guardada neste computador "
                "e vale durante 12 meses."
            ),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=504,
        ).pack(anchor="w", pady=(4, 8))

        self.drop = tk.Text(
            frm,
            height=6,
            relief="solid",
            bg=GRAY_100,
            fg=GRAY_800,
            font=("Segoe UI", 10),
            borderwidth=0,
            highlightbackground=GREEN_700,
            highlightcolor=GREEN_700,
            highlightthickness=1,
            wrap="word",
            padx=8,
            pady=8,
        )
        self.drop.pack(fill="both", expand=True)
        self.drop.drop_target_register(DND_FILES)
        self.drop.dnd_bind("<<Drop>>", self._on_drop)

        inicial = (
            f"A licença anterior foi recusada:\n{reason}"
            if reason
            else f"Nenhuma licença aceite.\nColoque a licença em: {self._license_dir}"
        )
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
            text="Sair",
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
            text="Procurar…",
            command=self._browse,
            bg=GREEN_700,
            fg=WHITE,
            activebackground=GREEN_900,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            width=14,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="right", padx=(0, 8))

        # código da máquina: é o que o cliente envia ao fornecedor
        tk.Label(
            frm,
            text="Para receber a licença, envie este código ao fornecedor:",
            bg=BG_WINDOW,
            fg=GRAY_600,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x", pady=(10, 0))

        row = tk.Frame(frm, bg=BG_WINDOW)
        row.pack(fill="x", pady=(3, 0))

        self._code_entry = tk.Entry(
            row,
            font=("Consolas", 8),
            relief="solid",
            borderwidth=1,
            bg=WHITE,
            fg=GRAY_800,
            readonlybackground=WHITE,
        )
        self._code_entry.pack(side="left", fill="x", expand=True)
        self._code_entry.insert(0, compute_machine_fingerprint())
        self._code_entry.config(state="readonly")

        tk.Button(
            row,
            text="Copiar",
            command=self._copy_code,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            relief="flat",
            font=("Segoe UI", 9),
            width=8,
            pady=2,
            cursor="hand2",
        ).pack(side="left", padx=(6, 0))

        tk.Label(
            frm,
            text=FOOTER_TEXT,
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 7),
            justify="center",
            wraplength=504,
        ).pack(anchor="w", pady=(10, 0))

    def _copy_code(self):
        self._code_entry.clipboard_clear()
        self._code_entry.clipboard_append(self._code_entry.get())
        messagebox.showinfo(
            "Copiado",
            "Código copiado. Envie-o ao fornecedor por email ou WhatsApp.",
            parent=self.win,
        )

    # -- handlers -------------------------------------------------------

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Selecione o ficheiro de licença",
            initialdir=str(self._license_dir),
            filetypes=[("Licenças", "*.lic"), ("Todos os arquivos", "*")],
        )
        if path:
            self._submit(Path(path))

    def _on_drop(self, event):
        # No Windows o evento traz as chaves '{}' e pode vir com \r\n
        raw = event.data.strip().strip("{}")
        candidates = raw.replace("\r\n", " ").split()
        lic = next((c for c in candidates if c.lower().endswith(".lic")), None)
        if lic:
            self._submit(Path(lic))
        else:
            messagebox.showwarning(
                "Ficheiro inválido",
                "Arraste apenas um ficheiro .lic.",
                parent=self.win,
            )

    def _submit(self, path: Path):
        """Valida e, se aceite, fecha."""
        if self._closing:
            return
        self._set_status("A verificar licença…", GREEN_100, GREEN_900)
        self.win.update_idletasks()

        ok, message = self._on_submit(path)

        if ok:
            self._closing = True
            self._set_status(f"Licença aceite.\n{message}", GREEN_100, GREEN_700)
            self.win.after(700, self._close)
        else:
            # a recusa fica no ecrã; o utilizador pode tentar outro ficheiro
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

    def _set_status(self, text: str, bg: str, fg: str):
        self.drop.config(state="normal", bg=bg, fg=fg)
        self.drop.delete("1.0", "end")
        self.drop.insert("1.0", text)
        self.drop.config(state="disabled")
