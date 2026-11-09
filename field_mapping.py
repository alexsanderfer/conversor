"""
Field mapping configuration for CSV converter.

This module provides a flexible field mapping system that allows users
to map their CSV column names to the expected Jumpseller format.

The mapping is a dictionary where:
- Key: expected field name (used in conversion logic)
- Value: actual column name in the source CSV

Users can customize this mapping to support different CSV formats.

Perfis de fornecedor
--------------------
O mapeamento pode ser guardado por perfil de fornecedor, para que cada
fornedor use o seu próprio mapeamento sem misturar configurações.

O ficheiro `field_mapping_config.json` tem esta estrutura:

    {
        "active_profile": "NomeDoFornedor",
        "profiles": {
            "NomeDoFornedor": { "design": "...", ... },
            "OutroFornedor": { ... }
        }
    }

Para manter compatibilidade com ficheiros antigos (dict plano), o módulo
trata esses ficheiros como o perfil "Padrão".
"""

import json
import os
import sys
from pathlib import Path

# Default field mapping - maps expected names to source column names.
# By default, the mapping is empty, which means the converter expects
# the CSV to already contain the expected column names (design, codigo, ref, etc.).
# If your CSV uses different column names, configure the mapping via the
# "Mapear Campos..." button in the GUI, or edit field_mapping_config.json manually.

DEFAULT_FIELD_MAPPING = {
    # Empty by default - any CSV with expected column names works out of the box.
    # To support CSVs with different column names, add mappings here:
    # "design": "nome",       # if your CSV uses "nome" instead of "design"
    # "codigo": "codbarras",  # if your CSV uses "codbarras" instead of "codigo"
    # "ref": "referencia",    # if your CSV uses "referencia" instead of "ref"
}

# Perfil usado quando o ficheiro de configuração tem o formato antigo (dict plano).
_PROFILE_DEFAULT = "Padrão"

# Margem de lucro padrão (1.40 = 40% de lucro)
_DEFAULT_PROFIT_MARGIN = 1.40


def _config_path():
    # Use AppData for persistent storage (works both in dev and in PyInstaller exe)
    try:
        if getattr(sys, 'frozen', False):
            base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConversorJumpseller"
            base_dir.mkdir(parents=True, exist_ok=True)
            config_file = base_dir / "field_mapping_config.json"
            # Migrate from old location if exists
            old_config = Path(sys._MEIPASS) / "field_mapping_config.json"
            if not config_file.exists() and old_config.exists():
                try:
                    import shutil
                    shutil.copy2(old_config, config_file)
                except Exception:
                    pass
            # Also check next to exe
            if not config_file.exists():
                exe_dir = Path(sys.executable).parent
                exe_config = exe_dir / "field_mapping_config.json"
                if exe_config.exists():
                    try:
                        import shutil
                        shutil.copy2(exe_config, config_file)
                    except Exception:
                        pass
            # Also check current dir
            if not config_file.exists():
                cwd_config = Path.cwd() / "field_mapping_config.json"
                if cwd_config.exists():
                    try:
                        import shutil
                        shutil.copy2(cwd_config, config_file)
                    except Exception:
                        pass
            return config_file
    except Exception:
        pass
    # Development mode
    return Path(__file__).parent / "field_mapping_config.json"


