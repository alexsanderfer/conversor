import sys
from pathlib import Path

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


def test_massive_rules_column_explains_rule_purpose_in_european_portuguese():
    gui_path = Path(__file__).parent.parent / "gui" / "csv_converter_gui.py"
    source = gui_path.read_text(encoding="utf-8")

    assert 'translate("Lista de Regras", self.language)' in source
    assert "Insira as regras para associar grupos de categorias e as subcategorias a uma categoria pai." in source
    assert "Ex: Todas as linhas das categorias de artigos para o lar e casa enviar para..." in source


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
