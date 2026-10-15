# Profit Margin Configuration Implementation

## Summary of Changes

I have successfully implemented user-configurable profit margin for the Conversor Jumpseller application. The profit margin is no longer hardcoded at 1.40 (40%) but can be configured by the user.

## Files Modified

### 1. `csv_converter_gui.py`
- **Line 48**: Added `get_profit_margin` to the imports from `field_mapping`
- **Line 128**: Changed `price = preco * 1.40` to `price = preco * get_profit_margin()`

### 2. `field_mapping.py`
- **Line 51**: Added `_DEFAULT_PROFIT_MARGIN = 1.40` constant
- **Lines 63-84**: Enhanced `_read_config()` to:
  - Initialize a `"settings"` section with default profit margin when config file doesn't exist
  - Handle backward compatibility with old config format
  - Ensure `settings` and `profit_margin` keys always exist
  - Automatically write back corrected config when reading an existing file that's missing settings
- **Lines 167-182**: Added two new functions:
  - `get_profit_margin() -> float`: Returns current profit margin from settings
  - `set_profit_margin(margin: float) -> bool`: Saves new profit margin to settings

### 3. `field_mapping_config.json` (updated automatically)
- Added `"settings": {"profit_margin": 1.4}` section to store the profit margin setting
- This file is updated automatically when `set_profit_margin()` is called

## How It Works

### Default Behavior
- By default, the profit margin is set to 1.40 (40%)
- This maintains backward compatibility with existing configurations

### Changing the Margin
Users can change the profit margin in two ways:

#### 1. Programmatic Access (for developers/advanced users)
```python
from field_mapping import get_profit_margin, set_profit_margin

# Get current margin
current_margin = get_profit_margin()  # Returns 1.4 by default

# Set new margin (e.g., 60% margin)
set_profit_margin(1.6)
```

#### 2. Manual Configuration File Edit
Users can manually edit `field_mapping_config.json`:
1. Locate the file in the application directory
2. Find the `"settings"` section
3. Change the `"profit_margin"` value (e.g., to `1.6` for 60% margin)
4. Save the file

### Price Calculation Formula
The price is now calculated as:
**Preço de venda = Preço de origem × Margem de lucro**

Where:
- **Preço de origem**: The source price from the CSV (after parsing)
- **Margem de lucro**: Configurable value (default: 1.40 for 40% margin)

## Example Calculations

With default margin (1.40):
- Source price 14.56 → Sale price 20.38 (14.56 × 1.40)
- Source price 15.40 → Sale price 21.56 (15.40 × 1.40)
- Source price 17.65 → Sale price 24.71 (17.65 × 1.40)

With custom margin (1.60 for 60%):
- Source price 14.56 → Sale price 23.30 (14.56 × 1.60)
- Source price 15.40 → Sale price 24.64 (15.40 × 1.60)
- Source price 17.65 → Sale price 28.24 (17.65 × 1.60)

## Verification
The implementation has been tested to ensure:
- Backward compatibility (existing configs still work)
- Correct price calculations with both default and custom margins
- Proper handling of edge cases (None, empty strings, invalid values)
- Persistence of settings across application restarts
- Thread-safe access to configuration settings

The profit margin is now fully user-configurable as requested.