def _read_config():
    """Lê o ficheiro de configuração e devolve a estrutura completa."""
    path = _config_path()
    default_settings = {
        "profit_margin": _DEFAULT_PROFIT_MARGIN,
        "profit_percentage": 40.0,
        "iva_percentage": 0.0,
        "shipping_cost": 0.0,
        "price_formula": "margin"
    }
    if not path.is_file():
        return {
            "active_profile": _PROFILE_DEFAULT,
            "profiles": {},
            "settings": dict(default_settings)
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        try:
            if path.is_file():
                backup = path.with_suffix(path.suffix + ".bak")
                import shutil
                shutil.copy2(path, backup)
        except Exception:
            pass
        return {
            "active_profile": _PROFILE_DEFAULT,
            "profiles": {},
            "settings": dict(default_settings)
        }

    # Compatibilidade: formato antigo era um dict plano de mapeamento.
    needs_write_back = False
    if isinstance(data, dict) and "profiles" not in data:
        data = {
            "active_profile": _PROFILE_DEFAULT,
            "profiles": {_PROFILE_DEFAULT: data},
            "settings": dict(default_settings)
        }
        needs_write_back = True
    elif not isinstance(data, dict):
        data = {
            "active_profile": _PROFILE_DEFAULT,
            "profiles": {},
            "settings": dict(default_settings)
        }
        needs_write_back = True
    else:
        # Garantir que todas as seções necessárias existam
        data.setdefault("active_profile", _PROFILE_DEFAULT)
        if not isinstance(data.get("profiles"), dict):
            data["profiles"] = {}
        if not isinstance(data.get("settings"), dict):
            data["settings"] = dict(default_settings)
            needs_write_back = True
        else:
            if "profit_margin" not in data["settings"]:
                data["settings"]["profit_margin"] = _DEFAULT_PROFIT_MARGIN
                needs_write_back = True
            if "profit_percentage" not in data["settings"]:
                try:
                    pm = float(data["settings"].get("profit_margin", 1.4))
                    data["settings"]["profit_percentage"] = round((pm - 1.0) * 100.0, 2)
                except Exception:
                    data["settings"]["profit_percentage"] = 40.0
                needs_write_back = True
            for k, v in default_settings.items():
                if k not in data["settings"]:
                    data["settings"][k] = v
                    needs_write_back = True

    # Sempre tentar escrever de volta para garantir persistência
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        # Se não puder escrever, continua com os dados em memória
        pass

    return data


def _write_config(data):
    path = _config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def list_profiles():
    """Lista os nomes de todos os perfis guardados."""
    return list(_read_config()["profiles"].keys())


def get_active_profile() -> str:
    """Nome do perfil de fornecedor atualmente selecionado."""
    return _read_config()["active_profile"]


def set_active_profile(name: str) -> bool:
    """Seleciona o perfil ativo. Cria o perfil se ainda não existir."""
    data = _read_config()
    if name not in data["profiles"]:
        data["profiles"][name] = {}
    data["active_profile"] = name
    return _write_config(data)


def get_profile_mapping(name: str = None) -> dict:
    """
    Devolve o mapeamento de um perfil.

    Se `name` for None, usa o perfil ativo. Se o perfil não existir,
    devolve uma cópia vazia (comportamento padrão).
    """
    if name is None:
        name = get_active_profile()
    profiles = _read_config()["profiles"]
    mapping = profiles.get(name)
    if mapping is None:
        return DEFAULT_FIELD_MAPPING.copy()
    return dict(mapping)


def save_profile(name: str, mapping: dict) -> bool:
    """Guarda (ou cria) um perfil com o mapeamento dado."""
    data = _read_config()
    data["profiles"][name] = dict(mapping)
    data["active_profile"] = name
    return _write_config(data)


def delete_profile(name: str) -> bool:
    """Apaga um perfil. Não permite apagar o último."""
    data = _read_config()
    profiles = data["profiles"]
    if name not in profiles:
        return False
    if len(profiles) <= 1:
        return False
    del profiles[name]
    if data["active_profile"] == name:
        data["active_profile"] = next(iter(profiles))
    return _write_config(data)


def get_profit_margin() -> float:
    """Retorna a margem de lucro configurada pelo usuário.

    Returns:
        float: Margem de lucro (padrão: 1.40 para 40%)
    """
    try:
        return float(_read_config()["settings"].get("profit_margin", _DEFAULT_PROFIT_MARGIN))
    except Exception:
        return _DEFAULT_PROFIT_MARGIN


def set_profit_margin(margin: float) -> bool:
    """Define a margem de lucro a ser utilizada nas conversões.

    Args:
        margin: Margem de lucro (ex: 1.40 para 40%)

    Returns:
        bool: True se salvo com sucesso
    """
    try:
        data = _read_config()
        m = float(margin)
        data["settings"]["profit_margin"] = m
        # Update percentage as well
        try:
            data["settings"]["profit_percentage"] = round((m - 1.0) * 100.0, 2)
        except Exception:
            pass
        return _write_config(data)
    except Exception:
        return False


def get_price_settings(profile_name=None):
    """Retorna todas as configurações de preço por perfil."""
    try:
        data = _read_config()
        if profile_name is None:
            profile_name = get_active_profile()
        profiles = data.get("profiles", {})
        profile = profiles.get(profile_name, {})
        settings = profile.get("price_settings", {})
        if not settings:
            # Fallback para settings globais para compatibilidade
            settings = data.get("settings", {})
        return {
            "profit_margin": float(settings.get("profit_margin", _DEFAULT_PROFIT_MARGIN)),
            "profit_percentage": float(settings.get("profit_percentage", 40.0)),
            "iva_percentage": float(settings.get("iva_percentage", 0.0)),
            "shipping_cost": float(settings.get("shipping_cost", 0.0)),
            "price_formula": settings.get("price_formula", "margin"),
        }
    except Exception:
        return {
            "profit_margin": _DEFAULT_PROFIT_MARGIN,
            "profit_percentage": 40.0,
            "iva_percentage": 0.0,
            "shipping_cost": 0.0,
            "price_formula": "margin",
        }


def set_price_settings(profit_percentage=None, iva_percentage=None, shipping_cost=None, price_formula=None, profile_name=None):
    """Define configurações de preço por perfil."""
    try:
        data = _read_config()
        if profile_name is None:
            profile_name = get_active_profile()
        profiles = data.setdefault("profiles", {})
        profile = profiles.setdefault(profile_name, {})
        price_settings = profile.setdefault("price_settings", {})
        if profit_percentage is not None:
            pp = float(profit_percentage)
            price_settings["profit_percentage"] = pp
            price_settings["profit_margin"] = 1.0 + (pp / 100.0)
        if iva_percentage is not None:
            price_settings["iva_percentage"] = float(iva_percentage)
        if shipping_cost is not None:
            price_settings["shipping_cost"] = float(shipping_cost)
        if price_formula is not None:
            price_settings["price_formula"] = str(price_formula)
        profiles[profile_name] = profile
        data["profiles"] = profiles
        return _write_config(data)
    except Exception:
        return False


def set_keyword_mapping_settings(enabled=None, parent_category=None, keywords=None):
    """Define configurações de mapeamento por palavras-chave."""
    try:
        data = _read_config()
        settings = data.setdefault("settings", {})
        kw = settings.setdefault("keyword_mapping", {})
        if enabled is not None:
            kw["enabled"] = bool(enabled)
        if parent_category is not None:
            kw["parent_category"] = str(parent_category)
        if keywords is not None:
            kw["keywords"] = str(keywords)
        return _write_config(data)
    except Exception:
        return False


def get_keyword_mapping_settings():
    """Retorna configurações de mapeamento por palavras-chave."""
    try:
        data = _read_config()
        settings = data.get("settings", {})
        kw = settings.get("keyword_mapping", {})
        return {
            "parent_category": kw.get("parent_category", ""),
            "keywords": kw.get("keywords", ""),
            "enabled": kw.get("enabled", False),
        }
    except Exception:
        return {
            "parent_category": "",
            "keywords": "",
            "enabled": False,
        }


def set_keyword_mapping_settings(parent_category=None, keywords=None, enabled=None):
    """Define configurações de mapeamento por palavras-chave."""
    try:
        data = _read_config()
        settings = data.setdefault("settings", {})
        kw = settings.setdefault("keyword_mapping", {})
        if parent_category is not None:
            kw["parent_category"] = str(parent_category)
        if keywords is not None:
            kw["keywords"] = str(keywords)
        if enabled is not None:
            kw["enabled"] = bool(enabled)
        return _write_config(data)
    except Exception:
        return False


def load_field_mapping():
    """
    Load field mapping from the active profile, or return default.

    Returns:
        dict: Mapping of expected field names to source column names
    """
    return get_profile_mapping(get_active_profile())


def get_category_settings() -> dict:
    """Retorna as configurações de mapeamento de categorias (nova categoria pai, aplicar a todos, prefixo, usar hierarquia)."""
    try:
        data = _read_config()
        return data.get("settings", {}).get("category_mapping", {})
    except Exception:
        return {}


def set_category_settings(new_categories=None, cat_keywords=None, apply_to_all=None, selected_prefix=None, use_parent=None):
    """Define configurações de categorias."""
    try:
        data = _read_config()
        settings = data.setdefault("settings", {})
        cats = settings.setdefault("category_mapping", {})
        if new_categories is not None:
            cats["new_categories"] = list(new_categories)[:10]
        if cat_keywords is not None:
            cats["cat_keywords"] = list(cat_keywords)[:10]
        if apply_to_all is not None:
            cats["apply_to_all"] = bool(apply_to_all)
        if selected_prefix is not None:
            cats["selected_prefix"] = str(selected_prefix)
        if use_parent is not None:
            cats["use_parent"] = bool(use_parent)
        return _write_config(data)
    except Exception:
        return False


def get_keyword_mapping_settings():
    """Retorna configurações de mapeamento por palavras-chave (legado - uma regra única)."""
    try:
        data = _read_config()
        settings = data.get("settings", {})
        kw = settings.get("keyword_mapping", {})
        return {
            "enabled": kw.get("enabled", False),
            "parent_category": kw.get("parent_category", ""),
            "keywords": kw.get("keywords", ""),
        }
    except Exception:
        return {
            "enabled": False,
            "parent_category": "",
            "keywords": "",
        }


def set_keyword_mapping_settings(enabled=None, parent_category=None, keywords=None):
    """Define configurações de mapeamento por palavras-chave (legado - uma regra única)."""
    try:
        data = _read_config()
        settings = data.setdefault("settings", {})
        kw = settings.setdefault("keyword_mapping", {})
        if enabled is not None:
            kw["enabled"] = bool(enabled)
        if parent_category is not None:
            kw["parent_category"] = str(parent_category)
        if keywords is not None:
            kw["keywords"] = str(keywords)
        return _write_config(data)
    except Exception:
        return False


def get_keyword_rules() -> list:
    """
    Retorna a lista de regras de mapeamento por palavras-chave com prioridade.

    Cada regra: {"keywords": [str, ...], "parent_category": str, "priority": int}
    Ordenadas por prioridade decrescente (maior prioridade primeiro).
    """
    try:
        data = _read_config()
        rules = data.get("settings", {}).get("keyword_rules", [])
        if not isinstance(rules, list):
            rules = []
        return sorted(rules, key=lambda r: int(r.get("priority", 0)), reverse=True)
    except Exception:
        return []


def set_keyword_rules(rules: list) -> bool:
    """Guarda a lista completa de regras de palavras-chave."""
    try:
        data = _read_config()
        settings = data.setdefault("settings", {})
        settings["keyword_rules"] = list(rules)
        return _write_config(data)
    except Exception:
        return False


def add_keyword_rule(keywords, parent_category: str, priority: int = 10) -> bool:
    """Adiciona uma regra de mapeamento por palavras-chave."""
    try:
        kw_list = [str(k).strip() for k in keywords if str(k).strip()]
        if not kw_list or not parent_category or not str(parent_category).strip():
            return False
        rules = get_keyword_rules()
        rules.append({
            "keywords": kw_list,
            "parent_category": str(parent_category).strip(),
            "priority": int(priority),
        })
        return set_keyword_rules(rules)
    except Exception:
        return False


def remove_keyword_rule(index: int) -> bool:
    """Remove a regra de palavras-chave na posição dada (na lista ordenada por prioridade)."""
    try:
        rules = get_keyword_rules()
        if 0 <= index < len(rules):
            del rules[index]
            return set_keyword_rules(rules)
        return False
    except Exception:
        return False


def apply_keyword_rules(category_path: str, product_name: str = "") -> str:
    """
    Aplica as regras de palavras-chave sobre uma categoria (ou caminho de categoria).

    Percorre as regras ordenadas por prioridade decrescente. Se alguma palavra-chave
    da regra estiver presente no nome do produto ou na categoria, devolve a
    categoria pai da regra (primeira regra vencedora por prioridade).

    Args:
        category_path: Caminho da categoria já construído (ex: "Eletronica/Som").
        product_name: Nome do produto para fazer match das palavras-chave.

    Returns:
        str: Nome da categoria pai da regra vencedora, ou string vazia se nenhuma regra casar.
    """
    text = f"{product_name} {category_path}".lower()
    for rule in get_keyword_rules():
        parent = str(rule.get("parent_category", "")).strip()
        if not parent:
            continue
        for kw in rule.get("keywords", []):
            kn = str(kw).strip().lower()
            if kn and kn in text:
                return parent
    return ""


def get_mapped_value(row: dict, expected_field: str, mapping: dict = None) -> str:
    """
    Get a value from a CSV row using field mapping.

    Args:
        row: Dictionary with CSV column names as keys
        expected_field: The expected field name (used in conversion logic)
        mapping: Optional mapping dictionary (uses default if None)

    Returns:
        str: The value from the row, or empty string if not found
    """
    if mapping is None:
        mapping = load_field_mapping()

    # Get the actual source field name from mapping.
    # If the field is not in the mapping, use the expected field name directly.
    source_field = mapping.get(expected_field, expected_field)

    # If mapping explicitly sets the field to empty string, skip it (optional/not used)
    if source_field == "":
        return ""

    # Get value from row, default to empty string
    return row.get(source_field, "").strip()


def save_field_mapping(mapping: dict):
    """
    Save field mapping to the active profile.

    Args:
        mapping: Mapping dictionary to save
    """
    save_profile(get_active_profile(), mapping)