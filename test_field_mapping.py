#!/usr/bin/env python3
"""
Test script to verify field mapping works correctly with multiple CSV formats.
"""

import csv
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from csv_converter_gui import process_csv, load_field_mapping, get_mapped_value
from field_mapping import DEFAULT_FIELD_MAPPING

def test_csv_file(csv_path: str, expected_fields: dict = None):
    """Test conversion of a CSV file."""
    path = Path(csv_path)
    if not path.exists():
        print(f"ERROR: {path} not found")
        return False
    
    print(f"\n{'='*60}")
    print(f"Testing: {path.name}")
    print(f"{'='*60}")
    
    # Load the mapping
    mapping = load_field_mapping()
    print("Field mapping loaded:")
    if mapping:
        for key, value in mapping.items():
            if value:
                print(f"  {key} -> {value}")
    else:
        print("  (empty - using expected column names directly)")
    print()
    
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        headers = reader.fieldnames
        print(f"CSV headers: {headers}")
        
        first_row = next(reader)
        print("First row sample:")
        for k, v in list(first_row.items())[:5]:
            print(f"  {k}: {str(v)[:60] if v else ''}")
        print()
        
        # Test mapping
        print("Testing field mapping:")
        test_fields = ["design", "codigo", "ref", "familia_principal", 
                       "sub_familia", "marca", "imagem", "stock", "preco"]
        for field in test_fields:
            value = get_mapped_value(first_row, field, mapping)
            print(f"  {field}: '{str(value)[:50] if value else ''}'")
        print()
    
    # Test full conversion
    print("Testing full conversion...")
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            n_rows, output_path = process_csv(str(path), tmpdir)
            print(f"Converted {n_rows} rows")
            
            with open(output_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=";")
                first_out = next(reader)
                print("First converted row (key fields):")
                key_fields = ["Name", "SKU", "Barcode", "Brand", "Categories", "Price", "Stock"]
                for field in key_fields:
                    value = first_out.get(field, "")
                    print(f"  {field}: '{str(value)[:80] if value else ''}'")
            
            return True
    except Exception as e:
        print(f"ERROR during conversion: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = True
    
    # Test CSV with expected column names (should work with empty mapping)
    test_csv = Path("cvs_examples/test_csv.csv")
    if test_csv.exists():
        success = test_csv_file(str(test_csv)) and success
    
    # Test CSV that needs mapping (produtos.csv)
    produtos_path = Path("cvs_examples/produtos.csv")
    if produtos_path.exists():
        print("\nNOTE: produtos.csv requires field mapping configuration.")
        print("Run the GUI and use 'Mapear Campos...' to configure it.")
    
    sys.exit(0 if success else 1)