import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.field_mapping as field_mapping
from gui.csv_converter_gui import build_categories


def test_massive_category_rule_matches_parent_and_descendants(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.add_massive_category_rule("Informática", "Loja INFORMÁTICA")
    assert field_mapping.apply_massive_category_rules(
        "Informática", "Portáteis", "Acessórios"
    ) == "Loja INFORMÁTICA"


def test_massive_category_rule_uses_priority(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.add_massive_category_rule("artigos", "Loja GERAL", priority=1)
    assert field_mapping.add_massive_category_rule("informática", "Loja INFORMÁTICA", priority=10)

    assert field_mapping.apply_massive_category_rules("Informática", "Artigos") == "Loja INFORMÁTICA"


def test_new_massive_rule_gets_higher_default_priority(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.add_massive_category_rule("Informática", "Loja ANTIGA")
    assert field_mapping.add_massive_category_rule("Informática", "Loja NOVA")

    assert field_mapping.apply_massive_category_rules("Informática") == "Loja NOVA"


def test_massive_rule_supports_multiple_exact_source_categories(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.set_massive_category_rules([
        {
            "description": "Artigos de informática",
            "source_categories": ["Computadores", "Portáteis"],
            "parent_category": "Loja INFORMÁTICA",
            "priority": 10,
        }
    ])

    assert field_mapping.apply_massive_category_rules("Computadores") == "Loja INFORMÁTICA"
    assert field_mapping.apply_massive_category_rules("Portáteis") == "Loja INFORMÁTICA"
    assert field_mapping.apply_massive_category_rules("Ferramentas", "Portáteis") == ""
    assert field_mapping.apply_massive_category_rules("Acessórios") == ""


def test_massive_rule_matches_sources_without_case_or_accents(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.set_massive_category_rules([
        {
            "description": "Eletrónica",
            "source_categories": ["Eletrónica e Tecnologias"],
            "parent_category": "Loja TECNOLOGIAS",
            "priority": 10,
        }
    ])

    assert field_mapping.apply_massive_category_rules("ELETRONICA E TECNOLOGIAS") == "Loja TECNOLOGIAS"


def test_legacy_massive_category_group_remains_supported(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.set_massive_category_rules([
        {
            "category_group": "Informática",
            "parent_category": "Loja INFORMÁTICA",
            "priority": 10,
        }
    ])

    assert field_mapping.apply_massive_category_rules("Informática") == "Loja INFORMÁTICA"


def test_category_settings_supports_more_than_ten(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    values = [f"Categoria {i}" for i in range(15)]
    assert field_mapping.set_category_settings(new_categories=values)
    assert field_mapping.get_category_settings()["new_categories"] == values


def test_highlights_brands_settings_supports_more_than_ten(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    values = [f"Destaque {i}" for i in range(15)]
    assert field_mapping.set_highlights_brands_settings(new_categories=values)
    assert field_mapping.get_highlights_brands_settings()["new_categories"] == values


def test_window_geometry_roundtrip(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    assert field_mapping.set_window_geometry("1200x800+100+50")
    assert field_mapping.get_window_geometry() == "1200x800+100+50"


def test_massive_parent_settings_do_not_require_clearing_keywords(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.set_category_settings(
        new_categories=["Loja informática"],
        cat_keywords=["portátil"],
    )
    assert field_mapping.set_category_settings(
        new_categories=["Loja informática", "Loja casa"],
        apply_to_all=False,
        selected_prefix="",
        use_parent=True,
    )

    settings = field_mapping.get_category_settings()
    assert settings["cat_keywords"] == ["portátil"]


def test_build_categories_keeps_original_hierarchy_under_massive_parent(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.add_massive_category_rule("Informática", "Loja INFORMÁTICA")

    row = {
        "design": "Portátil",
        "familia_principal": "Informática",
        "sub_familia": "Portáteis",
        "sub_sub_familia": "Ultrabooks",
    }
    result = build_categories(row, mapping={})

    assert result == (
        "Loja INFORMÁTICA,"
        "Loja INFORMÁTICA/Informática,"
        "Loja INFORMÁTICA/Informática/Portáteis,"
        "Loja INFORMÁTICA/Informática/Portáteis/Ultrabooks"
    )


def test_real_csv_supports_multiple_sources_in_one_massive_rule(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    source_path = Path(__file__).parent.parent / "csv_examples" / "produtos (3).csv"

    with source_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(__import__("csv").DictReader(handle, delimiter=";"))

    categories = sorted({row["categoria"] for row in rows if row.get("categoria")})
    selected = categories[:2]
    assert len(selected) == 2
    assert field_mapping.set_massive_category_rules([{
        "description": "Informática",
        "source_categories": selected,
        "parent_category": "Loja INFORMÁTICA",
        "priority": 10,
    }])

    matched = [
        row for row in rows
        if field_mapping.apply_massive_category_rules(row.get("categoria", ""), row.get("subcategoria", ""))
    ]
    expected = [row for row in rows if row.get("categoria") in selected]
    assert len(matched) == len(expected)


def test_real_supplier_csv_preserves_hierarchy_for_massive_rule(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    source_path = Path(__file__).parent.parent / "csv_examples" / "Download_de_produtos_em_CSV (26).csv"

    with source_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(__import__("csv").DictReader(handle, delimiter=";"))
    family = next(row["familia_principal"] for row in rows if row.get("familia_principal"))
    assert field_mapping.set_massive_category_rules([{
        "description": "Grupo real",
        "source_categories": [family],
        "parent_category": "Loja MASSIVA",
        "priority": 10,
    }])

    matched = next(row for row in rows if row.get("familia_principal") == family)
    result = build_categories(matched, mapping={})
    assert result.startswith("Loja MASSIVA,Loja MASSIVA/" + family)


def test_saving_massive_rule_keeps_description_sources_and_parent_without_duplicates(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.save_massive_category_rule(
        description="Artigos de informática",
        source_categories=["Computadores", "Portáteis"],
        parent_category="Loja INFORMÁTICA",
    )
    saved = field_mapping.get_massive_category_rules()
    assert len(saved) == 1
    rule_id = saved[0]["rule_id"]
    assert saved[0]["description"] == "Artigos de informática"
    assert saved[0]["source_categories"] == ["Computadores", "Portáteis"]
    assert saved[0]["parent_category"] == "Loja INFORMÁTICA"

    assert field_mapping.save_massive_category_rule(
        description="Artigos de informática",
        source_categories=["Computadores"],
        parent_category="Loja INFORMÁTICA",
        rule_id=rule_id,
    )
    updated = field_mapping.get_massive_category_rules()
    assert len(updated) == 1
    assert updated[0]["rule_id"] == rule_id
    assert updated[0]["source_categories"] == ["Computadores"]
    assert updated[0]["priority"] == 1


class TestMassiveCategoryMatching(unittest.TestCase):
    """Correspondência de regras massivas por caminho (correção do achado Critical).

    Usa _config_path isolado em tmp_path para não tocar na configuração persistente.
    """

    def setUp(self):
        self.tmp_config = Path(tempfile.mkdtemp()) / "field_mapping_config.json"
        self._orig_config_path = field_mapping._config_path
        field_mapping._config_path = lambda: self.tmp_config

    def tearDown(self):
        field_mapping._config_path = self._orig_config_path

    def test_massive_rule_matches_source_prefix_path_two_levels(self):
        """Caso crítico da review: origem gravada da coluna 2 ("A > B") casa em
        linha de dois níveis, independentemente de column_level."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica > Computadores", "Informatica > Monitores"],
            parent_category="Informatica",
        )

        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "", column_level="unique"
        ) == "Informatica"
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "", column_level="unique+subcats"
        ) == "Informatica"
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "", column_level="unique+subcats+subsubcats"
        ) == "Informatica"

        # Linha de um único nível nunca casa com a origem de dois níveis.
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "", "", column_level="unique+subcats+subsubcats"
        ) == ""

        # A origem "Informatica > Computadores" é prefixo por níveis do caminho
        # "Informatica > Computadores > Acer" (o caminho abre um nível novo).
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "Acer", column_level="unique+subcats+subsubcats"
        ) == "Informatica"

        # Origens de outros ramos não casam: "Informatica > Monitores" não é
        # prefixo de "Informatica > Computadores > Acer".
        only_monitores = Path(tempfile.mkdtemp()) / "field_mapping_config.json"
        field_mapping._config_path = lambda: only_monitores
        assert field_mapping.save_massive_category_rule(
            description="Monitores",
            source_categories=["Informatica > Monitores"],
            parent_category="Informatica",
        )
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "Acer", column_level="unique+subcats+subsubcats"
        ) == ""
        field_mapping._config_path = lambda: self.tmp_config

    def test_massive_rule_matches_source_full_path_three_levels(self):
        """Origem da coluna 3 ("A > B > C") casa no caminho completo de três níveis."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica > Computadores > Acer"],
            parent_category="Informatica",
        )

        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "Acer", column_level="unique"
        ) == "Informatica"
        # Dois níveis não bastam para uma origem de três níveis.
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "", column_level="unique+subcats"
        ) == ""

    def test_massive_rule_simple_column_one_source_still_matches(self):
        """Origens simples da coluna 1 (compatibilidade retroativa)."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica"],
            parent_category="Loja INFORMÁTICA",
        )

        assert field_mapping.apply_massive_category_rules(
            "Informatica", "", "", column_level="unique"
        ) == "Loja INFORMÁTICA"
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Portáteis", "", column_level="unique+subcats"
        ) == "Loja INFORMÁTICA"
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Portáteis", "Acer", column_level="unique+subcats+subsubcats"
        ) == "Loja INFORMÁTICA"

    def test_massive_rule_legacy_category_group_keeps_partial_behaviour(self):
        """Regras antigas com category_group mantêm correspondência parcial."""
        assert field_mapping.set_massive_category_rules([
            {"category_group": "Informática", "parent_category": "Loja INFORMÁTICA", "priority": 10},
        ])

        assert field_mapping.apply_massive_category_rules("Informática", "", "") == "Loja INFORMÁTICA"
        assert field_mapping.apply_massive_category_rules("Informática", "Portáteis", "") == "Loja INFORMÁTICA"

    def test_massive_rule_prefix_does_not_confuse_levels(self):
        """Origem "a" casa em "a > b" mas não em "ab > c" (prefixo por níveis)."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica"],
            parent_category="Loja INFORMÁTICA",
        )

        assert field_mapping.apply_massive_category_rules(
            "Informatica", "", "", column_level="unique"
        ) == "Loja INFORMÁTICA"
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Portateis", "", column_level="unique"
        ) == "Loja INFORMÁTICA"
        assert field_mapping.apply_massive_category_rules(
            "Outra Coisa", "", "", column_level="unique"
        ) == ""

    def test_massive_rule_three_level_source_not_match_two_level_row(self):
        """Origem de três níveis ("A > B > C") não casa em linha de dois níveis ("A > B")."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica > Computadores > Acer"],
            parent_category="Informatica",
        )

        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "Acer", column_level="unique"
        ) == "Informatica"
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "Computadores", "", column_level="unique+subcats"
        ) == ""
        assert field_mapping.apply_massive_category_rules(
            "Informatica", "", "", column_level="unique+subcats+subsubcats"
        ) == ""

    def test_column_level_nao_restringe_a_correspondencia_por_caminho(self):
        """Decisão documentada: com correspondência por caminho, o nível de
        coluna deixa de limitar a regra (a origem delimita os níveis)."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica > Computadores"],
            parent_category="Informatica",
        )

        resultados = {
            field_mapping.apply_massive_category_rules(
                "Informatica", "Computadores", "", column_level=nivel
            )
            for nivel in ("unique", "unique+subcats", "unique+subcats+subsubcats")
        }
        self.assertEqual(resultados, {"Informatica"})

    def test_massive_rule_from_grouping_applies_to_two_level_row(self):
        """Regra gravada por _apply_grouping_suggestions (origens em caminho, "A > B")
        é aplicada pela conversão numa linha de dois níveis."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica > Computadores", "Informatica > Monitores"],
            parent_category="Informatica",
        )

        row = {
            "design": "Portátil",
            "familia_principal": "Informatica",
            "sub_familia": "Computadores",
            "sub_sub_familia": "",
        }
        result = build_categories(row, mapping={})
        # A regra aplica e a hierarquia original fica sob o pai.
        self.assertIn("Informatica", result.split(","))
        self.assertIn("Informatica/Informatica/Computadores", result.split(","))

    def test_massive_rule_from_grouping_column3_applies_on_two_level_row(self):
        """Achado 3: regras da coluna 3 casam nas linhas de três níveis e, tal
        como as da coluna 2, não perdem o caso de dois níveis."""
        assert field_mapping.save_massive_category_rule(
            description="Informatica - Informatica",
            source_categories=["Informatica > Computadores > Acer"],
            parent_category="Informatica",
        )

        row_three = {
            "design": "Portátil Acer",
            "familia_principal": "Informatica",
            "sub_familia": "Computadores",
            "sub_sub_familia": "Acer",
        }
        result_three = build_categories(row_three, mapping={})
        self.assertIn("Informatica/Informatica/Computadores/Acer", result_three.split(","))

        # A origem de três níveis não é prefixo por níveis do caminho de dois
        # níveis: a regra não se aplica e as categorias ficam intactas.
        row_two = {
            "design": "Computador genérico",
            "familia_principal": "Informatica",
            "sub_familia": "Computadores",
            "sub_sub_familia": "",
        }
        self.assertEqual(
            build_categories(row_two, mapping={}),
            "Informatica,Informatica/Computadores",
        )


def test_massive_rule_descriptions_are_not_hardcoded_in_gui():
    gui_path = Path(__file__).parent.parent / "gui" / "csv_converter_gui.py"
    source = gui_path.read_text(encoding="utf-8")

    assert "default_descriptions =" not in source
    assert "Todas as linhas das categorias de artigos de informática" not in source


def test_massive_rules_column_explains_rule_purpose_in_european_portuguese():
    gui_path = Path(__file__).parent.parent / "gui" / "csv_converter_gui.py"
    source = gui_path.read_text(encoding="utf-8")

    assert 'translate("Lista de Regras", self.language)' in source
    assert "Insira as regras para associar grupos de categorias e as subcategorias a uma categoria pai." in source
    assert "Ex: Todas as linhas das categorias de artigos para o lar e casa enviar para..." in source


class TestGroupingSuggestionCoverage(unittest.TestCase):
    """Cobertura dos achados 3 e 4 da revisão final."""

    class _FakeGroupingApp:
        """Stand-in mínimo da App para testar `_apply_grouping_suggestions`."""

        def _refresh_massive_rules_list(self):
            pass

    def setUp(self):
        self.tmp_config = Path(tempfile.mkdtemp()) / "field_mapping_config.json"
        self._orig_config_path = field_mapping._config_path
        field_mapping._config_path = lambda: self.tmp_config

    def tearDown(self):
        field_mapping._config_path = self._orig_config_path

    def _apply(self, sugestoes):
        import gui.csv_converter_gui as gui

        app = self._FakeGroupingApp()
        return gui.App._apply_grouping_suggestions(app, sugestoes)

    def test_apply_grouping_suggestions_inclui_familia_para_cobrir_a_area(self):
        """Achado 3: com a fonte na coluna 2, gravar só "A > B" deixava fora os
        produtos da mesma família (ex.: "A > Monitores"). A regra gravada passa
        a incluir também a família."""
        gravadas = self._apply({"Informatica": ["Informatica > Computadores"]})

        self.assertEqual(gravadas, 1)
        regras = field_mapping.get_massive_category_rules()
        self.assertEqual(len(regras), 1)
        self.assertEqual(
            regras[0]["source_categories"],
            ["Informatica > Computadores", "Informatica"],
        )
        # O produto da mesma área que não está na origem fica coberto pela família.
        self.assertEqual(
            field_mapping.apply_massive_category_rules("Informatica", "Monitores"),
            "Informatica",
        )

    def test_apply_grouping_suggestions_nao_duplica_familia_quando_ja_presente(self):
        self._apply({"Informatica": ["Informatica"]})

        regras = field_mapping.get_massive_category_rules()
        self.assertEqual(regras[0]["source_categories"], ["Informatica"])

    def test_sugestoes_falhadas_mostram_erro_distinto(self):
        """Achado 4: uma exceção do motor não pode aparecer como "não foram
        encontradas sugestões"."""
        import gui.csv_converter_gui as gui

        # Sem Tkinter: um objeto simples com os atributos que o diálogo usa.
        app = SimpleNamespace(language="pt-PT")
        app._grouping_source_column = lambda: (["Informatica"], "Categorias únicas")

        def explode(_categorias):
            raise RuntimeError("motor avariado")

        self._orig_suggest = gui.suggest_groupings
        self._orig_showerror = gui.messagebox.showerror
        gui.suggest_groupings = explode
        chamadas = []
        gui.messagebox.showerror = (
            lambda titulo, texto, parent=None: chamadas.append((titulo, texto))
        )
        try:
            gui.App._open_grouping_suggestions_dialog(app)
        finally:
            gui.suggest_groupings = self._orig_suggest
            gui.messagebox.showerror = self._orig_showerror

        self.assertEqual(len(chamadas), 1)
        self.assertEqual(chamadas[0][0], "Erro")
        self.assertIn("erro ao gerar as sugestões", chamadas[0][1])


def test_i18n_catalog_contains_all_supported_languages():
    from core.i18n import translate

    assert translate("Mapeamento Massivo", "pt-PT") == "Mapeamento Massivo"
    assert translate("Mapeamento Massivo", "pt-BR") == "Mapeamento em Massa"
    assert translate("Mapeamento Massivo", "en") == "Mass Category Mapping"


def test_language_setting_supports_european_brazilian_portuguese_and_english(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.set_language("pt-BR")
    assert field_mapping.get_language() == "pt-BR"
    assert field_mapping.set_language("en")
    assert field_mapping.get_language() == "en"
    assert field_mapping.set_language("invalid")
    assert field_mapping.get_language() == "pt-PT"


def test_saving_same_legacy_description_updates_without_duplicate(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)

    assert field_mapping.set_massive_category_rules([{
        "category_group": "Informática",
        "parent_category": "Loja ANTIGA",
        "priority": 4,
    }])
    assert field_mapping.save_massive_category_rule(
        description="Informática",
        source_categories=["Computadores"],
        parent_category="Loja NOVA",
    )

    saved = field_mapping.get_massive_category_rules()
    assert len(saved) == 1
    assert saved[0]["source_categories"] == ["Computadores"]
    assert saved[0]["parent_category"] == "Loja NOVA"
