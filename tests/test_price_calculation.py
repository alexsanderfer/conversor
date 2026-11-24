import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.csv_converter_gui import _calc_price
from core.field_mapping import set_price_settings, get_price_settings, set_active_profile

def test_price_calculations():
    print("Testando cálculos de preços...")
    set_active_profile("Default")

    # Teste 1: Custo 1011.89, Lucro 40%, IVA 23%, Portes 6.50
    set_price_settings(profit_percentage=40.0, iva_percentage=23.0, shipping_cost=6.50)
    res = _calc_price("1011.89")
    print(f"Custo 1011.89, Lucro 40%, IVA 23%, Portes 6.50 -> Resultado: {res} (Esperado: 1748.97)")
    assert float(res) == 1748.97, f"Esperado 1748.97, obtido {res}"

    # Teste 2 (ERRO 2): Custo 25.20, Lucro 15%, IVA 23% (Lucro » IVA)
    # Cálculo: (25.20 * 1.15) * 1.23 = 28.98 * 1.23 = 35.6454 -> 35.65
    set_price_settings(
        profit_percentage=15.0,
        iva_percentage=23.0,
        shipping_cost=0.0,
        price_line={
            "profit_percentage": 15.0,
            "iva_percentage": 23.0,
            "shipping_cost": 0.0,
            "price_formula": "Lucro, IVA, Portes",
            "active": True,
        }
    )
    # Simular guardadas repetidas para testar que não duplica nem multiplica em cascata
    for _ in range(5):
        set_price_settings(
            profit_percentage=15.0,
            iva_percentage=23.0,
            shipping_cost=0.0,
            price_line={
                "profit_percentage": 15.0,
                "iva_percentage": 23.0,
                "shipping_cost": 0.0,
                "price_formula": "Lucro, IVA, Portes",
                "active": True,
            }
        )
    res2 = _calc_price("25.20")
    print(f"Custo 25.20, Lucro 15%, IVA 23% (após várias gravações) -> Resultado: {res2} (Esperado: 35.65)")
    assert float(res2) == 35.65, f"Esperado 35.65, obtido {res2}"

    print("Todos os testes de preços passaram com sucesso!")

if __name__ == "__main__":
    test_price_calculations()
