"""
Field mapping configuration for CSV converter.

This module provides a flexible field mapping system that allows users
to map their CSV column names to the expected Jumpseller format.

The mapping is a dictionary where:
- Key: expected field name (used in conversion logic)
- Value: actual column name in the source CSV

Users can customize this mapping to support different CSV formats.
"""

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


def load_field_mapping():
    """
    Load field mapping from configuration file or return default.
    
    Returns:
        dict: Mapping of expected field names to source column names
    """
    import json
    import os
    from pathlib import Path
    
    config_path = Path(__file__).parent / "field_mapping_config.json"
    
    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    
    return DEFAULT_FIELD_MAPPING.copy()


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
    Save field mapping to configuration file.
    
    Args:
        mapping: Mapping dictionary to save
    """
    import json
    from pathlib import Path
    
    config_path = Path(__file__).parent / "field_mapping_config.json"
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False