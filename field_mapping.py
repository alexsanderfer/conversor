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


def _config_path():
    return Path(__file__).parent / "field_mapping_config.json"


def _read_config():
    """Lê o ficheiro de configuração e devolve a estrutura completa."""
    path = _config_path()
    if not path.is_file():
        return {"active_profile": _PROFILE_DEFAULT, "profiles": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"active_profile": _PROFILE_DEFAULT, "profiles": {}}

    # Compatibilidade: formato antigo era um dict plano de mapeamento.
    if isinstance(data, dict) and "profiles" not in data:
        return {
            "active_profile": _PROFILE_DEFAULT,
            "profiles": {_PROFILE_DEFAULT: data},
        }

    if not isinstance(data, dict):
        return {"active_profile": _PROFILE_DEFAULT, "profiles": {}}
    data.setdefault("active_profile", _PROFILE_DEFAULT)
    data.setdefault("profiles", {})
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


def load_field_mapping():
    """
    Load field mapping from the active profile, or return default.

    Returns:
        dict: Mapping of expected field names to source column names
    """
    return get_profile_mapping(get_active_profile())


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