import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.csv_converter_gui import process_csv, _calc_price
from core.field_mapping import (
    set_price_settings, set_active_profile,
    add_massive_category_rule, set_massive_category_rules, get_massive_category_rules
)

def run_integration_test():
    print("Iniciando teste de integração com csv_examples/produtos_10.csv...")
    set_active_profile("Default")

    # 1. Configurar preços (ex: 15% lucro, 23% IVA) e testar preço de 25,20 ou o primeiro do CSV (1011.89)
    set_price_settings(profit_percentage=15.0, iva_percentage=23.0, shipping_cost=0.0)
    p_test = _calc_price("25.20")
    print(f"Preço fornecedor 25.20 -> Calculado: {p_test} (Esperado: 35.65)")
    assert float(p_test) == 35.65, f"Esperado 35.65, obtido {p_test}"

    # 2. Configurar regra massiva (Separador M): "Recondicionados" -> "Computadores"
    set_massive_category_rules([])
    add_massive_category_rule(category_group="Recondicionados", parent_category="Computadores e Eletrónica", mapping_mode=2)
    rules = get_massive_category_rules()
    rules[0]["source_categories"] = ["Recondicionados"]
    set_massive_category_rules(rules)

    csv_path = Path("csv_examples/produtos_10.csv")
    if not csv_path.is_file():
        print("Ficheiro csv_examples/produtos_10.csv não encontrado.")
        return

    # 3. Testar conversão completa
    print("\n--- Testando Conversão Completa ---")
    n_total, out_total, rem_unav, rem_not_mapped, rem_not_rule = process_csv(
        str(csv_path), output_dir="dist", filter_to_rules_only=False
    )
    print(f"Total convertidas: {n_total} linhas. Guardado em: {out_total}")

    # 4. Testar conversão restrita a regras (filter_to_rules_only=True)
    print("\n--- Testando Conversão Restrita a Regras (Apenas 'Recondicionados') ---")
    n_rules, out_rules, rem_unav, rem_not_mapped, rem_not_rule = process_csv(
        str(csv_path), output_dir="dist", filter_to_rules_only=True
    )
    print(f"Convertidas com regra: {n_rules} linhas. Linhas ignoradas sem regra: {rem_not_rule}")
    print(f"Guardado em: {out_rules}")

    print("\nTeste de integração com ficheiro de exemplo concluído com SUCESSO!")

if __name__ == "__main__":
    run_integration_test()
