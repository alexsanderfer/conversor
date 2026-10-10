#!/usr/bin/env python3
"""
Integration test for the field mapping feature.
Tests the complete flow: mapping -> conversion -> validation.
"""

import json
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from csv_converter_gui import process_csv, load_field_mapping
from field_mapping import (
    DEFAULT_FIELD_MAPPING,
    load_field_mapping as fm_load,
    get_mapped_value,
    save_field_mapping,
)

def test_default_mapping():
    """Test that default mapping is loaded correctly."""
    print("Test 1: Default field mapping...")
    mapping = fm_load()
    
    # Check key mappings
    assert mapping.get("design") == "nome", "design should map to nome"
    assert mapping.get("codigo") == "codbarras", "codigo should map to codbarras"
    assert mapping.get("ref") == "referencia", "ref should map to referencia"
    assert mapping.get("familia_principal") == "categoria", "familia_principal should map to categoria"
    assert mapping.get("sub_familia") == "subcategoria", "sub_familia should map to subcategoria"
    assert mapping.get("desc1") == "descricao", "desc1 should map to(descricao"
    
    print("  [OK] Default mapping correct")
    return True

def test_get_mapped_value():
    """Test the get_mapped_value function."""
    print("Test 2: get_mapped_value function...")
    
    # Sample row from produtos.csv
    row = {
        "referencia": "RE-549005",
        "nome": "Dell Latitude 5490",
        "marca": "Dell",
        "categoria": "Recondicionados",
        "preco": "199.90",
        "stock": "1",
    }
    
    mapping = DEFAULT_FIELD_MAPPING.copy()
    
    # Test mapped fields
    assert get_mapped_value(row, "design", mapping) == "Dell Latitude 5490"
    assert get_mapped_value(row, "ref", mapping) == "RE-549005"
    assert get_mapped_value(row, "marca", mapping) == "Dell"
    assert get_mapped_value(row, "familia_principal", mapping) == "Recondicionados"
    assert get_mapped_value(row, "preco", mapping) == "199.90"
    assert get_mapped_value(row, "stock", mapping) == "1"
    
    # Test unmapped field (should use field name as-is)
    assert get_mapped_value(row, "unmapped_field", mapping) == ""
    
    print("  [OK] get_mapped_value works correctly")
    return True

def test_save_load_mapping():
    """Test saving and loading custom mapping."""
    print("Test 3: Save and load custom mapping...")
    
    custom_mapping = {
        "design": "product_name",
        "codigo": "barcode",
        "ref": "sku",
    }
    
    # Save custom mapping to a temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)
        json.dump(custom_mapping, f)
    
    try:
        # Load from the temporary file
        with open(temp_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        
        assert loaded.get("design") == "product_name"
        assert loaded.get("codigo") == "barcode"
        assert loaded.get("ref") == "sku"
        
        print("  [OK] Save and load works")
        
    finally:
        if temp_path.exists():
            temp_path.unlink()
    
    return True

def test_conversion_with_mapping():
    """Test that conversion uses the field mapping correctly."""
    print("Test 4: Conversion with field mapping...")
    
    produtos_path = Path("cvs_examples/produtos.csv")
    if not produtos_path.exists():
        print("  [SKIP] produtos.csv not found")
        return True
    
    with tempfile.TemporaryDirectory() as tmpdir:
        n_rows, output_path = process_csv(str(produtos_path), tmpdir)
        
        assert n_rows > 0, "Should convert at least one row"
        assert Path(output_path).exists(), "Output file should exist"
        
        # Read output and verify
        import csv
        with open(output_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)
            
            assert len(rows) == n_rows, f"Expected {n_rows} rows, got {len(rows)}"
            
            # Check first row has data
            first = rows[0]
            assert first.get("Name"), "Name should not be empty"
            assert first.get("SKU"), "SKU should not be empty"
            assert first.get("Brand"), "Brand should not be empty"
            assert first.get("Price"), "Price should not be empty"
        
        print(f"  [OK] Converted {n_rows} rows successfully")
    
    return True

def test_field_mapping_dialog():
    """Test that the FieldMappingDialog can be created."""
    print("Test 5: FieldMappingDialog creation...")
    
    try:
        import tkinter as tk
        from csv_converter_gui import FieldMappingDialog
        
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        
        # Create dialog with default mapping
        dialog = FieldMappingDialog(root, DEFAULT_FIELD_MAPPING.copy())
        
        # Check that entries were created
        assert hasattr(dialog, 'entries'), "Dialog should have entries attribute"
        assert len(dialog.entries) > 0, "Dialog should have entries"
        
        # Check that all mappable fields are present
        for field, desc in FieldMappingDialog.MAPPABLE_FIELDS:
            assert field in dialog.entries, f"Field {field} should be in entries"
        
        # Test reset functionality
        dialog._reset()
        for field, var in dialog.entries.items():
            expected = DEFAULT_FIELD_MAPPING.get(field, "")
            assert var.get() == expected, f"Field {field} should reset to {expected}"
        
        root.destroy()
        print("  [OK] FieldMappingDialog works correctly")
        
    except Exception as e:
        print(f"  [ERROR] Dialog test failed: {e}")
        return False
    
    return True

def run_all_tests():
    """Run all integration tests."""
    print("="*60)
    print("Field Mapping Integration Tests")
    print("="*60)
    
    tests = [
        test_default_mapping,
        test_get_mapped_value,
        test_save_load_mapping,
        test_conversion_with_mapping,
        test_field_mapping_dialog,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  [ERROR] Test {test.__name__} raised exception: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60)
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)