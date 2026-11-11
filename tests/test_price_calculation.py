import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.csv_converter_gui import _calc_price
from core.field_mapping import set_price_settings, get_price_settings, set_active_profile

def test_price_calculations():
    print("Testando cálculos de preços...")
    set_active_profile("Default")

    # Teste 1: Custo 1011.89, Lucro 40%, IVA 23%, Portes 6.50
    # Cálculo esperado: ((1011.89 * 1.40) * 1.23) + 6.50 = 1416.646 * 1.23 + 6.50 = 1742.47458 + 6.50 = 1748.97458 -> 1748.97
    set_price_settings(profit_percentage=40.0, iva_percentage=23.0, shipping_cost=6.50)
    res = _calc_price("1011.89")
    print(f"Custo 1011.89, Lucro 40%, IVA 23%, Portes 6.50 -> Resultado: {res} (Esperado: 1748.97)")
    assert float(res) == 1748.97, f"Esperado 1748.97, obtido {res}"

    print("Todos os testes de preços passaram com sucesso!")

if __name__ == "__main__":
    test_price_calculations()
