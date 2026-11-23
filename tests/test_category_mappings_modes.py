#!/usr/bin/env python3
"""
Testes unitários para os 3 modos de mapeamento de categorias, limpeza total e mapa de categorias.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gui.csv_converter_gui import build_categories
from core.field_mapping import (
    add_massive_category_rule, get_massive_category_rules, set_massive_category_rules,
    clear_keyword_rules
)


class TestCategoryMappingModes(unittest.TestCase):
    """Testa os três modos de mapeamento de categorias e funções auxiliares."""

    def setUp(self):
        set_massive_category_rules([])

    def test_mapping_modes_persistence(self):
        """Verifica se o modo de mapeamento (mapping_mode) é guardado corretamente na regra."""
        add_massive_category_rule(
            category_group="Informatica - Portateis",
            parent_category="Loja Tech",
            mapping_mode=1
        )
        rules = get_massive_category_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["mapping_mode"], 1)

    def test_mode_1_conversion(self):
        """Modo 1: Agrupa subcategorias na categoria pai sem enviar a categoria única."""
        add_massive_category_rule(
            category_group="Informatica",
            parent_category="Tecnologia",
            mapping_mode=1
        )
        # Atualizar source_categories para cobrir a família
        rules = get_massive_category_rules()
        rules[0]["source_categories"] = ["Informatica"]
        set_massive_category_rules(rules)

        row = {
            "familia_principal": "Informatica",
            "sub_familia": "Portateis",
            "sub_sub_familia": "MacBook"
        }
        res = build_categories(row, mapping={})
        # Modo 1 espera: "Tecnologia/Portateis" e "Tecnologia/Portateis/MacBook" (sem "Tecnologia/Informatica")
        self.assertIn("Tecnologia/Portateis", res)
        self.assertNotIn("Tecnologia/Informatica", res)

    def test_mode_3_conversion(self):
        """Modo 3: Envia apenas a subcategoria diretamente sob a categoria pai."""
        add_massive_category_rule(
            category_group="Informatica",
            parent_category="Tecnologia",
            mapping_mode=3
        )
        rules = get_massive_category_rules()
        rules[0]["source_categories"] = ["Informatica"]
        set_massive_category_rules(rules)

        row = {
            "familia_principal": "Informatica",
            "sub_familia": "Portateis",
            "sub_sub_familia": ""
        }
        res = build_categories(row, mapping={})
        # Modo 3 espera apenas "Tecnologia/Portateis"
        self.assertEqual(res, "Tecnologia/Portateis")


if __name__ == "__main__":
    unittest.main()
