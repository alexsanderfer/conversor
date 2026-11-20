#!/usr/bin/env python3
"""
Regression tests para a coluna 1 da aba CATEGORIAS i (mapeamento avançado).

A coluna de categorias únicas passa a mostrar apenas as categorias que ainda
não têm regra de mapeamento (`apply_keyword_rules(categoria, "")` vazio);
a coluna de subcategorias mantém-se completa.

A configuração do core é isolada num diretório temporário para não tocar no
`field_mapping_config.json` do ambiente de desenvolvimento.
"""
import sys
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import core.field_mapping as field_mapping
    from gui.csv_converter_gui import App
except Exception:  # pragma: no cover - ambiente sem Tkinter/dependências
    tk = None


@unittest.skipIf(tk is None, "Tkinter indisponível")
class TestCategoriasNaoMapeadas(unittest.TestCase):
    def setUp(self):
        # Config isolada: os testes de mapeamento não alteram o ficheiro real.
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        config_path = Path(self._tmp.name) / "field_mapping_config.json"
        self._original_config_path = field_mapping._config_path
        field_mapping._config_path = lambda: config_path
        self.addCleanup(setattr, field_mapping, "_config_path", self._original_config_path)

        self.app = App()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.app._unique_categories = ["Informática", "Moda", "Ferramentas"]
        self.app._subcat_categories = [
            "Informática > Portáteis",
            "Moda > Calçado",
            "Ferramentas > Manual",
        ]

    def _adicionar_regras(self, *categorias):
        """Repõe as regras com as categorias indicadas (config isolada)."""
        rules = [
            {"category": c, "subcategory": "", "parent_category": "Loja TESTE", "priority": 10}
            for c in categorias
        ]
        self.assertTrue(field_mapping.set_keyword_rules(rules))

    def test_sem_regras_todas_ficam(self):
        """Sem regras, todas as categorias únicas estão por mapear."""
        self.assertEqual(
            sorted(self.app._categorias_nao_mapeadas()),
            sorted(["Informática", "Moda", "Ferramentas"]),
        )

    def test_categoria_mapeada_sai_da_lista(self):
        """Uma regra para 'Informática' retira essa categoria das não-mapeadas."""
        self._adicionar_regras("Informática")
        self.assertEqual(sorted(self.app._categorias_nao_mapeadas()), ["Ferramentas", "Moda"])

    def test_coluna_1_mostra_so_nao_mapeadas(self):
        """_filter_categories alimenta a coluna 1 com as não-mapeadas."""
        self._adicionar_regras("Informática")
        self.app._filter_categories()

        texto = self.app._cat_unique_text.get("1.0", "end")
        self.assertIn("Ferramentas", texto)
        self.assertIn("Moda", texto)
        self.assertNotIn("Informática", texto)

    def test_titulo_coluna_1_com_contagens(self):
        """Título: (N de M) sem pesquisa e (K de N de M) com pesquisa."""
        self._adicionar_regras("Informática")

        self.app._cat_search_var.set("")
        self.app._filter_categories()
        self.assertEqual(
            self.app._cat_unique_title_var.get(),
            "CATEGORIAS ÚNICAS SEM MAPEAMENTO (2 de 3)",
        )

        self.app._cat_search_var.set("ferr")
        self.assertIn("(1 de 2 de 3)", self.app._cat_unique_title_var.get())

        self.app._cat_search_var.set("")

    def test_pesquisa_sem_resultados_mostra_lista_vazia(self):
        """Com pesquisa ativa e sem resultados, a coluna mostra '(nenhuma categoria)'."""
        self.app._cat_search_var.set("zzz")
        self.app._filter_categories()

        texto = self.app._cat_unique_text.get("1.0", "end").strip()
        self.assertEqual(texto, "(nenhuma categoria)")

    def test_todas_mapeadas_mostram_texto_explicito(self):
        """Com N == 0, o texto diz que todas estão mapeadas."""
        self._adicionar_regras("Informática", "Moda", "Ferramentas")

        self.app._filter_categories()

        texto = self.app._cat_unique_text.get("1.0", "end").strip()
        self.assertEqual(texto, "(todas as categorias mapeadas)")
        self.assertEqual(
            self.app._cat_unique_title_var.get(),
            "CATEGORIAS ÚNICAS SEM MAPEAMENTO (0 de 3)",
        )

    def test_coluna_2_mantem_subcategorias_completas(self):
        """A coluna de subcategorias não é filtrada pelas regras."""
        self._adicionar_regras("Informática")
        self.app._filter_categories()

        texto = self.app._cat_subcat_text.get("1.0", "end")
        self.assertIn("Informática > Portáteis", texto)
        self.assertIn("Ferramentas > Manual", texto)

    def test_combo_avancado_mantem_todas_as_categorias(self):
        """O dropdown do mapeamento avançado continua com todas as categorias."""
        self._adicionar_regras("Informática")
        self.app._refresh_cat_adv_combos()

        valores = list(self.app._adv_cat_combo["values"])
        self.assertIn("Informática", valores)
        self.assertIn("Ferramentas", valores)


if __name__ == "__main__":
    unittest.main()
