"""
Stripe integration placeholder for license purchasing.
This module will be implemented when ready to accept payments.
"""

import webbrowser
from pathlib import Path
from tkinter import messagebox
from theme import GREEN_700, GREEN_900, WHITE


def open_stripe_checkout():
    """
    Abre a página de checkout do Stripe para compra de licença.
    Por enquanto, apenas mostra uma mensagem informativa.
    """
    # URL de exemplo do Stripe - será substituída quando houver conta configurada
    stripe_url = "https://buy.stripe.com/test_your-checkout-link-here"

    try:
        webbrowser.open(stripe_url)
        messagebox.showinfo(
            "Stripe Checkout",
            "Redirecionando para a página de pagamento Stripe...\n\n"
            "Quando o pagamento for concluído, a licença será enviada por e-mail.\n"
            "Este é um link de teste - substitua pela URL real do Stripe quando pronto."
        )
    except Exception as exc:
        messagebox.showerror(
            "Erro",
            f"Não foi possível abrir o navegador para pagamento:\n{exc}"
        )


def is_stripe_configured():
    """
    Verifica se o Stripe está configurado (placeholder).
    Retorna False até que a integração seja implementada.
    """
    return False


def get_license_price():
    """
    Retorna o preço da licença (placeholder).
    """
    return "R$ 99,90"