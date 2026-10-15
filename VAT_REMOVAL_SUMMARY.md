VAT (23%) Removal Summary
========================

Changes Made:

1. Modified csv_converter_gui.py line 128:
   - BEFORE: price = preco * 1.40 * 1.23
   - AFTER:  price = preco * 1.40
   - This removes the 23% VAT calculation from the price conversion

2. Updated README.md line 20:
   - BEFORE: - **Preço** = preço de origem × 1,40 (margem) × 1,23 (IVA)
   - AFTER:  - **Preço** = preço de origem × 1,40 (margem)
   - This updates the documentation to reflect the new calculation

Verification:
- Created and ran tests to confirm the calculation now correctly computes price as preco * 1.40
- Verified that edge cases (None, empty strings, invalid values) still work correctly
- Confirmed that the numerical results are accurate:
  * Input 14.56 → Output 20.38 (was 25.07 with VAT)
  * Input 15.40 → Output 21.56 (was 26.52 with VAT)
  * Input 17.65 → Output 24.71 (was 30.39 with VAT)
  * Input 10.71 → Output 14.99 (was 18.44 with VAT)

The change successfully removes the VAT (23%) from the price calculation as requested, leaving only the 40% margin/markup.