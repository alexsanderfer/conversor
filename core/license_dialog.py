"""
Janela de ativação / renovação de licença.

Mostrada quando não há licença válida. Oferece três formas de ativação:
1) Conta vinculada online — valida via API do servidor SaaS (Supabase/Stripe).
2) Código do Dispositivo — fluxo Device Code (gera código, usuário autoriza no navegador).
3) Código de ativação — chave assinada HMAC-SHA256 enviada por email/WhatsApp.
"""

import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from core.license_manager import verify_activation_key, verify_saas_account, verify_device_code
from core.i18n import translate, DEFAULT_LANGUAGE
from gui.theme import (
    BG_WINDOW,
    ERROR_BG,
    ERROR_FG,
    GRAY_100,
    GRAY_600,
    GRAY_800,
    BLUE_100,
    BLUE_500,
    BLUE_700,
    BLUE_900,
    WHITE,
)

# Ecrã do SaaS onde o fornecedor cola o código de dispositivo.
DEVICE_ACTIVATION_URL = "https://shopsyncpt.vercel.app/pt-PT/device/activate"


class LicenseDialog:
    """
    Diálogo modal de ativação por chave, conta SaaS ou código do dispositivo.

    `on_submit(method, value, tier=None)` valida a ativação e devolve (ok, motivo).
    O diálogo fecha-se sozinho quando ok é True, ou quando o utilizador desiste.
    """

    def __init__(self, root, license_dir, on_submit, on_cancel=None, language=DEFAULT_LANGUAGE):
        self._root = root
        self._license_dir = Path(license_dir)
        self._on_submit = on_submit
        self._on_cancel = on_cancel or (lambda: None)
        self._closing = False
        self.language = language

        self.win = tk.Toplevel(root)
        self.win.title(translate("Licença — CsvFast-FileConverter", self.language))
        self.win.geometry("580x560")
        self.win.resizable(False, False)
        self.win.transient(root)
        self.win.configure(bg=BG_WINDOW)
        self.win.protocol("WM_DELETE_WINDOW", self._cancel)

        self._build()
        self.win.grab_set()
        self.win.focus_set()

    # -- construção da UI ------------------------------------------------

    def _build(self):
        frm = tk.Frame(self.win, bg=BG_WINDOW, padx=18, pady=14)
        frm.pack(fill="both", expand=True)

        # Título
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
                translate("Escolha o método de ativação abaixo.", self.language)
            ),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        # --- Radio buttons: método de ativação ---
        radio_frm = tk.Frame(frm, bg=BG_WINDOW)
        radio_frm.pack(anchor="w", pady=(0, 10))

        self._method_var = tk.StringVar(value="account")

        rb_account = tk.Radiobutton(
            radio_frm,
            text=translate("Conta vinculada online", self.language),
            variable=self._method_var,
            value="account",
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 10),
            selectcolor=BG_WINDOW,
            activebackground=BG_WINDOW,
            activeforeground=BLUE_700,
            command=self._switch_method,
        )
        rb_account.pack(side="left", padx=(0, 15))

        rb_device = tk.Radiobutton(
            radio_frm,
            text=translate("Código do Dispositivo", self.language),
            variable=self._method_var,
            value="device",
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 10),
            selectcolor=BG_WINDOW,
            activebackground=BG_WINDOW,
            activeforeground=BLUE_700,
            command=self._switch_method,
        )
        rb_device.pack(side="left", padx=(0, 15))

        rb_code = tk.Radiobutton(
            radio_frm,
            text=translate("Código de ativação", self.language),
            variable=self._method_var,
            value="code",
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 10),
            selectcolor=BG_WINDOW,
            activebackground=BG_WINDOW,
            activeforeground=BLUE_700,
            command=self._switch_method,
        )
        rb_code.pack(side="left")

        # --- Painel: Conta (SaaS) ---
        self._panel_account = tk.Frame(frm, bg=BG_WINDOW)
        self._panel_account.pack(fill="both", expand=True)

        tk.Label(
            self._panel_account,
            text=translate("Conta vinculada online:", self.language),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            self._panel_account,
            text=translate("Email:", self.language),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        self._account_email_var = tk.StringVar()
        self._account_email_entry = tk.Entry(
            self._panel_account,
            textvariable=self._account_email_var,
            relief="solid",
            bg=WHITE,
            fg=GRAY_800,
            font=("Consolas", 10),
            borderwidth=1,
            highlightbackground=BLUE_700,
            highlightcolor=BLUE_700,
            highlightthickness=1,
        )
        self._account_email_entry.pack(fill="x", pady=(0, 6))

        tk.Label(
            self._panel_account,
            text=translate("Senha:", self.language),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        self._account_password_var = tk.StringVar()
        self._account_password_entry = tk.Entry(
            self._panel_account,
            textvariable=self._account_password_var,
            show="•",
            relief="solid",
            bg=WHITE,
            fg=GRAY_800,
            font=("Consolas", 10),
            borderwidth=1,
            highlightbackground=BLUE_700,
            highlightcolor=BLUE_700,
            highlightthickness=1,
        )
        self._account_password_entry.pack(fill="x", pady=(0, 6))

        # Botões da conta
        btn_account_frm = tk.Frame(self._panel_account, bg=BG_WINDOW)
        btn_account_frm.pack(fill="x")

        tk.Button(
            btn_account_frm,
            text=translate("Get License", self.language),
            command=self._get_license_from_account,
            bg=BLUE_700,
            fg=WHITE,
            activebackground=BLUE_900,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            width=14,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btn_account_frm,
            text=translate("Cancel", self.language),
            command=self._cancel,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            relief="flat",
            font=("Segoe UI", 9),
            width=10,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(10, 0))

        tk.Label(
            self._panel_account,
            text=translate("Refresh license list", self.language),
            bg=BG_WINDOW,
            fg=BLUE_700,
            font=("Segoe UI", 9, "underline"),
            cursor="hand2",
        ).pack(anchor="w", pady=(8, 0))

        # --- Painel: Código do Dispositivo (Device Code Flow) ---
        self._panel_device = tk.Frame(frm, bg=BG_WINDOW)

        tk.Label(
            self._panel_device,
            text=translate(
                "Gere um código no dispositivo e cole-o abaixo, ou envie o código "
                "para o fornecedor para ativar via email/WhatsApp.",
                self.language
            ),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        self._device_code_var = tk.StringVar()
        self._device_entry = tk.Entry(
            self._panel_device,
            textvariable=self._device_code_var,
            relief="solid",
            bg=WHITE,
            fg=GRAY_800,
            font=("Consolas", 10),
            borderwidth=1,
            highlightbackground=BLUE_700,
            highlightcolor=BLUE_700,
            highlightthickness=1,
        )
        self._device_entry.pack(fill="x", pady=(0, 6))

        btn_device_frm = tk.Frame(self._panel_device, bg=BG_WINDOW)
        btn_device_frm.pack(fill="x")

        tk.Button(
            btn_device_frm,
            text=translate("Gerar Código", self.language),
            command=self._generate_device_code,
            bg=BLUE_700,
            fg=WHITE,
            activebackground=BLUE_900,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            width=14,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btn_device_frm,
            text=translate("Verificar Código", self.language),
            command=self._verify_device_code,
            bg=BLUE_500,
            fg=WHITE,
            activebackground=BLUE_700,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            width=14,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            btn_device_frm,
            text=translate("Cancel", self.language),
            command=self._cancel,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            relief="flat",
            font=("Segoe UI", 9),
            width=10,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        # Ligação direta ao ecrã do SaaS onde o fornecedor cola o código.
        tk.Label(
            self._panel_device,
            text=translate(
                "O fornecedor cola este código no ShopSync para autorizar o dispositivo.",
                self.language
            ),
            bg=BG_WINDOW,
            fg=GRAY_600,
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        self._device_url_var = tk.StringVar()
        self._device_url_link = tk.Label(
            self._panel_device,
            textvariable=self._device_url_var,
            bg=BG_WINDOW,
            fg=BLUE_700,
            font=("Segoe UI", 8, "underline"),
            cursor="hand2",
        )
        self._device_url_link.pack(anchor="w", pady=(2, 0))
        self._device_url_link.bind("<Button-1>", self._open_device_page)
        self._device_url_var.set(DEVICE_ACTIVATION_URL)
        # Atualiza o link sempre que o código muda, para o browser abrir já
        # com o código preenchido no SaaS.
        self._device_code_var.trace_add("write", self._update_device_url)
        self._update_device_url()

        tk.Label(
            self._panel_device,
            text=translate("O código expira em 10 minutos.", self.language),
            bg=BG_WINDOW,
            fg=GRAY_600,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(4, 0))

        # --- Painel: Código de ativação ---
        self._panel_code = tk.Frame(frm, bg=BG_WINDOW)

        tk.Label(
            self._panel_code,
            text=translate("Cole abaixo a chave de ativação enviada pelo fornecedor (por email ou WhatsApp).", self.language),
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
            justify="left",
        ).pack(anchor="w", pady=(0, 4))

        self._code_entry = tk.Entry(
            self._panel_code,
            relief="solid",
            bg=WHITE,
            fg=GRAY_800,
            font=("Consolas", 10),
            borderwidth=1,
            highlightbackground=BLUE_700,
            highlightcolor=BLUE_700,
            highlightthickness=1,
        )
        self._code_entry.pack(fill="x", pady=(0, 6))

        btn_code_frm = tk.Frame(self._panel_code, bg=BG_WINDOW)
        btn_code_frm.pack(fill="x")

        tk.Button(
            btn_code_frm,
            text=translate("Activate", self.language),
            command=self._activate_code,
            bg=BLUE_700,
            fg=WHITE,
            activebackground=BLUE_900,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            width=14,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btn_code_frm,
            text=translate("Cancel", self.language),
            command=self._cancel,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            relief="flat",
            font=("Segoe UI", 9),
            width=10,
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(10, 0))

        # --- Status (comum) ---
        self._status_var = tk.StringVar()
        self._status_var.set("")
        self._status_label = tk.Label(
            frm,
            textvariable=self._status_var,
            bg=BG_WINDOW,
            fg=GRAY_600,
            font=("Segoe UI", 8),
            justify="left",
            wraplength=540,
        )
        self._status_label.pack(anchor="w", pady=(10, 0))

        # Inicializar com o método selecionado
        self._switch_method()

    def _switch_method(self):
        """Mostra/esconde os painéis conforme o método selecionado."""
        method = self._method_var.get()
        self._panel_account.pack_forget()
        self._panel_code.pack_forget()
        self._panel_device.pack_forget()

        if method == "account":
            self._panel_account.pack(fill="both", expand=True)
        elif method == "device":
            self._panel_device.pack(fill="both", expand=True)
        else:
            self._panel_code.pack(fill="both", expand=True)
        self._set_status("")

    def _set_status(self, text: str, fg: str = GRAY_600):
        """Mostra uma mensagem de status sem desabilitar o campo de entrada."""
        self._status_var.set(text)
        self._status_label.config(fg=fg)

    # -- handlers -------------------------------------------------------

    def _activate_code(self):
        """Valida a chave de ativação digitada/colada."""
        if self._closing:
            return
        key = self._code_entry.get().strip()
        if not key:
            self._set_status(translate("Por favor, cole a chave de ativação antes de continuar.", self.language), ERROR_FG)
            return

        self._set_status(translate("A verificar chave…", self.language), BLUE_700)
        self.win.update_idletasks()

        ok, message = verify_activation_key(key)

        if ok:
            self._closing = True
            self._set_status(f"{translate('Chave aceite.', self.language)}\n{message}", BLUE_700)
            # Passar a string da chave (não um caminho de ficheiro)
            self._on_submit("code", key)
            self.win.after(700, self._close)
        else:
            # a recusa fica no ecrã; o utilizador pode tentar outra chave
            self._set_status(message, ERROR_FG)

    def _generate_device_code(self):
        """Gera um código aleatório para o Device Code Flow."""
        import secrets
        import string

        # Gera código de 8 caracteres alfanuméricos
        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        self._device_code_var.set(code)

        # Copia para a área de transferência e abre o ecrã do SaaS, para o
        # utilizador só ter de colar o código no navegador.
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(code)
            self._set_status(
                translate(
                    "Código gerado e copiado. A abrir o ShopSync…",
                    self.language,
                ),
                GRAY_600,
            )
        except Exception:
            self._set_status(
                translate("Código gerado. Copie-o para o navegador.", self.language),
                GRAY_600,
            )

        self._open_device_page()

    def _update_device_url(self, *_args):
        """Reflete o código atual no link do ecrã do SaaS."""
        code = self._device_code_var.get().strip()
        if code:
            self._device_url_var.set(f"{DEVICE_ACTIVATION_URL}?code={code}")
        else:
            self._device_url_var.set(DEVICE_ACTIVATION_URL)

    def _open_device_page(self, _event=None):
        """Abre no navegador o ecrã do SaaS com o código preenchido."""
        import webbrowser

        url = self._device_url_var.get() or DEVICE_ACTIVATION_URL
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _verify_device_code(self):
        """Verifica se o código do dispositivo foi aprovado no SaaS."""
        if self._closing:
            return
        code = self._device_code_var.get().strip()
        if not code:
            self._set_status(translate("Por favor, insira o código do dispositivo.", self.language), ERROR_FG)
            return

        self._set_status(translate("A verificar código no servidor…", self.language), BLUE_700)
        self.win.update_idletasks()

        ok, message, tier = verify_device_code(code)

        if ok:
            self._closing = True
            self._set_status(f"{translate('Código aprovado.', self.language)}\n{message}", BLUE_700)
            # Passar código e tier
            self._on_submit("device", code, tier)
            self.win.after(700, self._close)
        else:
            self._set_status(message, ERROR_FG)

    def _get_license_from_account(self):
        """Tenta obter/validar licença associada à conta informada."""
        if self._closing:
            return
        email = self._account_email_var.get().strip()
        password = self._account_password_var.get().strip()
        if not email:
            self._set_status(translate("Por favor, insira o email da conta SaaS.", self.language), ERROR_FG)
            return
        if not password:
            self._set_status(translate("Por favor, insira a senha da conta SaaS.", self.language), ERROR_FG)
            return

        self._set_status(translate("A validar conta no servidor…", self.language), BLUE_700)
        self.win.update_idletasks()

        ok, message, tier = verify_saas_account(email, password)

        if ok:
            self._closing = True
            self._set_status(f"{translate('Conta validada.', self.language)}\n{message}", BLUE_700)
            # Passar email e tier
            self._on_submit("account", email, tier)
            self.win.after(700, self._close)
        else:
            self._set_status(message, ERROR_FG)

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
