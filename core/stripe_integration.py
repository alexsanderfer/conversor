"""
Stripe integration placeholder for license purchasing.
This module will be implemented when ready to accept payments.
"""

import webbrowser
from pathlib import Path
from tkinter import messagebox
from core.i18n import translate, DEFAULT_LANGUAGE
from gui.theme import BLUE_700, BLUE_900, WHITE


def open_stripe_checkout(language: str = DEFAULT_LANGUAGE):
    """
    Abre a página de checkout do Stripe para compra de licença.
    Por enquanto, apenas mostra uma mensagem informativa.
    """
    # URL de exemplo do Stripe - será substituída quando houver conta configurada
    stripe_url = "https://buy.stripe.com/test_your-checkout-link-here"

    try:
        webbrowser.open(stripe_url)
        messagebox.showinfo(
            translate("Stripe Checkout", language),
            translate("Redirecionando para a página de pagamento Stripe...", language) + "\n\n" +
            translate("Quando o pagamento for concluído, a licença será enviada por e-mail.", language) + "\n" +
            translate("Este é um link de teste - substitua pela URL real do Stripe quando pronto.", language)
        )
    except Exception as exc:
        messagebox.showerror(
            translate("Erro", language),
            translate("Não foi possível abrir o navegador para pagamento:", language) + f"\n{exc}"
        )


def is_stripe_configured(language: str = DEFAULT_LANGUAGE) -> bool:
    """
    Verifica se o Stripe está configurado (placeholder).
    Retorna False até que a integração seja implementada.
    """
    return False


def get_license_price(language: str = DEFAULT_LANGUAGE) -> str:
    """
    Retorna o preço da licença (placeholder).
    """
    return translate("R$ 99,90", language)