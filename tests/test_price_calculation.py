import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.csv_converter_gui import _calc_price
from core.field_mapping import set_price_settings, get_price_settings, set_active_profile

def test_price_calculations():
    print("Testando cálculos de preços...")
    set_active_profile("Default")

    # Teste 1: Apenas margem (IVA = 0, Portes = 0) -> 100 * 1.40 = 140.0
    set_price_settings(profit_percentage=40.0, iva_percentage=0.0, shipping_cost=0.0)
    res = _calc_price("100.00")
    print(f"Custo 100.00, Lucro 40%, IVA 0, Portes 0 -> Resultado: {res} (Esperado: 140.0)")
    assert float(res) == 140.0, f"Esperado 140.0, obtido {res}"

    # Teste 2: Com portes e IVA (Custo 100 + Lucro 40% = 140 + Portes 5 = 145 * 23% IVA = 178.35)
    set_price_settings(profit_percentage=40.0, iva_percentage=23.0, shipping_cost=5.0)
    res_detailed = _calc_price("100.00")
    print(f"Custo 100.00, Lucro 40%, Portes 5.0, IVA 23% -> Resultado: {res_detailed} (Esperado: 178.35)")
    assert float(res_detailed) == 178.35, f"Esperado 178.35, obtido {res_detailed}"

    # Teste 3: Apenas portes (sem IVA) -> 100 * 1.40 + 5 = 145.0
    set_price_settings(profit_percentage=40.0, iva_percentage=0.0, shipping_cost=5.0)
    res_shipping_only = _calc_price("100.00")
    print(f"Custo 100.00, Lucro 40%, Portes 5.0, IVA 0 -> Resultado: {res_shipping_only} (Esperado: 145.0)")
    assert float(res_shipping_only) == 145.0, f"Esperado 145.0, obtido {res_shipping_only}"

    print("Todos os testes de preços passaram com sucesso!")

if __name__ == "__main__":
    test_price_calculations()
