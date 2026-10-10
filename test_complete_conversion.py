#!/usr/bin/env python3
"""
Complete test to verify the field mapping works with produtos.csv.
This test creates a sample output file and validates the conversion.
"""

import csv
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from csv_converter_gui import process_csv

def test_complete_conversion():
    """Test complete conversion of produtos.csv with field mapping."""
    
    produtos_path = Path("cvs_examples/produtos.csv")
    if not produtos_path.exists():
        print(f"ERROR: {produtos_path} not found")
        return False
    
    print(f"Testing complete conversion of {produtos_path}...")
    print(f"File size: {produtos_path.stat().st_size} bytes")
    
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Run conversion
            n_rows, output_path = process_csv(str(produtos_path), tmpdir)
            print(f"\n[OK] Conversion successful!")
            print(f"  Rows converted: {n_rows}")
            print(f"  Output file: {output_path}")
            
            # Validate output
            output_file = Path(output_path)
            if not output_file.exists():
                print(f"ERROR: Output file not found")
                return False
            
            print(f"  Output size: {output_file.stat().st_size} bytes")
            
            # Read and validate output
            with open(output_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=";")
                headers = reader.fieldnames
                
                # Check required headers
                required = ["Name", "SKU", "Brand", "Price", "Stock", "Categories"]
                missing = [h for h in required if h not in headers]
                if missing:
                    print(f"ERROR: Missing required headers: {missing}")
                    return False
                
                print(f"  All required headers present: {required}")
                
                # Read first 3 rows
                rows = []
                for i, row in enumerate(reader):
                    rows.append(row)
                    if i >= 2:
                        break
                
                print(f"\nFirst {len(rows)} converted rows:")
                for idx, row in enumerate(rows, 1):
                    print(f"\n  Row {idx}:")
                    print(f"    Name: {row.get('Name', '')[:80]}")
                    print(f"    SKU: {row.get('SKU', '')}")
                    print(f"    Brand: {row.get('Brand', '')}")
                    print(f"    Price: {row.get('Price', '')}")
                    print(f"    Stock: {row.get('Stock', '')}")
                    print(f"    Categories: {row.get('Categories', '')[:80]}")
                
                # Check that data was properly mapped
                first_row = rows[0]
                if not first_row.get("Name"):
                    print("ERROR: Name field is empty - mapping might be broken")
                    return False
                if not first_row.get("SKU"):
                    print("ERROR: SKU field is empty - mapping might be broken")
                    return False
                
                print("\n[OK] All validations passed!")
                return True
                
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_complete_conversion()
    print("\n" + "="*60)
    if success:
        print("TEST PASSED: Field mapping works correctly with produtos.csv")
    else:
        print("TEST FAILED: There were errors with the field mapping")
    print("="*60)
    sys.exit(0 if success else 1)