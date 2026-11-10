import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.csv_converter_gui import _calc_price
from core.field_mapping import set_price_settings, get_price_settings, set_active_profile

def test_price_calculations():
    print("Testando cálculos de preços...")
    set_active_profile("Default")

    # Teste 1: Margem simples (40%)
    set_price_settings(profit_percentage=40.0, iva_percentage=0.0, shipping_cost=0.0, price_formula="margin")
    res = _calc_price("100.00")
    print(f"Custo 100.00 com margem 40% -> Resultado: {res} (Esperado: 140.0)")
    assert float(res) == 140.0, f"Esperado 140.0, obtido {res}"

    # Teste 2: Fórmula detalhada (Custo 100 + Lucro 40% = 140 + Portes 5 = 145 * 23% IVA = 178.35)
    set_price_settings(profit_percentage=40.0, iva_percentage=23.0, shipping_cost=5.0, price_formula="detailed")
    res_detailed = _calc_price("100.00")
    print(f"Custo 100.00, Lucro 40%, Portes 5.0, IVA 23% (detailed) -> Resultado: {res_detailed} (Esperado: 178.35)")
    assert float(res_detailed) == 178.35, f"Esperado 178.35, obtido {res_detailed}"

    # Teste 3: Fórmula margin mas com IVA e portes definidos (deve aplicar automaticamente)
    set_price_settings(profit_percentage=40.0, iva_percentage=23.0, shipping_cost=5.0, price_formula="margin")
    res_auto = _calc_price("100.00")
    print(f"Custo 100.00 com formula margin mas IVA/Portes definidos -> Resultado: {res_auto} (Esperado: 178.35)")
    assert float(res_auto) == 178.35, f"Esperado 178.35, obtido {res_auto}"

    print("Todos os testes de preços passaram com sucesso!")

if __name__ == "__main__":
    test_price_calculations()
