#!/usr/bin/env python3
"""
Regression tests for the CATEGORIAS M tab category columns.

Guards against the bug where ``_filter_massive_categories`` referenced widgets
that were never created (``_massive_search_var``, ``_massive_unique_text``,
``_massive_subcat_text``, ``_massive_unique_title_var``,
``_massive_subcat_title_var``), raising AttributeError after loading a CSV.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tkinter as tk
    from gui.csv_converter_gui import App
except Exception:  # pragma: no cover - ambiente sem Tkinter
    tk = None


@unittest.skipIf(tk is None, "Tkinter indisponível")
class TestColunasMassivas(unittest.TestCase):
    """As três colunas da aba CATEGORIAS M têm de refletir as categorias do CSV."""

    def setUp(self):
        self.app = App()
        self.app.withdraw()

    def tearDown(self):
        self.app.destroy()

    def _preencher(self):
        """Simula o que update_categories faz após ler um CSV."""
        self.app._unique_categories = ["Informática", "Moda", "Ferramentas"]
        self.app._subcat_categories = [
            "Informática > Portáteis",
            "Moda > Calçado",
            "Ferramentas > Manual",
        ]
        self.app._massive_unique_categories = list(self.app._unique_categories)
        self.app._massive_unique_with_subcats = list(self.app._subcat_categories)
        self.app._massive_unique_with_subsubcats = [
            "Informática > Portáteis > Acer",
            "Moda > Calçado > Sapatilhas",
        ]
        self.app._massive_subsubcat_categories = self.app._massive_unique_with_subsubcats

    def test_filter_nao_lanca_excecao(self):
        """O bug original: AttributeError ao chamar _filter_massive_categories."""
        self._preencher()
        try:
            self.app._filter_massive_categories()
        except AttributeError as exc:  # pragma: no cover - regressão
            self.fail(f"_filter_massive_categories lançou AttributeError: {exc}")

    def test_colunas_preenchidas(self):
        """Cada coluna mostra a sua lista, com a contagem no título."""
        self._preencher()
        self.app._filter_massive_categories()

        self.assertIn("Informática", self.app._massive_col1_text.get("1.0", "end"))
        self.assertIn("Informática > Portáteis", self.app._massive_col2_text.get("1.0", "end"))
        self.assertIn(
            "Informática > Portáteis > Acer",
            self.app._massive_col3_text.get("1.0", "end"),
        )
        self.assertIn("3", self.app._massive_col1_title_var.get())
        self.assertIn("2", self.app._massive_col3_title_var.get())

    def test_pesquisa_filtra_colunas(self):
        """O campo de pesquisa existe e filtra as três colunas."""
        self._preencher()
        self.assertTrue(hasattr(self.app, "_massive_search_var"))

        self.app._massive_search_var.set("inform")
        self.assertIn("1 de 3", self.app._massive_col1_title_var.get())
        self.assertIn("Informática", self.app._massive_col1_text.get("1.0", "end"))
        self.assertNotIn("Ferramentas", self.app._massive_col1_text.get("1.0", "end"))

        self.app._massive_search_var.set("")
        self.assertIn("CATEGORIAS", self.app._massive_col1_title_var.get())

    def test_load_columns_reflete_listas_internas(self):
        """_load_massive_category_columns alimenta as colunas a partir das listas internas."""
        self._preencher()
        self.app._load_massive_category_columns()

        self.assertIn("Informática", self.app._massive_col1_text.get("1.0", "end"))
        self.assertIn("Moda > Calçado", self.app._massive_col2_text.get("1.0", "end"))
        self.assertIn(
            "Moda > Calçado > Sapatilhas",
            self.app._massive_col3_text.get("1.0", "end"),
        )


if __name__ == "__main__":
    unittest.main()
