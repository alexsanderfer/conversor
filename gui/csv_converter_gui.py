"""
Conversor de CSV para formato de importacao Jumpseller (com licenca).

Como usar:
    python csv_converter_gui.py

Uma janela abre; arraste um CSV ou clique em "Escolher arquivo",
escolha a pasta de destino e clique em "Converter".
Na primeira execucao (ou sem licenca valida) aparece o dialogo de licenca.
"""

import csv
import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
import unicodedata
import webbrowser
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from tkinterdnd2 import DND_FILES, Tk

from core.i18n import translate, DEFAULT_LANGUAGE
from core.license_dialog import LicenseDialog
from core.license_manager import check_license, load_license_state, check_license_expiry_warning
from core.stripe_integration import open_stripe_checkout
from core.updater import check_for_updates, get_current_version
from gui.theme import (
    BG_WINDOW,
    ERROR_BG,
    ERROR_FG,
    FOOTER_TEXT,
    GRAY_100,
    GRAY_600,
    GRAY_800,
    BLUE_100,
    BLUE_500,
    BLUE_700,
    WHITE,
    apply_theme,
    style_drop_area,
)
from core.field_mapping import (
    load_field_mapping, get_mapped_value, save_field_mapping, DEFAULT_FIELD_MAPPING,
    list_profiles, get_active_profile, set_active_profile,
    get_profile_mapping, save_profile, delete_profile, _PROFILE_DEFAULT,
    get_profit_margin, get_price_settings, set_price_settings,
    get_category_settings, set_category_settings,
    add_keyword_rule, remove_keyword_rule, apply_keyword_rules, get_keyword_rules,
    get_compiled_keyword_rules, apply_compiled_keyword_rules,
    get_sku_prefix, set_sku_prefix,
    get_highlights_brands_settings, set_highlights_brands_settings,
    get_highlights_brands_keyword_rules, add_highlights_brands_keyword_rule, remove_highlights_brands_keyword_rule,
    get_compiled_highlights_brands_rules, apply_compiled_highlights_brands_rules,
    get_brands_keyword_rules, add_brands_keyword_rule, remove_brands_keyword_rule,
    get_compiled_brands_rules, apply_compiled_brands_rules,
    get_last_input_file, set_last_input_file,
    get_auto_check_updates, set_auto_check_updates,
    get_start_maximized, set_start_maximized,
    get_language, set_language,
    get_window_geometry, set_window_geometry,
    get_massive_category_rules, set_massive_category_rules,
    add_massive_category_rule, save_massive_category_rule, remove_massive_category_rule,
    apply_massive_category_rules,
)
from core.category_classifier import classify_product, load_rules, save_rules, learn_from_product, learn_from_file_rows
from core.i18n import translate, TRANSLATABLE_STRINGS

# Cache for category settings
_category_settings_cache = None
_category_settings_cache_time = 0.0

# ---------------------------------------------------------------------------
# CONFIGURACAO: colunas de destino na ordem exata do Jumpseller
# ---------------------------------------------------------------------------
DEST_COLUMNS = [
    "Permalink", "Name", "Description", "Meta Title", "Meta Description",
    "Width", "Length", "Height", "Brand", "Barcode", "Categories", "Images",
    "Digital", "Featured", "Status", "SKU", "Weight", "Cost per item",
    "Compare at price", "Stock", "Stock Unlimited", "Stock Notification",
    "Stock Threshold", "Price", "Variant Image", "Variant 1 Option Name",
    "Variant 1 Option Type", "Variant 1 Option Value", "Variant 1 Option Custom",
    "Google Product Category",
]

LICENSE_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "ConversorJumpseller" / "licenses"


def _assets_dir() -> Path:
    """Resolve a pasta de assets tanto em modo dev quanto no exe congelado.

    No exe (PyInstaller) os dados empacotados via ``datas`` ficam sob
    ``sys._MEIPASS/assets``; em desenvolvimento ficam na raiz do projeto
    (sibling do pacote ``gui/``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


ASSETS = _assets_dir()

# ---------------------------------------------------------------------------
# LOGICA DE CONVERSAO (mesma do CLI, intacta)
# ---------------------------------------------------------------------------

def parse_dimensions(raw: str):
    if not raw or not raw.strip():
        return ("0", "0", "0")
    raw = raw.strip().lower()
    raw = raw.replace(" ", "").replace("x", "×").replace("*", "×")
    parts = [p.strip() for p in raw.split("×") if p.strip()]
    if len(parts) == 1:
        w = _to_num(parts[0])
        return (str(w), "0", "0")
    elif len(parts) == 2:
        w = _to_num(parts[0])
        l = _to_num(parts[1])
        return (str(w), str(l), "0")
    elif len(parts) >= 3:
        w = _to_num(parts[0])
        l = _to_num(parts[1])
        h = _to_num(parts[2])
        return (str(w), str(l), str(h))
    return ("0", "0", "0")


def _to_num(raw: str):
    if not raw:
        return 0
    try:
        val = float(raw)
        if val == int(val):
            return int(val)
        return val
    except ValueError:
        return 0


_CURRENCY_RE = re.compile(r"(?:r\s*\$|€|eur|usd|\$)", re.IGNORECASE)


def _parse_pt_number(raw: str):
    if not raw:
        return None
    cleaned = _CURRENCY_RE.sub("", raw)
    cleaned = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        return None
    try:
        if "," in cleaned:
            preco = float(cleaned.replace(".", "").replace(",", "."))
        else:
            preco = float(cleaned)
    except ValueError:
        return None
    return preco


def _calc_price(raw_preco: str) -> str:
    preco = _parse_pt_number(raw_preco)
    if preco is None:
        return ""
    try:
        from core.field_mapping import get_active_profile
        settings = get_price_settings(get_active_profile())
        profit_pct = float(settings.get("profit_percentage", 40.0))
        iva_pct = float(settings.get("iva_percentage", 0.0))
        shipping = float(settings.get("shipping_cost", 0.0))

        # Fórmula detalhada ajustada: ((Custo * (1 + lucro%)) * (1 + iva%)) + portes
        price = preco * (1.0 + profit_pct / 100.0)
        if iva_pct and iva_pct > 0:
            price = price * (1.0 + iva_pct / 100.0)
        if shipping and shipping > 0:
            price += shipping
        return str(round(price, 2))
    except Exception:
        try:
            settings = get_price_settings(get_active_profile())
            profit_margin = float(settings.get("profit_margin", 1.40))
            price = preco * profit_margin
            return str(round(price, 2))
        except Exception:
            return str(round(preco, 2))


def parse_stock(raw: str):
    if not raw or not raw.strip():
        return 0
    raw = raw.strip()
    if raw.startswith(">"):
        try:
            return int(raw[1:].strip())
        except ValueError:
            return 0
    elif raw.startswith("<"):
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def slugify(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    slug = ""
    for ch in text:
        if ch.isalnum():
            slug += ch
        elif ch == " ":
            slug += "-"
        else:
            slug += "-"
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


_BULLET_RE = re.compile(r'^\s*(?:[-–—•*·]+|\d+[.)])\s*')


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = text.replace("#", "").strip()
    text = _BULLET_RE.sub("", text)
    text = text.strip()
    if not text:
        return ""
    text = re.sub(r'^=\s*', '', text)
    text = re.sub(r'^\s*\(=-\s*', '', text)
    text = _BULLET_RE.sub("", text)
    text = text.strip()
    text = text.replace("(", "").replace(")", "").strip()
    text = _BULLET_RE.sub("", text)
    return text.strip()


def build_description(row: dict, mapping: dict = None) -> str:
    """
    Build product description from description fields using field mapping.
    
    Args:
        row: Dictionary with CSV column names as keys
        mapping: Optional field mapping dictionary
    
    Returns:
        str: Combined description text
    """
    if mapping is None:
        mapping = load_field_mapping()
    
    parts = []
    for i in range(1, 7):
        val = get_mapped_value(row, f"desc{i}", mapping)
        for linha in re.split(r"[\r\n]+", val):
            cleaned = clean_text(linha)
            if cleaned:
                parts.append(cleaned)
    return ". ".join(parts)


def build_categories(row: dict, mapping: dict = None, compiled_rules=None) -> str:
    """
    Build category hierarchy using field mapping.

    Args:
        row: Dictionary with CSV column names as keys
        mapping: Optional field mapping dictionary

    Returns:
        str: Comma-separated category paths
    """
    if mapping is None:
        mapping = load_field_mapping()

    familia = get_mapped_value(row, "familia_principal", mapping)
    sub_familia = get_mapped_value(row, "sub_familia", mapping)
    sub_sub_familia = get_mapped_value(row, "sub_sub_familia", mapping)

    # Classificação automática se categoria estiver vazia
    if not familia:
        try:
            product_name = get_mapped_value(row, "design", mapping)
            if product_name:
                auto_cat = classify_product(product_name, "")
                if auto_cat:
                    familia = auto_cat
        except Exception:
            pass

    # ---- Mapeamento Massivo (CATEGORIAS M) ----
    # Aplica as regras massivas com base nas categorias originais do fornheiro.
    # Se houver correspondência, a categoria pai definida na regra substitui
    # toda a hierarquia, mantendo as subcategoria originais abaixo dela.
    try:
        massive_parent = apply_massive_category_rules(familia, sub_familia, sub_sub_familia)
        if massive_parent:
            # Constrói a hierarquia sob a nova categoria pai
            result = [massive_parent]
            if familia:
                prefixed = f"{massive_parent}/{familia}"
                if prefixed not in result:
                    result.append(prefixed)
            if sub_familia and familia:
                cat2 = f"{massive_parent}/{familia}/{sub_familia}"
                parts = cat2.split('/')
                if len(parts) > 4:
                    cat2 = '/'.join(parts[:4])
                if cat2 not in result:
                    result.append(cat2)
            if sub_sub_familia and familia and sub_familia:
                cat3 = f"{massive_parent}/{familia}/{sub_familia}/{sub_sub_familia}"
                parts = cat3.split('/')
                if len(parts) > 4:
                    cat3 = '/'.join(parts[:4])
                if cat3 not in result:
                    result.append(cat3)
            return ",".join(result)
    except Exception:
        pass

    categories = []
    if familia:
        categories.append(familia)
    if sub_familia:
        cat2 = f"{familia}/{sub_familia}"
        # Limitar a 4 níveis máximo
        parts = cat2.split('/')
        if len(parts) > 4:
            cat2 = '/'.join(parts[:4])
        categories.append(cat2)
    if sub_sub_familia:
        cat3 = f"{familia}/{sub_familia}/{sub_sub_familia}"
        parts = cat3.split('/')
        if len(parts) > 4:
            cat3 = '/'.join(parts[:4])
        categories.append(cat3)

    # Apply category mapping if configured
    try:
        cat_settings = get_category_settings()
        new_cats = [c.strip() for c in cat_settings.get("new_categories", []) if c.strip()]
        if new_cats and categories:
            parent_cat = new_cats[0]
            use_parent = cat_settings.get("use_parent", True)
            apply_to_all = cat_settings.get("apply_to_all", True)

            if apply_to_all:
                # Jumpseller needs ALL hierarchy levels from root to leaf.
                # When mapping to a parent, output: [parent, parent/cat1, parent/cat1/cat2, ...]
                if use_parent:
                    result = [parent_cat]
                    for cat_path in categories:
                        cp = (cat_path or "").strip().strip("/")
                        if not cp:
                            continue
                        prefixed = f"{parent_cat}/{cp}"
                        if prefixed not in result:
                            result.append(prefixed)
                    return ",".join(result)
                else:
                    return parent_cat

            # apply_to_all == False: only categories matching selected_prefix get the parent mapping
            selected_prefix = cat_settings.get("selected_prefix", "").strip().lower()
            if selected_prefix:
                matched_paths = []
                unmatched_paths = []
                for cat_path in categories:
                    cp = (cat_path or "").strip()
                    cp_low = cp.lower()
                    if cp_low.startswith(selected_prefix) or selected_prefix in cp_low:
                        matched_paths.append(cp)
                    else:
                        unmatched_paths.append(cp)

                if matched_paths:
                    result = []
                    if use_parent:
                        # Expand to full hierarchy from the mapping parent, preserving matched structure
                        result.append(parent_cat)
                        for cat_path in matched_paths:
                            cp = cat_path.strip().strip("/")
                            if not cp:
                                continue
                            prefixed = f"{parent_cat}/{cp}"
                            if prefixed not in result:
                                result.append(prefixed)
                        # Keep unmatched categories as-is (full paths already built)
                        for up in unmatched_paths:
                            upc = (up or "").strip()
                            if upc and upc not in result:
                                result.append(upc)
                    else:
                        result.append(parent_cat)
                        for up in unmatched_paths:
                            upc = (up or "").strip()
                            if upc and upc not in result:
                                result.append(upc)
                    return ",".join(result)
                # No matches: fall through to original categories
    except Exception:
        pass

    # Mapeamento por palavras-chave por categoria (Categoria 1-10 com suas palavras-chave)
    try:
        cat_settings = get_category_settings()
        new_cats = [c.strip() for c in cat_settings.get("new_categories", []) if c.strip()]
        cat_kws = cat_settings.get("cat_keywords", [])
        if new_cats and categories:
            product_name = get_mapped_value(row, "design", mapping)
            for i, parent_cat in enumerate(new_cats):
                kws = cat_kws[i] if i < len(cat_kws) else ""
                if not parent_cat or not kws:
                    continue
                keywords = [k.strip().lower() for k in kws.replace(",", ";").split(";") if k.strip()]
                text = f"{product_name} {','.join(categories)}".lower()
                for kw in keywords:
                    if kw and kw in text:
                        # Jumpseller precisa de toda a hierarquia da raiz até a folha
                        if cat_settings.get("use_parent", True):
                            result = [parent_cat]
                            for cat_path in categories:
                                cp = (cat_path or "").strip().strip("/")
                                if not cp:
                                    continue
                                prefixed = f"{parent_cat}/{cp}"
                                if prefixed not in result:
                                    result.append(prefixed)
                            return ",".join(result)
                        else:
                            return parent_cat
    except Exception:
        pass

    # Mapeamento avançado por Categoria e Subcategoria (prioridade com cache O(1))
    try:
        familia = get_mapped_value(row, "familia_principal", mapping)
        sub_familia = get_mapped_value(row, "sub_familia", mapping)
        if compiled_rules is not None:
            kw_parent = apply_compiled_keyword_rules(familia, sub_familia, compiled_rules)
        else:
            kw_parent = apply_keyword_rules(familia, sub_familia)
        if kw_parent:
            if cat_settings.get("use_parent", True):
                result = [kw_parent]
                for cat_path in categories:
                    cp = (cat_path or "").strip().strip("/")
                    if not cp:
                        continue
                    prefixed = f"{kw_parent}/{cp}"
                    if prefixed not in result:
                        result.append(prefixed)
                return ",".join(result)
            else:
                return kw_parent
    except Exception:
        pass

    return ",".join(categories)


def convert_row(row: dict, mapping: dict = None, compiled_rules=None) -> dict:
    """
    Convert a CSV row to Jumpseller format using field mapping.

    Args:
        row: Dictionary with CSV column names as keys
        mapping: Optional field mapping dictionary (uses default if None)

    Returns:
        dict: Row in Jumpseller format
    """
    if mapping is None:
        mapping = load_field_mapping()

    dest_row = OrderedDict()
    for dest_col in DEST_COLUMNS:
        dest_row[dest_col] = ""

    # Get values using field mapping
    name = get_mapped_value(row, "design", mapping)
    if name.startswith("=") and len(name) > 1:
        name = name[1:].strip()

    dest_row["Permalink"] = ""
    dest_row["Name"] = name
    dest_row["Description"] = build_description(row, mapping)
    dest_row["Meta Title"] = clean_text(name)
    dest_row["Meta Description"] = build_description(row, mapping)
    width, length, height = parse_dimensions(get_mapped_value(row, "dimensoes", mapping))
    dest_row["Width"] = width
    dest_row["Length"] = length
    dest_row["Height"] = height
    dest_row["Brand"] = get_mapped_value(row, "marca", mapping)
    dest_row["Barcode"] = get_mapped_value(row, "codigo", mapping)
    dest_row["Categories"] = build_categories(row, mapping, compiled_rules=compiled_rules)
    dest_row["Images"] = get_mapped_value(row, "imagem", mapping)
    dest_row["Digital"] = "NO"
    dest_row["Featured"] = "NO"
    stock_val = parse_stock(get_mapped_value(row, "stock", mapping))
    dest_row["Status"] = "available" if stock_val > 0 else "not-available"
    sku = get_mapped_value(row, "ref", mapping)
    sku_prefix = get_sku_prefix(get_active_profile())
    if sku_prefix and sku and not sku.startswith(sku_prefix):
        sku = sku_prefix + sku
    dest_row["SKU"] = sku
    dest_row["Weight"] = get_mapped_value(row, "peso", mapping)
    dest_row["Cost per item"] = ""
    dest_row["Compare at price"] = ""
    dest_row["Stock"] = str(stock_val)
    dest_row["Stock Unlimited"] = "NO"
    dest_row["Stock Notification"] = "YES"
    dest_row["Stock Threshold"] = ""
    dest_row["Price"] = _calc_price(get_mapped_value(row, "preco", mapping))
    return dest_row


def get_output_path(input_path: str, output_dir: str = None) -> str:
    if output_dir is None:
        output_dir = str(Path.home() / "Downloads")
    input_name = Path(input_path).stem
    output_name = f"{input_name}_convertido.csv"
    return os.path.join(output_dir, output_name)


def process_csv(input_path: str, output_dir: str = None, exclude_unavailable: bool = False):
    """
    Converte um CSV para o formato Jumpseller.

    Args:
        input_path: Caminho do ficheiro de entrada
        output_dir: Pasta de destino (opcional)
        exclude_unavailable: Se True, ignora produtos com stock <= 0 / Status not-available

    Returns:
        (linhas_escritas, output_path, linhas_removidas_indisponiveis)
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Arquivo nao encontrado: '{input_path}'")
    output_path = get_output_path(input_path, output_dir)
    mapping = load_field_mapping()
    compiled_rules = get_compiled_keyword_rules()
    removed_unavailable = 0
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = []
        for raw_row in reader:
            row = {
                k: (v if v is not None else "")
                for k, v in raw_row.items()
                if k is not None
            }
            if not any(v.strip() for v in row.values()):
                continue
            converted = convert_row(row, mapping, compiled_rules=compiled_rules)
            if exclude_unavailable:
                stock_raw = (converted.get("Stock") or "0").strip()
                try:
                    stock_num = int(float(stock_raw.replace(",", ".")))
                except Exception:
                    stock_num = 0
                status = (converted.get("Status") or "").strip().lower()
                if stock_num <= 0 or status == "not-available":
                    removed_unavailable += 1
                    continue
            rows.append(converted)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=DEST_COLUMNS, delimiter=";", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), output_path, removed_unavailable


# ---------------------------------------------------------------------------
# ATUALIZACAO DA LOJA
# ---------------------------------------------------------------------------
STATE_FILENAME = "_jumpseller_precos.json"


def _normalize_header(text: str) -> str:
    if not text:
        return ""
    # Remove BOM and trim
    text = text.strip().lstrip("﻿")
    # Normalize accents
    try:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
    except Exception:
        pass
    text = text.lower()
    # Replace spaces/punctuation
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _detect_field_mapping_from_headers(headers):
    """Auto-detect field mapping from CSV headers."""
    if not headers:
        return {}

    detected = {}
    # Build normalized lookup of headers
    header_map = {}
    for h in headers:
        if not h:
            continue
        norm = _normalize_header(h)
        if norm:
            header_map[norm] = h.strip()

    # Detection rules: expected_field -> list of possible header patterns
    rules = {
        "design": ["nome", "produto", "design", "titulo", "title", "descricao nome", "nome produto", "produto nome"],
        "ref": ["referencia", "ref", "sku", "codigo sku", "cod ref", "referencia sku", "item code"],
        "codigo": ["codbarras", "codigo barras", "ean", "barcode", "cod barras", "gtin", "upc"],
        "preco": ["preco", "price", "valor", "preco venda", "preco unitario", "pvp"],
        "stock": ["stock", "estoque", "quantidade", "qty", "saldo", "disponivel"],
        "peso": ["peso", "weight", "peso bruto", "peso liquido"],
        "marca": ["marca", "brand", "fabricante"],
        "imagem": ["imagem", "image", "foto", "url imagem", "imagem url", "foto url"],
        "dimensoes": ["dimensoes", "medidas", "dimensao", "dim", "l x a x p", "comprimento largura altura"],
        "familia_principal": ["categoria", "categoria principal", "familia", "familia principal", "grupo", "departamento"],
        "sub_familia": ["subcategoria", "sub categoria", "subfamilia", "sub familia"],
        "sub_sub_familia": ["sub subcategoria", "subsubcategoria", "terceira categoria"],
        "desc1": ["descricao", "descricao1", "descricao curta", "descricao produto", "description", "observacao", "detalhes"],
    }

    for expected, patterns in rules.items():
        # Try exact normalized match first
        for p in patterns:
            pnorm = _normalize_header(p)
            if pnorm in header_map:
                detected[expected] = header_map[pnorm]
                break
        if expected in detected:
            continue
        # Try partial match
        for norm_h, orig_h in header_map.items():
            for p in patterns:
                pnorm = _normalize_header(p)
                if pnorm and pnorm in norm_h:
                    detected[expected] = orig_h
                    break
            if expected in detected:
                break

    return detected


def _read_csv_any_delimiter(input_path: str):
    # Try multiple encodings since store files can be UTF-16
    encodings = ["utf-8-sig", "utf-16", "utf-16le", "utf-16be"]
    texto = None

    for encoding in encodings:
        try:
            with open(input_path, newline="", encoding=encoding) as f:
                texto = f.read()
            break
        except UnicodeDecodeError:
            continue

    if texto is None:
        # Fallback to binary read and try to detect
        with open(input_path, "rb") as f:
            raw = f.read()
        for encoding in encodings:
            try:
                texto = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            # Last resort: replace errors
            texto = raw.decode("utf-8", errors="replace")

    texto = texto.lstrip("﻿")
    candidatos = [";", ","]
    melhor = None
    for delim in candidatos:
        try:
            reader = csv.DictReader(texto.splitlines(True), delimiter=delim)
            headers = reader.fieldnames or []
        except csv.Error:
            continue
        if "SKU" in headers and len(headers) > 1:
            melhor = (delim, headers)
            break
    if melhor is None:
        try:
            delim = csv.Sniffer().sniff(texto, delimiters=";,\t|").delimiter
        except csv.Error:
            delim = ";"
        try:
            reader_check = csv.DictReader(texto.splitlines(True), delimiter=delim)
            headers = reader_check.fieldnames or []
        except Exception:
            headers = []
    else:
        delim, headers = melhor
    reader = csv.DictReader(texto.splitlines(True), delimiter=delim)
    rows = []
    for raw_row in reader:
        row = {
            k: (v if v is not None else "")
            for k, v in raw_row.items()
            if k is not None
        }
        if any(v.strip() for v in row.values()):
            rows.append(row)
    return headers, rows


_PRICE_STATE_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "ConversorJumpseller" / "price_state.json"


def load_price_state() -> dict:
    if not _PRICE_STATE_FILE.is_file():
        return {}
    try:
        with open(_PRICE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_price_state(state: dict):
    try:
        _PRICE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_PRICE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as exc:
        raise OSError(f"Não foi possível guardar o estado dos preços: {exc}")


def _read_fornecedor_rows(fornecedor_path: str):
    out = []
    mapping = load_field_mapping()
    compiled_rules = get_compiled_keyword_rules()
    with open(fornecedor_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for raw_row in reader:
            row = {
                k: (v if v is not None else "")
                for k, v in raw_row.items()
                if k is not None
            }
            if not any(v.strip() for v in row.values()):
                continue
            out.append((convert_row(row, mapping, compiled_rules=compiled_rules), _parse_pt_number(row.get("preco", ""))))
    return out


def merge_update(export_path: str, fornecedor_path: str, output_dir: str, exclude_unavailable: bool = False):
    _, export_rows = _read_csv_any_delimiter(export_path)
    by_sku = {}
    for row in export_rows:
        sku = row.get("SKU", "").strip()
        if sku:
            by_sku.setdefault(sku, []).append(row)

    fornecedor_rows = _read_fornecedor_rows(fornecedor_path)
    prev_state = load_price_state()
    new_state = {}
    merged = []
    matched_skus = set()
    removed_unavailable = 0

    for row, preco_origem in fornecedor_rows:
        if exclude_unavailable:
            stock_raw = (row.get("Stock") or "0").strip()
            try:
                stock_num = int(float(stock_raw.replace(",", ".")))
            except Exception:
                stock_num = 0
            status = (row.get("Status") or "").strip().lower()
            if stock_num <= 0 or status == "not-available":
                removed_unavailable += 1
                continue
        sku = row.get("SKU", "").strip()
        existentes = by_sku.get(sku) if sku else None
        if existentes:
            principal = existentes[0]
            row["Permalink"] = (principal.get("Permalink") or "").strip()
            matched_skus.add(sku)
            row["Featured"] = (principal.get("Featured") or "").strip() or "NO"
            anterior = prev_state.get(sku)
            preco_mudou = (
                preco_origem is not None
                and (anterior is None or float(anterior) != preco_origem)
            )
            if not preco_mudou:
                row["Price"] = (principal.get("Price") or "").strip()
        else:
            row["Permalink"] = ""
        if sku and preco_origem is not None:
            new_state[sku] = preco_origem
        merged.append(row)

    for sku, existentes in by_sku.items():
        for indice, existing in enumerate(existentes):
            if sku in matched_skus and indice == 0:
                continue
            row = OrderedDict((col, "") for col in DEST_COLUMNS)
            for col in DEST_COLUMNS:
                if col in existing:
                    val = (existing[col] or "").strip()
                    if col == "Categories":
                        # Normalizar barras nos nomes de categorias e limitar a 4 níveis
                        def _norm_cat(c):
                            c = re.sub(r'\s*/\s*', ' e ', c)
                            parts = c.split('/')
                            if len(parts) > 4:
                                c = '/'.join(parts[:4])
                            return c
                        cats = [_norm_cat(c) for c in val.split(",")]
                        val = ",".join(cats)
                    row[col] = val
            row["Featured"] = (existing.get("Featured") or "").strip() or "NO"
            merged.append(row)

    export_stem = Path(export_path).stem if export_path else "loja_atualizada"
    output_path = os.path.join(output_dir, f"{export_stem}_atualizacao.csv")
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=DEST_COLUMNS, delimiter=";", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(merged)

    save_price_state(new_state)

    n_atualizados = len(matched_skus)
    n_novos = (len(fornecedor_rows) - removed_unavailable) - n_atualizados
    if n_novos < 0:
        n_novos = 0
    n_intactos = sum(len(v) for v in by_sku.values()) - n_atualizados
    return output_path, n_atualizados, n_novos, n_intactos, removed_unavailable


# ---------------------------------------------------------------------------
# DIALOGO DE MAPEAMENTO DE CAMPOS
# ---------------------------------------------------------------------------

class FieldMappingDialog:
    """Dialogo para mapear colunas do CSV."""

    # Todos os campos mapeáveis: (nome_esperado, descrição)
    MAPPABLE_FIELDS = [
        ("design", "Nome do produto (design)"),
        ("dimensoes", "Dimensões (dimensoes)"),
        ("codigo", "Código de barras (codigo)"),
        ("ref", "SKU / Referência (ref)"),
        ("peso", "Peso (peso)"),
        ("familia_principal", "Categoria principal (familia_principal)"),
        ("sub_familia", "Subcategoria (sub_familia)"),
        ("sub_sub_familia", "Sub-subcategoria (sub_sub_familia)"),
        ("desc1", "Descrição 1 (desc1)"),
        ("desc2", "Descrição 2 (desc2)"),
        ("desc3", "Descrição 3 (desc3)"),
        ("desc4", "Descrição 4 (desc4)"),
        ("desc5", "Descrição 5 (desc5)"),
        ("desc6", "Descrição 6 (desc6)"),
        ("marca", "Marca (marca)"),
        ("imagem", "URL da imagem (imagem)"),
        ("stock", "Stock (stock)"),
        ("preco", "Preço (preco)"),
    ]

    def __init__(self, parent, mapping=None, detected_mapping=None):
        self.parent = parent
        base_mapping = dict(mapping) if mapping else {}
        if detected_mapping:
            # Merge detected mapping with existing (detected fills empty/missing)
            merged = dict(base_mapping)
            for k, v in detected_mapping.items():
                if k not in merged or not merged.get(k) or str(merged.get(k)).strip() == "":
                    merged[k] = v
            self.mapping = merged
        else:
            self.mapping = base_mapping
        self.result = None
        self._build()

    def _build(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(f"Mapear Campos — {get_active_profile()}")
        self.win.geometry("600x480")
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.grab_set()

        # Instruções
        tk.Label(
            self.win,
            text=(
                "Associe as colunas do seu CSV aos campos esperados.\n"
                "Os campos foram preenchidos automaticamente com base no ficheiro selecionado.\n"
                "Deixe em branco para usar o nome esperado tal como está.\n"
                "Digite '-' para ignorar um campo."
            ),
            justify="left", bg=BG_WINDOW, fg=GRAY_800,
            font=("Segoe UI", 9),
        ).pack(fill="x", padx=12, pady=(10, 6))

        # Frame with scrollbar
        canvas = tk.Canvas(self.win, bg=BG_WINDOW, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.win, orient="vertical", command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", pady=(0, 10))

        # Build field rows
        self.entries = {}
        for row_idx, (field, desc) in enumerate(self.MAPPABLE_FIELDS):
            row_frame = ttk.Frame(self.scroll_frame)
            row_frame.pack(fill="x", pady=1)

            # Expected field label
            lbl = ttk.Label(row_frame, text=desc, width=38, anchor="w")
            lbl.pack(side="left", padx=(0, 6))

            # Arrow
            arrow = ttk.Label(row_frame, text="<-", width=3)
            arrow.pack(side="left")

            # Source column entry
            var = tk.StringVar(value=self.mapping.get(field, ""))
            entry = ttk.Entry(row_frame, textvariable=var, width=28)
            entry.pack(side="left", padx=(2, 0))
            self.entries[field] = var

        # Botões
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))

        # Todos os botões empilhados verticalmente para evitar truncagem
        ttk.Button(
            btn_frame, text="Restaurar padrão", command=self._reset, width=18
        ).pack(fill="x", pady=(0, 2))
        ttk.Button(
            btn_frame, text="Cancelar", command=self._cancel, width=18
        ).pack(fill="x", pady=(0, 2))
        ttk.Button(
            btn_frame, text="Guardar", command=self._save, width=18
        ).pack(fill="x")

        # Bind Escape
        self.win.bind("<Escape>", lambda e: self._cancel())
        # Bind Enter on entries
        for var in self.entries.values():
            pass  # entries already created

    def _reset(self):
        for field, var in self.entries.items():
            var.set(DEFAULT_FIELD_MAPPING.get(field, ""))

    def _cancel(self):
        self.result = None
        self.win.destroy()

    def _save(self):
        # Collect values
        new_mapping = {}
        for field, var in self.entries.items():
            val = var.get().strip()
            if val:
                new_mapping[field] = val
        self.result = new_mapping
        save_field_mapping(new_mapping)
        self.win.destroy()

    def show(self):
        self.parent.wait_window(self.win)
        return self.result


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(Tk):
    def __init__(self):
        super().__init__()
        from tkinterdnd2 import TkinterDnD
        TkinterDnD.require(self)
        self.title("CsvFast - File Converter")
        self.geometry("1200x800")
        self.minsize(900, 650)
        self.resizable(True, True)
        self.last_output = None
        self.language = get_language()
        self._status_widget = None   # widget onde _set_drop_text escreve
        self._apply_window_icon()
        self._build_ui()
        self._check_updates_startup()

        # Restaurar geometria anterior
        geometry = get_window_geometry()
        if geometry:
            self.geometry(geometry)
        if get_start_maximized():
            self.state("zoomed")

        # Salvar geometria ao fechar
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        try:
            set_window_geometry(self.geometry())
        except Exception:
            pass
        self.destroy()

    def _build_ui(self):
        apply_theme(self)

        # aplicar fundo
        bg_img = self._load_background()
        if bg_img:
            self.bg_label = tk.Label(self, image=bg_img)
            self.bg_label.image = bg_img
            self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
            self.bg_label.lower()

        # container superior com logo, botão de compra e botão de atualização
        top_container = tk.Frame(self, bg=BG_WINDOW)
        top_container.pack(fill="x", pady=0)
        top_container.lift()  # garantir que fique acima do fundo

        # logo (graceful: se o asset faltar, o label nao aparece)
        self._logo_label = self._load_logo()
        if self._logo_label:
            self._logo_label.pack(in_=top_container, anchor="w", pady=2)

        # indicador do fornecedor ativo
        self._active_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._active_fornecedor_lbl = tk.Label(
            top_container,
            textvariable=self._active_fornecedor_var,
            font=("Segoe UI", 9, "bold"),
            fg=GRAY_800,
            bg=BG_WINDOW,
        )
        self._active_fornecedor_lbl.pack(in_=top_container, side="left", padx=(16, 0), pady=2)

        # botão comprar licença (ocultado se houver licença válida)
        has_valid_license = False
        try:
            lic_path = self._stored_license_path()
            ok, _ = check_license(lic_path)
            if ok:
                has_valid_license = True
        except Exception:
            pass

        if not has_valid_license:
            self._buy_license_btn = tk.Button(
                top_container,
                text="Comprar Licença",
                command=self._open_stripe_checkout,
                bg=BLUE_700,
                fg=WHITE,
                activebackground=BLUE_500,
                activeforeground=WHITE,
                relief="flat",
                font=("Segoe UI", 9, "bold"),
                padx=12,
                pady=2,
                cursor="hand2",
            )
            self._buy_license_btn.pack(in_=top_container, side="right", padx=(0, 8), pady=2)

        # barra de separadores
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(2, 6))
        self.tabs.lift()

        self.tab_fornecedores = ttk.Frame(self.tabs, padding=8)
        self.tab_novo = ttk.Frame(self.tabs, padding=8)
        self.tab_update = ttk.Frame(self.tabs, padding=8)
        self.tab_lucro = ttk.Frame(self.tabs, padding=8)
        self.tab_sku_prefix = ttk.Frame(self.tabs, padding=8)
        self.tab_categorias_individuais = ttk.Frame(self.tabs, padding=8)
        self.tab_caturas_massivas = ttk.Frame(self.tabs, padding=8)
        self.tab_destaques = ttk.Frame(self.tabs, padding=8)
        self.tab_marcas = ttk.Frame(self.tabs, padding=8)
        self.tab_configuracoes = ttk.Frame(self.tabs, padding=8)
        self.tab_sobre = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.tab_fornecedores, text=f"  {translate('Fornecedores', self.language)}  ")
        self.tabs.add(self.tab_novo, text=f"  {translate('Novo Ficheiro', self.language)}  ")
        self.tabs.add(self.tab_update, text=f"  {translate('Atualizar Loja', self.language)}  ")
        self.tabs.add(self.tab_lucro, text=f"  {translate('Lucro e Taxas', self.language)}  ")
        self.tabs.add(self.tab_sku_prefix, text=f"  {translate('Prefixo SKU', self.language)}  ")
        self.tabs.add(self.tab_categorias_individuais, text=f"  {translate('Categorias I', self.language)}  ")
        self.tabs.add(self.tab_caturas_massivas, text=f"  {translate('Categorias M', self.language)}  ")
        self.tabs.add(self.tab_destaques, text=f"  {translate('Destaques', self.language)}  ")
        self.tabs.add(self.tab_marcas, text=f"  {translate('Marcas', self.language)}  ")
        self.tabs.add(self.tab_configuracoes, text=f"  {translate('Configurações', self.language)}  ")
        self.tabs.add(self.tab_sobre, text=f"  {translate('Sobre', self.language)}  ")

        self._build_tab_fornecedores()
        self._build_tab_novo()
        self._build_tab_update()
        self._build_tab_lucro()
        self._build_tab_sku_prefix()
        self._build_tab_caturas_individuais()
        self._build_tab_categorias_massivas()
        self._build_tab_destaques()
        self._build_tab_marcas()
        self._build_tab_configuracoes()
        self._build_tab_sobre()
        self._build_footer()
        self._translate_static_widgets()

        try:
            last_file = get_last_input_file()
            if last_file and os.path.isfile(last_file):
                self.path_var.set(last_file)
                self._update_drop_text(last_file)
                self._extract_categories_from_file(last_file)
        except Exception:
            pass

    # -- ícone da janela --------------------------------------------------

    def _apply_window_icon(self):
        """Define o ícone da aplicação (barra de título e taskbar)."""
        try:
            # iconbitmap com .ico é o método nativo do Windows (título + taskbar).
            ico_path = ASSETS / "icon.ico"
            if ico_path.is_file():
                try:
                    self.iconbitmap(str(ico_path))
                except Exception:
                    pass

            # Fallback com .png via iconphoto, sem depender de PIL.
            p = ASSETS / "icon.png"
            if p.is_file():
                try:
                    img = tk.PhotoImage(file=str(p))
                    self.iconphoto(True, img)
                    self._window_icon = img  # manter referência para não ser coletado pelo GC
                except Exception:
                    pass
        except Exception:
            pass

    # -- logo -----------------------------------------------------------

    def _load_logo(self):
        for name in ("logo.png", "logo.gif"):
            p = ASSETS / name
            if p.is_file():
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(p)
                    # Limitar largura e altura para caber no header (logo pequeno, não empurra as tabs)
                    max_w, max_h = 160, 60
                    ratio = min(max_w / im.width, max_h / im.height, 1.0)
                    im2 = im.resize((int(im.width * ratio), int(im.height * ratio)), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im2)
                    lbl = tk.Label(self, image=img, bg=BG_WINDOW)
                    lbl.image = img
                    return lbl
                except Exception:
                    try:
                        img = tk.PhotoImage(file=str(p))
                        lbl = tk.Label(self, image=img, bg=BG_WINDOW)
                        lbl.image = img
                        return lbl
                    except Exception:
                        continue
        return None

    def _load_background(self):
        for name in ("fundo.jpeg", "fundo.png", "background.png", "bg.png"):
            p = ASSETS / name
            if p.is_file():
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(p)
                    # Redimensionar para preencher a tela (será fixado pelo place() com relwidth/relheight)
                    # Como o label será colocado com place(), o tamanho exato não importa tanto aqui,
                    # mas ajuda a evitar erro de memória com imagens gigantes.
                    im2 = im.resize((1200, 800), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im2)
                    return img
                except Exception:
                    try:
                        img = tk.PhotoImage(file=str(p))
                        return img
                    except Exception:
                        continue
        return None

    def _build_footer(self):
        tk.Label(
            self,
            text=FOOTER_TEXT,
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 7),
            justify="center",
            wraplength=604,
        ).pack(fill="x", pady=(0, 4))

    def _translate_static_widgets(self):
        """Traduz todos os widgets estáticos da GUI com base no idioma atual."""
        import tkinter as _tk
        def _translate_widget(w, key):
            if isinstance(w, (_tk.Label, _tk.Button, _tk.Checkbutton, _tk.Radiobutton, _tk.Message, _tk.Menubutton)):
                try:
                    current = w.cget("text")
                    if current in TRANSLATABLE_STRINGS:
                        w.config(text=translate(current, self.language))
                except Exception:
                    pass
            elif isinstance(w, _tk.Toplevel):
                try:
                    current = w.title()
                    if current in TRANSLATABLE_STRINGS:
                        w.title(translate(current, self.language))
                except Exception:
                    pass
            elif isinstance(w, _tk.Frame):
                pass
            elif hasattr(w, "winfo_children"):
                for child in w.winfo_children():
                    _translate_widget(child, key)
        _translate_widget(self, "root")

    # -- tabs -----------------------------------------------------------

    def _build_tab_novo(self):
        frm_out = ttk.Frame(self)
        frm_out.pack(fill="x", padx=0, pady=(0, 6))
        ttk.Label(frm_out, text="Pasta de destino:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.out_dir_var = tk.StringVar()
        self.out_dir_var.set(str(Path.home() / "Downloads"))
        self.out_dir_entry = ttk.Entry(frm_out, textvariable=self.out_dir_var)
        self.out_dir_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        frm_out.columnconfigure(1, weight=1)
        ttk.Button(frm_out, text="Escolher pasta…", command=self._browse_output).grid(
            row=0, column=2, sticky="e"
        )

        frm_top = ttk.Frame(self.tab_novo)
        frm_top.pack(fill="x", pady=(0, 4))
        ttk.Label(frm_top, text="Arquivo CSV de entrada:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.path_var = tk.StringVar()
        self.path_entry = ttk.Entry(frm_top, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        frm_top.columnconfigure(1, weight=1)
        ttk.Button(frm_top, text="Escolher arquivo…", command=self._browse).grid(
            row=0, column=2, sticky="e"
        )

        # Spreadsheet Preview Container (Lado a Lado: Original vs Convertido)
        preview_container = ttk.Frame(self.tab_novo)
        preview_container.pack(fill="both", expand=True, pady=(4, 6))
        preview_container.columnconfigure(0, weight=1)
        preview_container.columnconfigure(1, weight=1)
        preview_container.rowconfigure(0, weight=1)

        # Coluna Esquerda: Original
        orig_frame = ttk.Frame(preview_container)
        orig_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._orig_preview_title_var = tk.StringVar(value="📄 CSV ORIGINAL (Nenhum ficheiro carregado)")
        ttk.Label(orig_frame, textvariable=self._orig_preview_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        orig_box = ttk.Frame(orig_frame)
        orig_box.pack(fill="both", expand=True)
        self._preview_orig_tree = ttk.Treeview(orig_box, show="headings", height=22)
        orig_scroll = ttk.Scrollbar(orig_box, orient="vertical", command=self._preview_orig_tree.yview)
        orig_scroll_x = ttk.Scrollbar(orig_box, orient="horizontal", command=self._preview_orig_tree.xview)
        self._preview_orig_tree.configure(yscrollcommand=orig_scroll.set, xscrollcommand=orig_scroll_x.set)
        self._preview_orig_tree.pack(side="left", fill="both", expand=True)
        orig_scroll.pack(side="right", fill="y")
        orig_scroll_x.pack(side="bottom", fill="x")

        # Coluna Direita: Convertido Jumpseller Preview
        conv_frame = ttk.Frame(preview_container)
        conv_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._conv_preview_title_var = tk.StringVar(value="✨ PREVIEW CONVERTIDO (Nenhum ficheiro carregado)")
        ttk.Label(conv_frame, textvariable=self._conv_preview_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        conv_box = ttk.Frame(conv_frame)
        conv_box.pack(fill="both", expand=True)
        self._preview_conv_tree = ttk.Treeview(conv_box, show="headings", height=22)
        conv_scroll = ttk.Scrollbar(conv_box, orient="vertical", command=self._preview_conv_tree.yview)
        conv_scroll_x = ttk.Scrollbar(conv_box, orient="horizontal", command=self._preview_conv_tree.xview)
        self._preview_conv_tree.configure(yscrollcommand=conv_scroll.set, xscrollcommand=conv_scroll_x.set)
        self._preview_conv_tree.pack(side="left", fill="both", expand=True)
        conv_scroll.pack(side="right", fill="y")
        conv_scroll_x.pack(side="bottom", fill="x")

        # Fallback / Status text hidden or minimized if needed, but treeviews take full space
        self.drop_text = None
        self._status_widget = None

        frm_opts = ttk.Frame(self.tab_novo)
        frm_opts.pack(fill="x", pady=(0, 4))
        self.exclude_unavailable_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opts,
            text="RETIRAR PRODUTOS INDISPONÍVEIS (stock 0 / not-available)",
            variable=self.exclude_unavailable_var,
        ).pack(side="left")

        frm_bot = ttk.Frame(self.tab_novo)
        frm_bot.pack(fill="x", pady=(0, 4))
        ttk.Button(frm_bot, text="Sair", command=self.destroy, width=10).pack(
            side="right", padx=(0, 8)
        )
        self.open_folder_btn = ttk.Button(
            frm_bot, text="Abrir pasta do resultado", command=self._open_folder, width=22
        )
        self.open_folder_btn.pack(side="right", padx=(0, 8))
        self.open_folder_btn.config(state="disabled")
        self.convert_btn = ttk.Button(
            frm_bot, text="Converter", command=self._convert, width=20
        )
        self.convert_btn.pack(side="right", padx=(0, 8))
        # Botão de mapeamento de campos
        self.mapping_btn = ttk.Button(
            frm_bot, text="Mapear Campos...", command=self._open_field_mapping, width=20
        )
        self.mapping_btn.pack(side="right", padx=(0, 8))
        self.path_entry.bind("<Return>", lambda ev: self._convert())

        # Seletor de fornecedor / perfil de mapeamento
        frm_for = ttk.Frame(self.tab_novo)
        frm_for.pack(fill="x", pady=(6, 2))
        ttk.Label(frm_for, text="Fornecedor:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.profile_var = tk.StringVar(value=get_active_profile())
        self.profile_combo = ttk.Combobox(
            frm_for, textvariable=self.profile_var, state="readonly", width=26
        )
        self.profile_combo.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_change)
        ttk.Button(
            frm_for, text="Novo", width=7, command=self._new_profile
        ).grid(row=0, column=2, sticky="w", padx=(0, 4))
        ttk.Button(
            frm_for, text="Eliminar", width=7, command=self._delete_profile
        ).grid(row=0, column=3, sticky="w")
        self._refresh_profile_combo()

    def _build_tab_update(self):
        self.export_var = tk.StringVar()
        self.fornecedor_var = tk.StringVar()

        frm_exp = ttk.Frame(self.tab_update)
        frm_exp.pack(fill="x", pady=(0, 6))
        ttk.Label(frm_exp, text="Export da loja (Jumpseller):").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(frm_exp, textvariable=self.export_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(frm_exp, text="Escolher arquivo…", command=self._browse_export).grid(
            row=0, column=2, sticky="e"
        )
        frm_exp.columnconfigure(1, weight=1)

        frm_for = ttk.Frame(self.tab_update)
        frm_for.pack(fill="x", pady=(0, 6))
        ttk.Label(frm_for, text="Novo ficheiro do fornecedor:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(frm_for, textvariable=self.fornecedor_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(frm_for, text="Escolher arquivo…", command=self._browse_fornecedor).grid(
            row=0, column=2, sticky="e"
        )
        frm_for.columnconfigure(1, weight=1)

        tk.Label(
            self.tab_update,
            text=(
                "Os produtos cujo SKU existe na loja recebem o Permalink "
                "e sao atualizados.\nOs que so existem no fornecedor sao "
                "criados (sem Permalink).\nOs que so existem na loja ficam "
                "intactos."
            ),
            fg=GRAY_600, justify="left", bg=BG_WINDOW,
            font=("Segoe UI", 9),
        ).pack(fill="x", pady=(4, 8))

        # Spreadsheet Preview Container (Lado a Lado: Original vs Convertido) para Atualizar Loja
        preview_container_up = ttk.Frame(self.tab_update)
        preview_container_up.pack(fill="both", expand=True, pady=(4, 6))
        preview_container_up.columnconfigure(0, weight=1)
        preview_container_up.columnconfigure(1, weight=1)
        preview_container_up.rowconfigure(0, weight=1)

        # Coluna Esquerda: Original
        orig_frame_up = ttk.Frame(preview_container_up)
        orig_frame_up.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ttk.Label(orig_frame_up, text="📄 FORNECEDOR ORIGINAL (Primeiras Linhas)", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        orig_box_up = ttk.Frame(orig_frame_up)
        orig_box_up.pack(fill="both", expand=True)
        self._preview_orig_tree_up = ttk.Treeview(orig_box_up, show="headings", height=22)
        orig_scroll_up = ttk.Scrollbar(orig_box_up, orient="vertical", command=self._preview_orig_tree_up.yview)
        orig_scroll_x_up = ttk.Scrollbar(orig_box_up, orient="horizontal", command=self._preview_orig_tree_up.xview)
        self._preview_orig_tree_up.configure(yscrollcommand=orig_scroll_up.set, xscrollcommand=orig_scroll_x_up.set)
        self._preview_orig_tree_up.pack(side="left", fill="both", expand=True)
        orig_scroll_up.pack(side="right", fill="y")
        orig_scroll_x_up.pack(side="bottom", fill="x")

        # Coluna Direita: Convertido Jumpseller Preview
        conv_frame_up = ttk.Frame(preview_container_up)
        conv_frame_up.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ttk.Label(conv_frame_up, text="✨ PREVIEW CONVERTIDO (Jumpseller)", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        conv_box_up = ttk.Frame(conv_frame_up)
        conv_box_up.pack(fill="both", expand=True)
        self._preview_conv_tree_up = ttk.Treeview(conv_box_up, show="headings", height=22)
        conv_scroll_up = ttk.Scrollbar(conv_box_up, orient="vertical", command=self._preview_conv_tree_up.yview)
        conv_scroll_x_up = ttk.Scrollbar(conv_box_up, orient="horizontal", command=self._preview_conv_tree_up.xview)
        self._preview_conv_tree_up.configure(yscrollcommand=conv_scroll_up.set, xscrollcommand=conv_scroll_x_up.set)
        self._preview_conv_tree_up.pack(side="left", fill="both", expand=True)
        conv_scroll_up.pack(side="right", fill="y")
        conv_scroll_x_up.pack(side="bottom", fill="x")

        self.drop_text_update = None
        self._status_widget_update = None

        frm_opts_up = ttk.Frame(self.tab_update)
        frm_opts_up.pack(fill="x", pady=(0, 4))
        if not hasattr(self, "exclude_unavailable_var"):
            self.exclude_unavailable_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opts_up,
            text="RETIRAR PRODUTOS INDISPONÍVEIS (stock 0 / not-available)",
            variable=self.exclude_unavailable_var,
        ).pack(side="left")

        frm_bot = ttk.Frame(self.tab_update)
        frm_bot.pack(fill="x")
        ttk.Button(frm_bot, text="Sair", command=self.destroy, width=10).pack(
            side="right", padx=(0, 8)
        )
        self.open_folder_btn2 = ttk.Button(
            frm_bot, text="Abrir pasta do resultado", command=self._open_folder, width=22
        )
        self.open_folder_btn2.pack(side="right", padx=(0, 8))
        self.open_folder_btn2.config(state="disabled")
        self.merge_btn = ttk.Button(
            frm_bot, text="Atualizar loja", command=self._merge, width=20
        )
        self.merge_btn.pack(side="right", padx=(0, 8))
        # Botão de mapeamento de campos (também disponível na aba de atualização)
        self.mapping_btn2 = ttk.Button(
            frm_bot, text="Mapear Campos...", command=self._open_field_mapping, width=20
        )
        self.mapping_btn2.pack(side="right", padx=(0, 8))

    def _build_tab_lucro(self):
        """Constrói a aba 'Lucro e Taxas' com configuração de preços."""
        frm = ttk.Frame(self.tab_lucro, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Configuração de Preços (por perfil)", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        frm_preco = ttk.Frame(frm)
        frm_preco.pack(fill="x", pady=(0, 8))

        try:
            from core.field_mapping import get_active_profile
            price_settings = get_price_settings(get_active_profile())
        except Exception:
            price_settings = get_price_settings()
        self._price_profit_var = tk.StringVar(value=str(price_settings.get("profit_percentage", 40.0)))
        self._price_iva_var = tk.StringVar(value=str(price_settings.get("iva_percentage", 0.0)))
        self._price_shipping_var = tk.StringVar(value=str(price_settings.get("shipping_cost", 0.0)))

        ttk.Label(frm_preco, text="Lucro %:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm_preco, textvariable=self._price_profit_var, width=8).grid(row=0, column=1, sticky="w", padx=(4, 10))
        ttk.Label(frm_preco, text="IVA %:").grid(row=0, column=2, sticky="w")
        ttk.Entry(frm_preco, textvariable=self._price_iva_var, width=8).grid(row=0, column=3, sticky="w", padx=(4, 10))
        ttk.Label(frm_preco, text="Portes (€):").grid(row=0, column=4, sticky="w")
        ttk.Entry(frm_preco, textvariable=self._price_shipping_var, width=8).grid(row=0, column=5, sticky="w", padx=(4, 10))
        ttk.Button(frm_preco, text="Guardar", command=self._save_price_settings, width=10).grid(row=0, column=6, sticky="w", padx=(4, 0))

        ttk.Label(frm, text="As configurações são guardadas por perfil e aplicadas apenas quando definidas.\nValores vazios ou zero (IVA/Portes) não são aplicados.", font=("Segoe UI", 9), foreground=GRAY_600, justify="left").pack(anchor="w", pady=(8, 0))

    def _build_tab_fornecedores(self):
        """Constrói a aba 'Fornecedores' para gerir e listar perfis."""
        frm = ttk.Frame(self.tab_fornecedores, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Gestão de Fornecedores (Perfis)", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            frm,
            text=(
                "Aqui pode criar novos fornecedores, remover fornecedores antigos ou selecionar qual o fornecedor "
                "ativo no momento. O fornecedor ativo é propagado automaticamente para todas as abas do programa "
                "(Novo Ficheiro, Atualizar Loja, Lucro e Taxas, Prefixo SKU, Categorias e Destaques e Marcas)."
            ),
            font=("Segoe UI", 9),
            foreground=GRAY_600,
            justify="left",
            wraplength=700,
        ).pack(anchor="w", pady=(0, 12))

        # Adicionar novo fornecedor
        add_row = ttk.Frame(frm)
        add_row.pack(fill="x", pady=(0, 12))
        ttk.Label(add_row, text="Novo Fornecedor:").pack(side="left", padx=(0, 6))
        self._new_forn_var = tk.StringVar()
        ttk.Entry(add_row, textvariable=self._new_forn_var, width=28).pack(side="left", padx=(0, 8))
        ttk.Button(add_row, text="Adicionar Fornecedor", command=self._tab_add_profile, width=18).pack(side="left")

        ttk.Label(frm, text="Fornecedores existentes (duplo clique ou botão para definir como ativo):", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        list_frame = ttk.Frame(frm)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        self._forn_listbox = tk.Listbox(list_frame, height=10, relief="sunken", bg=GRAY_100, font=("Segoe UI", 10), selectmode="single")
        forn_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._forn_listbox.yview)
        self._forn_listbox.configure(yscrollcommand=forn_scroll.set)
        self._forn_listbox.pack(side="left", fill="both", expand=True)
        forn_scroll.pack(side="right", fill="y")
        self._forn_listbox.bind("<Double-Button-1>", lambda e: self._tab_set_active_selected_profile())
        self._refresh_forn_list()

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Definir como Ativo", command=self._tab_set_active_selected_profile, width=18).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Eliminar Fornecedor", command=self._tab_delete_selected_profile, width=18).pack(side="left")

    def _set_active_profile_global(self, name: str):
        """Propaga a alteração do fornecedor ativo para todos os componentes do programa."""
        name = name.strip()
        if not name:
            return
        try:
            set_active_profile(name)
            self._active_fornecedor_var.set(name)

            # Atualizar seletor na aba Novo Ficheiro
            if hasattr(self, "profile_var"):
                self.profile_var.set(name)

            # Atualizar seletor na aba Categorias
            if hasattr(self, "_cat_fornecedor_var"):
                self._cat_fornecedor_var.set(name)
                self._refresh_cat_pai_combo()
                if hasattr(self, "_refresh_adv_rules_list"):
                    self._refresh_adv_rules_list()

            # Atualizar seletor na aba Destaques e Marcas
            if hasattr(self, "_hb_fornecedor_var"):
                self._hb_fornecedor_var.set(name)
                self._refresh_hb_pai_combo()
                if hasattr(self, "_refresh_hb_adv_rules_list"):
                    self._refresh_hb_adv_rules_list()

            # Atualizar seletor na aba Prefixo SKU e carregar o respetivo prefixo
            if hasattr(self, "_sku_fornecedor_var"):
                self._sku_fornecedor_var.set(name)
                if hasattr(self, "_sku_prefix_var"):
                    self._sku_prefix_var.set(get_sku_prefix(name))

            # Atualizar lista na aba Fornecedores
            if hasattr(self, "_forn_listbox"):
                self._refresh_forn_list()

            # Atualizar configurações de preço para o novo perfil
            try:
                price_settings = get_price_settings(name)
                if hasattr(self, '_price_profit_var'):
                    self._price_profit_var.set(str(price_settings.get("profit_percentage", 40.0)))
                if hasattr(self, '_price_iva_var'):
                    self._price_iva_var.set(str(price_settings.get("iva_percentage", 0.0)))
                if hasattr(self, '_price_shipping_var'):
                    self._price_shipping_var.set(str(price_settings.get("shipping_cost", 0.0)))
                if hasattr(self, '_price_formula_var'):
                    self._price_formula_var.set(price_settings.get("price_formula", "margin"))
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro ao propagar fornecedor:', self.language)} {e}", parent=self)

    def _refresh_forn_list(self):
        """Atualiza a lista de fornecedores na aba Fornecedores."""
        try:
            if hasattr(self, "_forn_listbox"):
                self._forn_listbox.delete(0, tk.END)
                profiles = list_profiles()
                active = get_active_profile()
                for p in profiles:
                    display_text = f"{p} (Ativo)" if p == active else p
                    self._forn_listbox.insert(tk.END, display_text)
        except Exception:
            pass

    def _tab_add_profile(self):
        name = self._new_forn_var.get().strip()
        if not name:
            messagebox.showwarning(translate("Atenção", self.language), translate("Insira o nome do novo fornecedor.", self.language), parent=self)
            return
        try:
            if save_profile(name, {}):
                self._new_forn_var.set("")
                self._set_active_profile_global(name)
                self._refresh_profile_combo()
                self._refresh_cat_fornecedor_combo()
                self._refresh_hb_fornecedor_combo()
                self._refresh_sku_fornecedor_combo()
                messagebox.showinfo(translate("Sucesso", self.language), f"{translate('Fornecedor', self.language)} '{name}' {translate('criado e selecionado com sucesso.', self.language)}", parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível criar o fornecedor.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro ao criar fornecedor:', self.language)} {e}", parent=self)

    def _tab_set_active_selected_profile(self):
        sel = self._forn_listbox.curselection()
        if not sel:
            messagebox.showwarning(translate("Atenção", self.language), translate("Selecione um fornecedor na lista.", self.language), parent=self)
            return
        profiles = list_profiles()
        idx = sel[0]
        if idx < len(profiles):
            name = profiles[idx]
            self._set_active_profile_global(name)
            self._refresh_profile_combo()
            self._refresh_cat_fornecedor_combo()
            self._refresh_hb_fornecedor_combo()
            self._refresh_sku_fornecedor_combo()
            messagebox.showinfo(translate("Ativo", self.language), f"{translate('Fornecedor', self.language)} '{name}' {translate('definido como ativo.', self.language)}", parent=self)

    def _tab_delete_selected_profile(self):
        sel = self._forn_listbox.curselection()
        if not sel:
            messagebox.showwarning(translate("Atenção", self.language), translate("Selecione um fornecedor na lista para eliminar.", self.language), parent=self)
            return
        profiles = list_profiles()
        idx = sel[0]
        if idx < len(profiles):
            name = profiles[idx]
            if len(profiles) <= 1:
                messagebox.showwarning(translate("Atenção", self.language), translate("Não pode eliminar o último fornecedor restante.", self.language), parent=self)
                return
            if messagebox.askyesno(translate("Eliminar", self.language), f"{translate('Tem certeza que deseja eliminar o fornecedor', self.language)} '{name}'?", parent=self):
                if delete_profile(name):
                    new_active = get_active_profile()
                    self._set_active_profile_global(new_active)
                    self._refresh_profile_combo()
                    self._refresh_cat_fornecedor_combo()
                    self._refresh_hb_fornecedor_combo()
                    self._refresh_sku_fornecedor_combo()
                    messagebox.showinfo(translate("Eliminado", self.language), f"{translate('Fornecedor', self.language)} '{name}' {translate('eliminado com sucesso.', self.language)}", parent=self)
                else:
                    messagebox.showerror(translate("Erro", self.language), translate("Não foi possível eliminar o fornecedor.", self.language), parent=self)

    def _build_dynamic_list(self, parent, label, values, add_command, remove_command):
        """Constrói uma lista dinâmica com campo de entrada, botão Adicionar e botão Remover."""
        frame = ttk.LabelFrame(parent, text=label, padding=6)
        frame.pack(fill="both", expand=True)

        entry_var = tk.StringVar()
        self._cat_new_listbox = frame

        entry_row = ttk.Frame(frame)
        entry_row.pack(fill="x", pady=(0, 4))
        entry = ttk.Entry(entry_row, textvariable=entry_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(entry_row, text=translate("Adicionar", self.language), command=add_command, width=10).pack(side="left")

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(
            list_frame, height=6, relief="sunken", bg=GRAY_100,
            font=("Consolas", 9), selectmode="single", exportselection=False,
        )
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for value in values:
            if value.strip():
                listbox.insert(tk.END, value)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text=translate("Remover", self.language), command=lambda: remove_command(listbox), width=10).pack(side="left")

        frame._entry_var = entry_var
        frame._listbox = listbox
        return frame

    def _get_listbox_values(self, frame):
        """Devolve os valores de uma lista dinâmica."""
        if not hasattr(frame, "_listbox"):
            return []
        listbox = frame._listbox
        return [listbox.get(i).strip() for i in range(listbox.size()) if listbox.get(i).strip()]

    def _add_cat_new_item(self):
        """Adiciona um item à lista dinâmica de categorias pai."""
        if not hasattr(self, "_cat_new_listbox"):
            return
        value = self._cat_new_listbox._entry_var.get().strip()
        if not value:
            return
        self._cat_new_listbox._listbox.insert(tk.END, value)
        self._cat_new_listbox._entry_var.set("")
        self._save_category_settings()

    def _remove_cat_new_item(self, listbox):
        """Remove o item selecionado da lista dinâmica de categorias pai."""
        selection = listbox.curselection()
        if selection:
            listbox.delete(selection[0])
            self._save_category_settings()

    def _add_massive_parent_item(self):
        """Adiciona um item à lista dinâmica de categorias pai massivas."""
        if not hasattr(self, "_massive_parent_listbox"):
            return
        value = self._massive_parent_listbox._entry_var.get().strip()
        if not value:
            return
        self._massive_parent_listbox._listbox.insert(tk.END, value)
        self._massive_parent_listbox._entry_var.set("")
        self._save_massive_parents()

    def _remove_massive_parent_item(self, listbox):
        """Remove o item selecionado da lista dinâmica de categorias pai massivas."""
        selection = listbox.curselection()
        if selection:
            listbox.delete(selection[0])
            self._save_massive_parents()

    def _build_tab_caturas_individuais(self):
        """Constrói a aba 'CATEGORIAS i' (individuais) com mapeamento de categorias."""
        frm = ttk.Frame(self.tab_categorias_individuais, padding=6)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Mapeamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

        # Linha de instrução com seletor de fornecedor ao lado
        header_row = ttk.Frame(frm)
        header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(header_row, text="Crie categorias pai para agrupar as categorias do fornecedor", font=("Segoe UI", 9), foreground=GRAY_600).pack(side="left")
        ttk.Label(header_row, text="  Fornecedor:", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self._cat_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._cat_fornecedor_combo = ttk.Combobox(header_row, textvariable=self._cat_fornecedor_var, state="readonly", width=24)
        self._cat_fornecedor_combo.pack(side="left")
        self._cat_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_cat_fornecedor_change)
        self._refresh_cat_fornecedor_combo()

        # Lista dinâmica de categorias pai (sem limite)
        self._cat_new_listbox = self._build_dynamic_list(
            parent=frm,
            label="Categorias Pai",
            values=get_category_settings().get("new_categories", []),
            add_command=self._add_cat_new_item,
            remove_command=self._remove_cat_new_item,
        )
        self._cat_new_entry_var = self._cat_new_listbox._entry_var

        # Manter hierarquia original está sempre activo (não é configurável pelo utilizador)
        self._cat_use_parent_var = tk.BooleanVar(value=True)

        ttk.Button(frm, text="Guardar todas as configurações de categorias", command=self._save_category_settings, width=45).pack(anchor="w", pady=(4, 0))

        # ---- Mapeamento Avançado (regras por Categoria e Subcategoria) ----
        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))
        ttk.Label(frm, text="Mapeamento Avançado — regras por Categoria e Subcategoria", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(frm, text="Associe automaticamente produtos a uma categoria pai com base na Categoria e Subcategoria originais do fornecedor.", font=("Segoe UI", 8), foreground=GRAY_600).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            frm,
            text=(
                "Como funciona: indique a Categoria e a Subcategoria do fornecedor (deixe a subcategoria vazia para aplicar a toda a categoria) "
                "e selecione a Categoria Pai de destino. Evita falsos positivos no nome dos produtos (ex: 'teclado' no nome de um portátil). "
                "Regras mais recentes têm maior prioridade. Aplica na 'Conversão' e no 'Atualizar Loja'."
            ),
            font=("Segoe UI", 8),
            foreground=GRAY_600,
            justify="left",
            wraplength=700,
        ).pack(anchor="w", pady=(0, 6))

        adv_row = ttk.Frame(frm)
        adv_row.pack(fill="x", pady=2)
        ttk.Label(adv_row, text="Cat.:").pack(side="left", padx=(0, 2))
        self._adv_cat_var = tk.StringVar()
        self._adv_cat_combo = ttk.Combobox(adv_row, textvariable=self._adv_cat_var)
        self._adv_cat_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(adv_row, text="Subcat.:").pack(side="left", padx=(4, 2))
        self._adv_subcat_var = tk.StringVar()
        self._adv_subcat_combo = ttk.Combobox(adv_row, textvariable=self._adv_subcat_var)
        self._adv_subcat_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(adv_row, text="Pai:").pack(side="left", padx=(4, 2))
        self._cat_pai_combo = ttk.Combobox(adv_row, state="readonly")
        self._cat_pai_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(adv_row, text="Adicionar Regra", command=self._add_advanced_keyword_rule, width=14).pack(side="left", padx=(0, 4))
        ttk.Button(adv_row, text="Remover Regra", command=self._remove_advanced_keyword_rule, width=14).pack(side="left")
        self._refresh_cat_pai_combo()

        ttk.Label(frm, text="Regras configuradas (mais recente = maior prioridade) — selecione para remover:", font=("Segoe UI", 9), foreground=GRAY_600).pack(anchor="w", pady=(6, 2))
        adv_frame = ttk.Frame(frm)
        adv_frame.pack(fill="both", expand=True)
        self._adv_rules_listbox = tk.Listbox(adv_frame, height=6, relief="sunken", bg=GRAY_100, font=("Consolas", 8), selectmode="single")
        adv_scroll = ttk.Scrollbar(adv_frame, orient="vertical", command=self._adv_rules_listbox.yview)
        self._adv_rules_listbox.configure(yscrollcommand=adv_scroll.set)
        self._adv_rules_listbox.pack(side="left", fill="both", expand=True)
        adv_scroll.pack(side="right", fill="y")
        self._adv_rules_listbox.bind("<Double-Button-1>", lambda e: self._remove_advanced_keyword_rule())
        self._refresh_adv_rules_list()

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))

        # Listagem em duas colunas: Categorias Únicas e Categorias e Subcategorias
        lists_container = ttk.Frame(frm)
        lists_container.pack(fill="both", expand=True, pady=(2, 0))
        lists_container.columnconfigure(0, weight=1)
        lists_container.columnconfigure(1, weight=1)
        lists_container.rowconfigure(0, weight=1)

        # Coluna 1: Categorias Únicas
        col1_frame = ttk.Frame(lists_container)
        col1_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._cat_unique_title_var = tk.StringVar(value="CATEGORIAS ÚNICAS (0)")
        ttk.Label(col1_frame, textvariable=self._cat_unique_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        c1_box = ttk.Frame(col1_frame)
        c1_box.pack(fill="both", expand=True)
        self._cat_unique_text = tk.Text(c1_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        c1_scroll = ttk.Scrollbar(c1_box, orient="vertical", command=self._cat_unique_text.yview)
        self._cat_unique_text.configure(yscrollcommand=c1_scroll.set)
        self._cat_unique_text.pack(side="left", fill="both", expand=True)
        c1_scroll.pack(side="right", fill="y")
        self._cat_unique_text.config(state="disabled")

        # Coluna 2: Categorias e Subcategorias
        col2_frame = ttk.Frame(lists_container)
        col2_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._cat_subcat_title_var = tk.StringVar(value="CATEGORIAS E SUBCATEGORIAS (0)")
        ttk.Label(col2_frame, textvariable=self._cat_subcat_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        c2_box = ttk.Frame(col2_frame)
        c2_box.pack(fill="both", expand=True)
        self._cat_subcat_text = tk.Text(c2_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        c2_scroll = ttk.Scrollbar(c2_box, orient="vertical", command=self._cat_subcat_text.yview)
        self._cat_subcat_text.configure(yscrollcommand=c2_scroll.set)
        self._cat_subcat_text.pack(side="left", fill="both", expand=True)
        c2_scroll.pack(side="right", fill="y")
        self._cat_subcat_text.config(state="disabled")

        search_row = ttk.Frame(frm)
        search_row.pack(fill="x", pady=(6, 4))
        ttk.Label(search_row, text="🔍 Pesquisar:").pack(side="left", padx=(0, 4))
        self._cat_search_var = tk.StringVar()
        self._cat_search_var.trace_add("write", lambda *args: self._filter_categories())
        ttk.Entry(search_row, textvariable=self._cat_search_var, width=28).pack(side="left", padx=(0, 8))
        ttk.Button(search_row, text="🔄 Recarregar", command=self._reload_categories, width=14).pack(side="left")

    def _build_tab_categorias_massivas(self):
        """Constrói a aba 'CATEGORIAS M' para agrupamento massivo."""
        frm = ttk.Frame(self.tab_caturas_massivas, padding=6)
        frm.pack(fill="both", expand=True)

        top = ttk.Frame(frm)
        top.pack(fill="both", expand=False)
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        # Cada coluna mantém o seu cabeçalho e descrição, sem deslocar a outra coluna.
        left = ttk.Frame(top, padding=(0, 0, 5, 0))
        left.grid(row=0, column=0, sticky="nsew")
        ttk.Label(left, text=translate("Mapeamento Massivo", self.language), font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            left,
            text=translate("Agrupe uma categoria do fornecedor e todas as suas subcategorias numa Categoria Pai. As regras aplicam-se automaticamente na conversão e na atualização da loja.", self.language),
            font=("Segoe UI", 9), foreground=GRAY_600, wraplength=430, justify="left",
        ).pack(anchor="w", pady=(0, 6))
        self._massive_parent_listbox = self._build_dynamic_list(
            parent=left,
            label=translate("Categorias Pai", self.language),
            values=get_category_settings().get("new_categories", []),
            add_command=self._add_massive_parent_item,
            remove_command=self._remove_massive_parent_item,
        )
        ttk.Button(
            left,
            text="Guardar categorias pai",
            command=self._save_massive_parents,
            width=26,
        ).pack(anchor="w", pady=(5, 0))

        right = ttk.Frame(top, padding=(5, 0, 0, 0))
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text=translate("Lista de Regras", self.language), font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            right,
            text=(
                translate("Insira as regras para associar grupos de categorias e as subcategorias a uma categoria pai.", self.language) + "\n"
                + translate("Ex: Todas as linhas das categorias de artigos para o lar e casa enviar para...", self.language)
            ),
            font=("Segoe UI", 8), foreground=GRAY_600, wraplength=430, justify="left",
        ).pack(anchor="w", pady=(0, 6))
        right_body = ttk.Frame(right, padding=6)
        right_body.pack(fill="both", expand=True)
        right = right_body

        # Lista dinâmica de regras (campo único + Adicionar/Remover, sem limite)
        self._massive_rules_dyn_list = self._build_dynamic_list(
            parent=right,
            label=translate("Regras", self.language),
            values=[str(r.get("description", "")).strip() or str(r.get("category_group", "")).strip()
                    for r in get_massive_category_rules()],
            add_command=self._add_massive_rule_from_dynamic,
            remove_command=self._remove_massive_rule_from_dynamic,
        )

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(8, 6))
        ttk.Label(
            frm,
            text=translate("Escolha uma categoria principal da origem. Todas as respetivas subcategorias serão incluídas automaticamente.", self.language),
            font=("Segoe UI", 8),
            foreground=GRAY_600,
        ).pack(anchor="w", pady=(0, 4))

        rule_row = ttk.Frame(frm)
        rule_row.pack(fill="x", pady=2)
        ttk.Label(rule_row, text=translate("Nome da regra:", self.language)).pack(side="left", padx=(0, 4))
        self._massive_description_var = tk.StringVar()
        self._massive_description_combo = ttk.Combobox(
            rule_row, textvariable=self._massive_description_var, state="normal", width=48
        )
        self._massive_description_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._massive_description_combo.bind("<<ComboboxSelected>>", self._on_massive_description_selected)
        ttk.Label(rule_row, text=translate("Categoria pai:", self.language)).pack(side="left", padx=(0, 4))
        self._massive_parent_var = tk.StringVar()
        self._massive_parent_combo = ttk.Combobox(
            rule_row, textvariable=self._massive_parent_var, state="readonly", width=28
        )
        self._massive_parent_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(rule_row, text=translate("Adicionar Regra", self.language), command=self._add_massive_rule, width=15).pack(side="left", padx=(0, 4))
        ttk.Button(rule_row, text=translate("Remover Regra", self.language), command=self._remove_massive_rule, width=15).pack(side="left")

        # Instrução guiada para o usuário (ex: "Selecione categorias de origem e depois a Categoria Pai")
        self._massive_instruction_var = tk.StringVar(
            value=translate("Escolha uma regra na lista para editar, ou crie uma nova.", self.language)
        )
        self._massive_instruction_lbl = ttk.Label(
            frm,
            textvariable=self._massive_instruction_var,
            font=("Segoe UI", 8),
            foreground=GRAY_600,
            justify="left",
        )
        self._massive_instruction_lbl.pack(anchor="w", pady=(2, 2))

        source_row = ttk.Frame(frm)
        source_row.pack(fill="x", pady=(4, 2))
        ttk.Label(source_row, text=translate("Categorias de origem (use a janela 'Selecionar' para marcar):", self.language)).pack(anchor="w")
        sel_origem_frame = ttk.Frame(source_row)
        sel_origem_frame.pack(fill="x", pady=(2, 0))
        ttk.Button(
            sel_origem_frame,
            text=translate("Selecionar Categorias de Origem…", self.language),
            command=self._open_massive_origem_selector_dialog,
            width=30,
        ).pack(side="left", padx=(0, 6))
        ttk.Label(
            sel_origem_frame,
            textvariable=self._massive_selected_origem_count_var,
            font=("Segoe UI", 8),
            foreground=GRAY_600,
        ).pack(side="left")
        self._massive_source_listbox = tk.Listbox(
            source_row, height=5, relief="sunken", bg=GRAY_100,
            font=("Consolas", 8), selectmode="extended", exportselection=False,
        )
        source_scroll = ttk.Scrollbar(source_row, orient="vertical", command=self._massive_source_listbox.yview)
        self._massive_source_listbox.configure(yscrollcommand=source_scroll.set)
        self._massive_source_listbox.pack(side="left", fill="both", expand=True)
        source_scroll.pack(side="right", fill="y")
        self._massive_source_listbox.bind("<<ListboxSelect>>", lambda _e: self._on_massive_source_listbox_selected())
        self._massive_rule_ids = {}
        self._massive_rule_list_indices = []
        self._massive_selected_rule_id = None
        self._massive_selected_origem_count_var = tk.StringVar(value="")
        self._massive_selected_source_indices = set()
        self._massive_origem_search_var = tk.StringVar()
        self._refresh_massive_description_combo()
        self._refresh_massive_parent_combo()
        self._refresh_massive_source_list()

        ttk.Label(frm, text=translate("Regras configuradas (as mais recentes têm prioridade):", self.language), font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 2))
        rules_frame = ttk.Frame(frm)
        rules_frame.pack(fill="x", expand=False)
        self._massive_rules_listbox = tk.Listbox(
            rules_frame, height=5, relief="sunken", bg=GRAY_100,
            font=("Consolas", 8), selectmode="single"
        )
        rules_scroll = ttk.Scrollbar(rules_frame, orient="vertical", command=self._massive_rules_listbox.yview)
        self._massive_rules_listbox.configure(yscrollcommand=rules_scroll.set)
        self._massive_rules_listbox.pack(side="left", fill="both", expand=True)
        rules_scroll.pack(side="right", fill="y")
        self._refresh_massive_rules_list()
        self._massive_rules_listbox.bind("<<ListboxSelect>>", self._on_massive_rule_list_selected)

        # Preview dinâmico do resultado da regra
        self._massive_preview_var = tk.StringVar(value="")
        self._massive_preview_lbl = ttk.Label(
            frm,
            textvariable=self._massive_preview_var,
            font=("Segoe UI", 8, "italic"),
            foreground="#0055AA",
            justify="left",
        )
        self._massive_preview_lbl.pack(anchor="w", pady=(4, 2))

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(8, 6))
        lists = ttk.Frame(frm)
        lists.pack(fill="both", expand=True)
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        lists.rowconfigure(0, weight=1)
        self._massive_unique_title_var = tk.StringVar(value="CATEGORIAS ÚNICAS (0)")
        self._massive_subcat_title_var = tk.StringVar(value="CATEGORIAS E SUBCATEGORIAS (0)")
        self._massive_unique_text = self._create_category_text_panel(
            lists, self._massive_unique_title_var, 0
        )
        self._massive_subcat_text = self._create_category_text_panel(
            lists, self._massive_subcat_title_var, 1
        )
        search = ttk.Frame(frm)
        search.pack(fill="x", pady=(6, 0))
        ttk.Label(search, text="Pesquisar:").pack(side="left", padx=(0, 4))
        self._massive_search_var = tk.StringVar()
        self._massive_search_var.trace_add("write", lambda *_: self._filter_massive_categories())
        ttk.Entry(search, textvariable=self._massive_search_var, width=28).pack(side="left", padx=(0, 8))
        ttk.Button(search, text="Recarregar", command=self._reload_categories, width=14).pack(side="left")

    def _create_category_text_panel(self, parent, title_var, column):
        panel = ttk.Frame(parent)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 4 if column == 0 else 0))
        ttk.Label(panel, textvariable=title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        box = ttk.Frame(panel)
        box.pack(fill="both", expand=True)
        text = tk.Text(box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        scroll = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.config(state="disabled")
        return text

    def _add_massive_rule_from_dynamic(self):
        """Adiciona uma nova regra massiva a partir da lista dinâmica."""
        if not hasattr(self, "_massive_rules_dyn_list"):
            return
        value = self._massive_rules_dyn_list._entry_var.get().strip()
        if not value:
            return
        if save_massive_category_rule(value, [], ""):
            self._massive_rules_dyn_list._listbox.insert(tk.END, value)
            self._massive_rules_dyn_list._entry_var.set("")
            self._refresh_massive_rules_list()
            self._refresh_massive_description_combo()
        else:
            messagebox.showerror(
                translate("Erro", self.language),
                translate("Não foi possível guardar a regra.", self.language),
                parent=self,
            )

    def _remove_massive_rule_from_dynamic(self, listbox):
        """Remove a regra selecionada da lista dinâmica."""
        selection = listbox.curselection()
        if not selection:
            return
        value = listbox.get(selection[0]).strip()
        if not value:
            return
        rules = get_massive_category_rules()
        for i, rule in enumerate(rules):
            description = str(rule.get("description", "")).strip() or str(rule.get("category_group", "")).strip()
            if description == value:
                if remove_massive_category_rule(i):
                    listbox.delete(selection[0])
                    self._refresh_massive_rules_list()
                    self._refresh_massive_description_combo()
                break

    def _save_massive_parents(self):
        values = self._get_listbox_values(self._massive_parent_listbox)
        set_category_settings(
            new_categories=values,
            apply_to_all=False,
            selected_prefix="",
            use_parent=True,
        )
        self._refresh_massive_parent_combo()
        self._refresh_cat_pai_combo()

    def _refresh_massive_parent_combo(self):
        if hasattr(self, "_massive_parent_combo"):
            settings = get_category_settings()
            values = [value.strip() for value in settings.get("new_categories", []) if value.strip()]
            self._massive_parent_combo["values"] = values

    def _refresh_massive_description_combo(self):
        if not hasattr(self, "_massive_description_combo"):
            return
        rules = get_massive_category_rules()
        descriptions = []
        for rule in rules:
            description = str(rule.get("description", "")).strip()
            if not description:
                description = str(rule.get("category_group", "")).strip()
            if description and description not in descriptions:
                descriptions.append(description)
        self._massive_description_combo["values"] = descriptions
        self._massive_rule_ids = {
            str(rule.get("description", "")).strip() or str(rule.get("category_group", "")).strip(): rule.get("rule_id")
            for rule in rules
            if str(rule.get("description", "")).strip() or str(rule.get("category_group", "")).strip()
        }

    def _refresh_massive_source_list(self):
        if not hasattr(self, "_massive_source_listbox"):
            return
        values = list(getattr(self, "_unique_categories", []))
        self._massive_source_listbox.delete(0, tk.END)
        for value in values:
            self._massive_source_listbox.insert(tk.END, value)
        self._massive_source_list_values = values

    def _refresh_massive_group_combo(self):
        """Compatibilidade com chamadas antigas; atualiza a lista de origens."""
        self._refresh_massive_source_list()

    def _update_massive_instruction(self):
        """Atualiza a instrução guiada conforme o estado da seleção."""
        if self._massive_selected_rule_id:
            msg = translate("Editando regra selecionada. Altere os campos e clique em 'Adicionar Regra' para guardar as alterações.", self.language)
        else:
            msg = translate("Preencha o nome, selecione as categorias de origem e a Categoria Pai, depois clique em 'Adicionar Regra'.", self.language)
        self._massive_instruction_var.set(msg)

    def _on_massive_description_selected(self, _event=None):
        description = self._massive_description_var.get().strip()
        rule = next(
            (
                item for item in get_massive_category_rules()
                if (str(item.get("description", "")).strip() or str(item.get("category_group", "")).strip()) == description
            ),
            None,
        )
        self._massive_selected_rule_id = rule.get("rule_id") if rule else None
        if rule:
            self._massive_parent_var.set(str(rule.get("parent_category", "")).strip())
            sources = rule.get("source_categories")
            if not isinstance(sources, list):
                legacy = str(rule.get("category_group", "")).strip()
                sources = [legacy] if legacy else []
            source_values = getattr(self, "_massive_source_list_values", [])
            self._massive_source_listbox.selection_clear(0, tk.END)
            normalized_sources = {str(source).strip().casefold() for source in sources}
            for index, value in enumerate(source_values):
                if str(value).strip().casefold() in normalized_sources:
                    self._massive_source_listbox.selection_set(index)
            self._update_massive_instruction()
            self._update_massive_preview()
        else:
            self._massive_parent_var.set("")
            self._massive_source_listbox.selection_clear(0, tk.END)
            self._update_massive_instruction()
            self._update_massive_preview()

    def _on_massive_rule_list_selected(self, _event=None):
        selection = self._massive_rules_listbox.curselection()
        if not selection or selection[0] >= len(self._massive_rule_list_indices):
            return
        rules = get_massive_category_rules()
        rule_index = self._massive_rule_list_indices[selection[0]]
        rule = rules[rule_index] if rule_index < len(rules) else None
        if not rule:
            return
        description = str(rule.get("description", "")).strip() or str(rule.get("category_group", "")).strip()
        if description in self._massive_description_combo["values"]:
            self._massive_description_var.set(description)
            self._on_massive_description_selected()

    def _add_massive_rule(self):
        description = self._massive_description_var.get().strip()
        parent = self._massive_parent_var.get().strip()
        selection = self._massive_source_listbox.curselection()
        source_values = getattr(self, "_massive_source_list_values", [])
        sources = [source_values[index] for index in selection if index < len(source_values)]
        if not description or not sources or not parent:
            messagebox.showwarning(
                "Atenção",
                "Escolha a regra, uma ou mais categorias de origem e a Categoria Pai.",
                parent=self,
            )
            return
        rules = get_massive_category_rules()
        rule_id = self._massive_selected_rule_id
        # Verificar se é uma nova regra ou atualização de uma existente pelo ID ou descrição
        is_update = False
        if rule_id:
            is_update = True
        else:
            # Também é update se a descrição já existir
            for rule in rules:
                if str(rule.get("description", "")).strip() == description or \
                   str(rule.get("category_group", "")).strip() == description:
                    is_update = True
                    break

        if not is_update and len(rules) >= 10:
            messagebox.showwarning(translate("Limite atingido", self.language), translate("Só pode criar até 10 regras massivas.", self.language), parent=self)
            return
        if save_massive_category_rule(description, sources, parent, rule_id=rule_id):
            self._massive_selected_rule_id = None
            self._massive_description_var.set("")
            self._massive_parent_var.set("")
            self._massive_source_listbox.selection_clear(0, tk.END)
            self._refresh_massive_description_combo()
            self._refresh_massive_rules_list()
            messagebox.showinfo(translate("Guardado", self.language), translate("Regra de mapeamento massivo guardada.", self.language), parent=self)
            self._massive_selected_rule_id = None
            self._update_massive_instruction()
        else:
            messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar a regra.", self.language), parent=self)

    def _refresh_massive_rules_list(self):
        if not hasattr(self, "_massive_rules_listbox"):
            return
        self._massive_rules_listbox.delete(0, tk.END)
        self._massive_rule_list_indices = []
        rules = get_massive_category_rules()
        for rule_index, rule in enumerate(rules):
            description = str(rule.get("description", "")).strip() or str(rule.get("category_group", "")).strip()
            sources = rule.get("source_categories")
            if not isinstance(sources, list):
                sources = [str(rule.get("category_group", "")).strip()]
            source_text = ", ".join(source for source in sources if source)
            self._massive_rules_listbox.insert(
                tk.END,
                f"[P{rule.get('priority', 0)}] {description} | {source_text} -> {rule.get('parent_category', '')}",
            )
            self._massive_rule_list_indices.append(rule_index)
        if not rules:
            self._massive_rules_listbox.insert(tk.END, "(Nenhuma regra massiva configurada)")

    def _remove_massive_rule(self):
        selection = self._massive_rules_listbox.curselection()
        if not selection or selection[0] >= len(self._massive_rule_list_indices):
            messagebox.showwarning(translate("Atenção", self.language), translate("Selecione uma regra para remover.", self.language), parent=self)
            return
        rules = get_massive_category_rules()
        rule_index = self._massive_rule_list_indices[selection[0]]
        rule = rules[rule_index] if rule_index < len(rules) else None
        if rule is None:
            messagebox.showwarning(translate("Atenção", self.language), translate("A regra selecionada já não existe.", self.language), parent=self)
            self._refresh_massive_rules_list()
            return
        description = str(rule.get("description", "")).strip() or str(rule.get("category_group", "")).strip()
        if messagebox.askyesno(translate("Remover Regra", self.language), f"{translate('Remover a regra', self.language)} '{description}'?", parent=self):
            if remove_massive_category_rule(rule_index):
                self._massive_selected_rule_id = None
                self._refresh_massive_description_combo()
                self._refresh_massive_rules_list()
                self._update_massive_instruction()

    def _filter_massive_categories(self):
        query = self._massive_search_var.get().strip().lower()
        unique_all = getattr(self, "_unique_categories", [])
        subcat_all = getattr(self, "_subcat_categories", [])
        unique = [item for item in unique_all if not query or query in item.lower()]
        subcats = [item for item in subcat_all if not query or query in item.lower()]
        self._massive_unique_title_var.set(f"CATEGORIAS ÚNICAS ({len(unique)})")
        self._massive_subcat_title_var.set(f"CATEGORIAS E SUBCATEGORIAS ({len(subcats)})")
        for widget, values, empty in (
            (self._massive_unique_text, unique, "(nenhuma categoria)"),
            (self._massive_subcat_text, subcats, "(nenhuma categoria)"),
        ):
            widget.config(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", "\n".join(values) if values else empty)
            widget.config(state="disabled")

    def _filter_massive_origens_search(self):
        """Mantido para compatibilidade: o filtro de pesquisa vive no diálogo modal."""
        self._update_selected_source_count()

    def _update_massive_preview(self):
        """Mostra ao utilizador como a regra será aplicada no resultado."""
        if not hasattr(self, "_massive_preview_var"):
            return
        parent = self._massive_parent_var.get().strip()
        sources = self._get_selected_sources_from_indices()
        if not sources or not parent:
            self._massive_preview_var.set("")
            return
        fontes = ", ".join(sources)
        self._massive_preview_var.set(
            translate("Resultado: quando encontradas as categorias '{fontes}', os produtos serão movidos para '{pai}'.".format(fontes=fontes, pai=parent), self.language)
        )

    def _get_selected_sources_from_indices(self):
        """Retorna as categorias de origem selecionadas (Listbox ou dialog)."""
        if not hasattr(self, "_massive_source_listbox"):
            return []
        source_values = getattr(self, "_massive_source_list_values", [])
        selection = self._massive_source_listbox.curselection()
        if selection:
            return [source_values[index] for index in selection if index < len(source_values)]
        # Fallback para seleção via dialog (guarda em _massive_selected_source_indices)
        selected = set(getattr(self, "_massive_selected_source_indices", set()))
        return [v for i, v in enumerate(source_values) if i in selected]

    def _on_massive_source_listbox_selected(self):
        """Sincroniza a seleção do listbox com o estado do diálogo modal."""
        if hasattr(self, "_massive_source_listbox") and hasattr(self, "_massive_source_list_values"):
            self._massive_selected_source_indices = set(self._massive_source_listbox.curselection())
        self._update_selected_source_count()

    def _update_selected_source_count(self):
        sources = self._get_selected_sources_from_indices()
        n = len(sources)
        self._massive_selected_origem_count_var.set(f"({n} selecionada(s))" if n > 0 else "")
        # Reflete a seleção do dialog no listbox visível
        if hasattr(self, "_massive_source_listbox") and hasattr(self, "_massive_source_list_values"):
            source_values = self._massive_source_list_values
            selected_names = {str(v).strip().casefold() for v in sources}
            self._massive_source_listbox.selection_clear(0, tk.END)
            for index, value in enumerate(source_values):
                if str(value).strip().casefold() in selected_names:
                    self._massive_source_listbox.selection_set(index)
        self._update_massive_preview()

    def _open_massive_origem_selector_dialog(self):
        """Abre um dialog modal com checkboxes para selecionar categorias de origem de forma clara."""
        dialog = tk.Toplevel(self)
        dialog.title(translate("Selecionar Categorias de Origem", self.language))
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("400x500")

        search_var = tk.StringVar()
        ttk.Label(dialog, text=translate("Pesquisar:", self.language)).pack(anchor="w", padx=10, pady=(10, 0))
        search_entry = ttk.Entry(dialog, textvariable=search_var)
        search_entry.pack(fill="x", padx=10, pady=(0, 10))

        canvas = tk.Canvas(dialog, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", pady=(0, 10))

        selected_state = {i: True for i in getattr(self, "_massive_selected_source_indices", set())}
        check_vars = {}

        def refresh_list():
            for widget in scroll_frame.winfo_children():
                widget.destroy()
            query = search_var.get().strip().lower()
            source_values = getattr(self, "_massive_source_list_values", [])
            check_vars.clear()
            for index, value in enumerate(source_values):
                if query and query not in str(value).lower():
                    continue
                var = tk.BooleanVar(value=index in selected_state)
                check_vars[index] = var
                cb = ttk.Checkbutton(
                    scroll_frame,
                    text=str(value),
                    variable=var,
                    command=lambda i=index, v=var: _on_check(i, v),
                )
                cb.pack(anchor="w", padx=15, pady=2)

        def _on_check(index, var):
            if var.get():
                selected_state[index] = True
            else:
                selected_state.pop(index, None)
            self._massive_selected_source_indices = set(selected_state.keys())
            self._update_selected_source_count()

        search_var.trace_add("write", lambda *args: refresh_list())

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(
            btn_frame,
            text=translate("Fechar", self.language),
            command=dialog.destroy,
        ).pack(side="right")

        refresh_list()
        dialog.wait_window()

    def _extract_categories_from_file(self, filepath):
        def worker():
            try:
                if not filepath or not os.path.isfile(filepath):
                    return
                self._last_loaded_filepath = filepath
                headers, rows = _read_csv_any_delimiter(filepath)
                if not headers:
                    return
                mapping = load_field_mapping()
                compiled_rules = get_compiled_keyword_rules()

                # Preencher Treeview de Preview Lado a Lado na main thread
                def update_trees():
                    if hasattr(self, "_preview_orig_tree") and hasattr(self, "_preview_conv_tree"):
                        orig_cols = headers[:6]
                        self._preview_orig_tree["columns"] = orig_cols
                        self._preview_orig_tree["show"] = "headings"
                        for col in orig_cols:
                            self._preview_orig_tree.heading(col, text=col)
                            self._preview_orig_tree.column(col, width=120, anchor="w")

                        for item in self._preview_orig_tree.get_children():
                            self._preview_orig_tree.delete(item)
                        for item in self._preview_conv_tree.get_children():
                            self._preview_conv_tree.delete(item)

                        conv_cols = ["Name", "Categories", "Brand", "Price", "Stock", "SKU"]
                        self._preview_conv_tree["columns"] = conv_cols
                        self._preview_conv_tree["show"] = "headings"
                        for col in conv_cols:
                            self._preview_conv_tree.heading(col, text=col)
                            self._preview_conv_tree.column(col, width=120, anchor="w")

                        for row in rows[:50]:
                            orig_values = [str(row.get(c, "")) for c in orig_cols]
                            self._preview_orig_tree.insert("", "end", values=orig_values)
                            try:
                                conv = convert_row(row, mapping, compiled_rules=compiled_rules)
                                conv_values = [str(conv.get(c, "")) for c in conv_cols]
                                self._preview_conv_tree.insert("", "end", values=conv_values)
                            except Exception:
                                pass

                        total_rows = len(rows)
                        preview_count = min(total_rows, 50)
                        if hasattr(self, "_orig_preview_title_var"):
                            self._orig_preview_title_var.set(f"📄 CSV ORIGINAL — Total lidos: {total_rows} | No preview: {preview_count}")
                        if hasattr(self, "_conv_preview_title_var"):
                            self._conv_preview_title_var.set(f"✨ PREVIEW CONVERTIDO — Total lidos: {total_rows} | No preview: {preview_count}")

                self.after(0, update_trees)

                unique_cats_set = set()
                subcat_cats_set = set()
                unique_brands_set = set()
                brand_subcat_set = set()
                for row in rows:
                    try:
                        familia = str(get_mapped_value(row, "familia_principal", mapping)).strip()
                        sub_familia = str(get_mapped_value(row, "sub_familia", mapping)).strip()
                        sub_sub_familia = str(get_mapped_value(row, "sub_sub_familia", mapping)).strip()

                        if familia:
                            unique_cats_set.add(familia)
                            subcat_cats_set.add(familia)
                        if sub_familia and familia:
                            subcat_cats_set.add(f"{familia} > {sub_familia}")
                        if sub_sub_familia and familia and sub_familia:
                            subcat_cats_set.add(f"{familia} > {sub_familia} > {sub_sub_familia}")

                        marca = str(get_mapped_value(row, "marca", mapping)).strip()
                        if not marca:
                            for k in ["marca", "Brand", "Marca", "fabricante", "Fabricante"]:
                                if k in row and str(row[k]).strip():
                                    marca = str(row[k]).strip()
                                    break
                        if marca:
                            unique_brands_set.add(marca)
                            if familia:
                                brand_subcat_set.add(f"{marca} > {familia}")
                                if sub_familia:
                                    brand_subcat_set.add(f"{marca} > {familia} > {sub_familia}")
                    except Exception:
                        continue

                def update_categories():
                    self._unique_categories = sorted(list(unique_cats_set)) if unique_cats_set else []
                    self._subcat_categories = sorted(list(subcat_cats_set)) if subcat_cats_set else []
                    self._all_categories = self._subcat_categories
                    self._unique_brands = sorted(list(unique_brands_set)) if unique_brands_set else []
                    self._brand_subcat_categories = sorted(list(brand_subcat_set)) if brand_subcat_set else []
                    self._filter_categories()
                    self._hb_filter_categories()
                    self._brand_filter_categories()
                    self._refresh_hb_adv_combos()
                    self._refresh_brand_adv_combos()
                    self._refresh_cat_adv_combos()
                    self._refresh_massive_group_combo()
                    self._filter_massive_categories()

                self.after(0, update_categories)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _filter_categories(self):
        try:
            query = getattr(self, "_cat_search_var", None)
            q = query.get().strip().lower() if query else ""

            unique_all = getattr(self, "_unique_categories", [])
            subcat_all = getattr(self, "_subcat_categories", [])

            filtered_unique = [c for c in unique_all if not q or q in c.lower()]
            filtered_subcat = [c for c in subcat_all if not q or q in c.lower()]

            if hasattr(self, '_cat_unique_title_var'):
                self._cat_unique_title_var.set(f"CATEGORIAS ÚNICAS ({len(filtered_unique)} de {len(unique_all)})" if q else f"CATEGORIAS ÚNICAS ({len(unique_all)})")
            if hasattr(self, '_cat_subcat_title_var'):
                self._cat_subcat_title_var.set(f"CATEGORIAS E SUBCATEGORIAS ({len(filtered_subcat)} de {len(subcat_all)})" if q else f"CATEGORIAS E SUBCATEGORIAS ({len(subcat_all)})")

            if hasattr(self, '_cat_unique_text'):
                self._cat_unique_text.config(state="normal")
                self._cat_unique_text.delete("1.0", "end")
                self._cat_unique_text.insert("1.0", "\n".join(filtered_unique) if filtered_unique else "(nenhuma categoria)")
                self._cat_unique_text.config(state="disabled")

            if hasattr(self, '_cat_subcat_text'):
                self._cat_subcat_text.config(state="normal")
                self._cat_subcat_text.delete("1.0", "end")
                self._cat_subcat_text.insert("1.0", "\n".join(filtered_subcat) if filtered_subcat else "(nenhuma categoria)")
                self._cat_subcat_text.config(state="disabled")
        except Exception:
            pass

    def _hb_filter_categories(self):
        try:
            query = getattr(self, "_hb_search_var", None)
            q = query.get().strip().lower() if query else ""

            unique_all = getattr(self, "_unique_categories", [])
            subcat_all = getattr(self, "_subcat_categories", [])

            filtered_unique = [c for c in unique_all if not q or q in c.lower()]
            filtered_subcat = [c for c in subcat_all if not q or q in c.lower()]

            if hasattr(self, '_hb_unique_title_var'):
                self._hb_unique_title_var.set(f"CATEGORIAS ÚNICAS ({len(filtered_unique)} de {len(unique_all)})" if q else f"CATEGORIAS ÚNICAS ({len(unique_all)})")
            if hasattr(self, '_hb_subcat_title_var'):
                self._hb_subcat_title_var.set(f"CATEGORIAS E SUBCATEGORIAS ({len(filtered_subcat)} de {len(subcat_all)})" if q else f"CATEGORIAS E SUBCATEGORIAS ({len(subcat_all)})")

            if hasattr(self, '_hb_unique_text'):
                self._hb_unique_text.config(state="normal")
                self._hb_unique_text.delete("1.0", "end")
                self._hb_unique_text.insert("1.0", "\n".join(filtered_unique) if filtered_unique else "(nenhuma categoria)")
                self._hb_unique_text.config(state="disabled")

            if hasattr(self, '_hb_subcat_text'):
                self._hb_subcat_text.config(state="normal")
                self._hb_subcat_text.delete("1.0", "end")
                self._hb_subcat_text.insert("1.0", "\n".join(filtered_subcat) if filtered_subcat else "(nenhuma categoria)")
                self._hb_subcat_text.config(state="disabled")
        except Exception:
            pass

    def _brand_filter_categories(self):
        try:
            query = getattr(self, "_brand_search_var", None)
            q = query.get().strip().lower() if query else ""

            brands_all = getattr(self, "_unique_brands", [])
            brand_subcat_all = getattr(self, "_brand_subcat_categories", [])

            filtered_brands = [c for c in brands_all if not q or q in c.lower()]
            filtered_brand_subcat = [c for c in brand_subcat_all if not q or q in c.lower()]

            if hasattr(self, '_brand_unique_title_var'):
                self._brand_unique_title_var.set(f"MARCAS ÚNICAS ({len(filtered_brands)} de {len(brands_all)})" if q else f"MARCAS ÚNICAS ({len(brands_all)})")
            if hasattr(self, '_brand_subcat_title_var'):
                self._brand_subcat_title_var.set(f"MARCAS CATEGORIAS E SUBCATEGORIAS ({len(filtered_brand_subcat)} de {len(brand_subcat_all)})" if q else f"MARCAS CATEGORIAS E SUBCATEGORIAS ({len(brand_subcat_all)})")

            if hasattr(self, '_brand_unique_text'):
                self._brand_unique_text.config(state="normal")
                self._brand_unique_text.delete("1.0", "end")
                self._brand_unique_text.insert("1.0", "\n".join(filtered_brands) if filtered_brands else "(nenhuma marca)")
                self._brand_unique_text.config(state="disabled")

            if hasattr(self, '_brand_subcat_text'):
                self._brand_subcat_text.config(state="normal")
                self._brand_subcat_text.delete("1.0", "end")
                self._brand_subcat_text.insert("1.0", "\n".join(filtered_brand_subcat) if filtered_brand_subcat else "(nenhuma marca/categoria)")
                self._brand_subcat_text.config(state="disabled")
        except Exception:
            pass

    def _reload_categories(self):
        try:
            path = getattr(self, "path_var", None)
            filepath = path.get().strip() if path else getattr(self, "_last_loaded_filepath", "")
            if not filepath:
                # Tentar detetar do campo fornecedor_var
                forn = getattr(self, "fornecedor_var", None)
                if forn:
                    filepath = forn.get().strip()
            if filepath and os.path.isfile(filepath):
                self._extract_categories_from_file(filepath)
                messagebox.showinfo(translate("Sucesso", self.language), translate("Categorias recarregadas com sucesso a partir do ficheiro!", self.language), parent=self)
            else:
                messagebox.showwarning(translate("Atenção", self.language), translate("Nenhum ficheiro CSV válido selecionado para recarregar.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _toggle_auto_classification(self):
        try:
            from category_classifier import load_rules, save_rules
            data = load_rules()
            data["enabled"] = bool(self._auto_cat_enabled_var.get())
            save_rules(data)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _add_classification_rule(self):
        try:
            from category_classifier import load_rules, save_rules
            keyword = self._rule_keyword_var.get().strip()
            category = self._rule_category_var.get().strip()
            if not keyword or not category:
                messagebox.showwarning(translate("Atenção", self.language), translate("Preencha palavra-chave e categoria destino.", self.language), parent=self)
                return
            data = load_rules()
            rules = data.get("rules", [])
            rules.append({"keywords": [keyword.lower()], "category": category, "priority": 15})
            data["rules"] = rules
            if save_rules(data):
                self._rule_keyword_var.set("")
                self._rule_category_var.set("")
                self._refresh_rules_list()
                messagebox.showinfo(translate("Guardado", self.language), translate("Regra adicionada com sucesso.", self.language), parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar a regra.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _learn_from_current_file(self):
        try:
            selected_file = self.path_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                selected_file = self.fornecedor_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                messagebox.showwarning(translate("Atenção", self.language), translate("Selecione ou arraste um ficheiro CSV primeiro.", self.language), parent=self)
                return
            headers, rows = _read_csv_any_delimiter(selected_file)
            if not rows:
                messagebox.showwarning(translate("Atenção", self.language), translate("Não foi possível ler o ficheiro ou está vazio.", self.language), parent=self)
                return
            mapping = load_field_mapping()
            count = learn_from_file_rows(rows, mapping)
            self._refresh_rules_list()
            if hasattr(self, '_category_settings_cache'):
                self._category_settings_cache = None
            messagebox.showinfo(translate("Aprendido", self.language), f"{translate('Aprendidas novas regras com base no ficheiro.', self.language)} ({{count}})", parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _preview_classification(self):
        try:
            selected_file = self.path_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                selected_file = self.fornecedor_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                messagebox.showwarning(translate("Atenção", self.language), translate("Selecione ou arraste um ficheiro CSV primeiro.", self.language), parent=self)
                return
            headers, rows = _read_csv_any_delimiter(selected_file)
            if not rows:
                messagebox.showwarning(translate("Atenção", self.language), translate("Não foi possível ler o ficheiro ou está vazio.", self.language), parent=self)
                return
            mapping = load_field_mapping()
            lines = []
            for i, row in enumerate(rows[:15]):
                try:
                    product_name = get_mapped_value(row, "design", mapping)
                    current_cat = get_mapped_value(row, "familia_principal", mapping)
                    suggested = classify_product(product_name, current_cat)
                    if suggested and not current_cat:
                        lines.append(f"{i+1}. {product_name[:40]:40} -> {suggested}")
                    elif current_cat:
                        lines.append(f"{i+1}. {product_name[:40]:40} [ATUAL: {current_cat}]")
                    else:
                        lines.append(f"{i+1}. {product_name[:40]:40} -> (sem sugestão)")
                except Exception:
                    continue
            if hasattr(self, '_preview_text'):
                self._preview_text.config(state="normal")
                self._preview_text.delete("1.0", "end")
                self._preview_text.insert("1.0", "\n".join(lines) if lines else "Sem dados para pré-visualizar")
                self._preview_text.config(state="disabled")
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _refresh_rules_list(self):
        try:
            from category_classifier import load_rules
            data = load_rules()
            rules = data.get("rules", [])
            learned = data.get("learned", [])
            lines = []
            for r in rules[-25:]:
                kws = ", ".join(r.get("keywords", []))
                lines.append(f"[REGRA] {kws} -> {r.get('category', '')}")
            for l in learned[-15:]:
                kws = ", ".join(l.get("keywords", []))
                lines.append(f"[APRENDIDO] {kws} -> {l.get('category', '')}")
            if hasattr(self, '_rules_list_text'):
                self._rules_list_text.config(state="normal")
                self._rules_list_text.delete("1.0", "end")
                self._rules_list_text.insert("1.0", "\n".join(lines) if lines else "Nenhuma regra adicional")
                self._rules_list_text.config(state="disabled")
        except Exception:
            pass

    def _save_category_settings(self):
        try:
            new_cats = self._get_listbox_values(self._cat_new_listbox)
            set_category_settings(
                new_categories=new_cats,
                cat_keywords=[""] * len(new_cats),
                apply_to_all=False,
                selected_prefix="",
                use_parent=True,
            )
        except Exception:
            # Guardar silencioso no mapeamento (sem alertas)
            pass
        self._refresh_cat_pai_combo()
        self._refresh_cat_fornecedor_combo()

    def _refresh_cat_pai_combo(self):
        """Preenche o dropdown com as categorias pai já configuradas."""
        try:
            cat_settings = get_category_settings()
            new_cats = [c.strip() for c in cat_settings.get("new_categories", []) if c.strip()]
            if hasattr(self, "_cat_pai_combo"):
                self._cat_pai_combo["values"] = new_cats
        except Exception:
            pass

    def _refresh_cat_adv_combos(self):
        try:
            if hasattr(self, "_adv_cat_combo"):
                self._adv_cat_combo["values"] = getattr(self, "_unique_categories", [])
            if hasattr(self, "_adv_subcat_combo"):
                self._adv_subcat_combo["values"] = getattr(self, "_subcat_categories", [])
        except Exception:
            pass

    def _refresh_cat_fornecedor_combo(self):
        """Preenche o dropdown de fornecedor da aba Categorias com os perfis."""
        try:
            profiles = list_profiles()
            if hasattr(self, "_cat_fornecedor_combo"):
                self._cat_fornecedor_combo["values"] = profiles
                if not self._cat_fornecedor_var.get():
                    self._cat_fornecedor_var.set(get_active_profile())
        except Exception:
            pass

    def _on_cat_fornecedor_change(self, _event=None):
        """Muda o perfil ativo quando o usuário escolhe um fornecedor na aba Categorias."""
        name = self._cat_fornecedor_var.get().strip()
        if name:
            self._set_active_profile_global(name)

    def _add_advanced_keyword_rule(self):
        """Adiciona uma regra de mapeamento avançado baseada em Categoria e Subcategoria."""
        cat_in = self._adv_cat_var.get().strip()
        subcat_in = self._adv_subcat_var.get().strip()
        parent_cat = self._cat_pai_combo.get().strip()
        if not cat_in or not parent_cat:
            messagebox.showwarning(translate("Atenção", self.language), translate("Preencha a Categoria e selecione a Categoria Pai de destino.", self.language), parent=self)
            return
        try:
            if add_keyword_rule(cat_in, subcat_in, parent_cat, priority=10):
                self._adv_cat_var.set("")
                self._adv_subcat_var.set("")
                self._refresh_adv_rules_list()
                messagebox.showinfo(translate("Guardado", self.language), translate("Regra avançada adicionada com sucesso.", self.language), parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar a regra.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _refresh_adv_rules_list(self):
        """Preenche a lista de regras avançadas (maior prioridade primeiro)."""
        try:
            rules = get_keyword_rules()
            if hasattr(self, "_adv_rules_listbox"):
                self._adv_rules_listbox.delete(0, tk.END)
                if rules:
                    for r in rules:
                        if "keywords" in r:
                            kws = ", ".join(r.get("keywords", []))
                            self._adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] [Legado] {kws} -> {r.get('parent_category', '')}")
                        else:
                            c = r.get("category", "")
                            s = r.get("subcategory", "")
                            p = r.get("parent_category", "")
                            sub_txt = f" > {s}" if s else " (Todas subcats)"
                            self._adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] Cat: {c}{sub_txt} -> {p}")
                else:
                    self._adv_rules_listbox.insert(tk.END, "(Nenhuma regra avançada configurada)")
        except Exception:
            pass

    def _remove_advanced_keyword_rule(self):
        """Remove a regra selecionada na lista de regras avançadas (aba Categorias)."""
        rules = get_keyword_rules()
        if not rules:
            messagebox.showinfo(translate("Informação", self.language), translate("Não há regras para remover.", self.language), parent=self)
            return
        sel = self._adv_rules_listbox.curselection()
        if sel:
            index = sel[0]
            if index < len(rules):
                r = rules[index]
                if "keywords" in r:
                    desc = ", ".join(r.get("keywords", []))
                else:
                    desc = f"Cat: {r.get('category','')}" + (f" > {r.get('subcategory','')}" if r.get('subcategory','') else "")
                cat = r.get("parent_category", "")
                if messagebox.askyesno("Remover Regra", f"Remover a regra:\n'{desc} → {cat}'?", parent=self):
                    remove_keyword_rule(index)
                    self._refresh_adv_rules_list()
            return
        messagebox.showwarning(translate("Atenção", self.language), translate("Selecione uma regra na lista para remover.", self.language), parent=self)

    def _build_tab_destaques(self):
        """Constrói a aba 'Destaques'."""
        frm = ttk.Frame(self.tab_destaques, padding=6)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Mapeamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

        hb_header_row = ttk.Frame(frm)
        hb_header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(hb_header_row, text="Crie categorias pai para Destaques", font=("Segoe UI", 9), foreground=GRAY_600).pack(side="left")
        ttk.Label(hb_header_row, text="  Fornecedor:", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self._hb_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._hb_fornecedor_combo = ttk.Combobox(hb_header_row, textvariable=self._hb_fornecedor_var, state="readonly", width=24)
        self._hb_fornecedor_combo.pack(side="left")
        self._hb_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_hb_fornecedor_change)
        self._refresh_hb_fornecedor_combo()

        hb_settings = get_highlights_brands_settings()
        self._hb_new_listbox = self._build_dynamic_list(
            parent=frm,
            label="Categorias Pai de Destaques",
            values=hb_settings.get("new_categories", []),
            add_command=self._add_hb_new_item,
            remove_command=self._remove_hb_new_item,
        )

        self._hb_use_parent_var = tk.BooleanVar(value=True)

        ttk.Button(frm, text="Guardar todas as configurações de Destaques", command=self._save_highlights_brands_settings, width=45).pack(anchor="w", pady=(4, 0))

        # ---- Mapeamento Avançado (regras por Categoria e Subcategoria) ----
        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))
        ttk.Label(frm, text="Mapeamento Avançado — regras por Categoria e Subcategoria", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(frm, text="Associe automaticamente produtos a uma categoria pai de destaques com base na Categoria e Subcategoria do fornecedor.", font=("Segoe UI", 8), foreground=GRAY_600).pack(anchor="w", pady=(0, 2))
        hb_adv_row = ttk.Frame(frm)
        hb_adv_row.pack(fill="x", pady=2)
        ttk.Label(hb_adv_row, text="Cat.:").pack(side="left", padx=(0, 2))
        self._hb_adv_cat_var = tk.StringVar()
        self._hb_adv_cat_combo = ttk.Combobox(hb_adv_row, textvariable=self._hb_adv_cat_var)
        self._hb_adv_cat_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(hb_adv_row, text="Subcat.:").pack(side="left", padx=(4, 2))
        self._hb_adv_subcat_var = tk.StringVar()
        self._hb_adv_subcat_combo = ttk.Combobox(hb_adv_row, textvariable=self._hb_adv_subcat_var)
        self._hb_adv_subcat_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(hb_adv_row, text="Pai:").pack(side="left", padx=(4, 2))
        self._hb_pai_combo = ttk.Combobox(hb_adv_row, state="readonly")
        self._hb_pai_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(hb_adv_row, text="Adicionar Regra", command=self._hb_add_advanced_keyword_rule, width=14).pack(side="left", padx=(0, 4))
        ttk.Button(hb_adv_row, text="Remover Regra", command=self._hb_remove_advanced_keyword_rule, width=14).pack(side="left")
        self._refresh_hb_pai_combo()

        ttk.Label(frm, text="Regras configuradas (mais recente = maior prioridade) — selecione para remover:", font=("Segoe UI", 9), foreground=GRAY_600).pack(anchor="w", pady=(6, 2))
        hb_adv_frame = ttk.Frame(frm)
        hb_adv_frame.pack(fill="both", expand=True)
        self._hb_adv_rules_listbox = tk.Listbox(hb_adv_frame, height=6, relief="sunken", bg=GRAY_100, font=("Consolas", 8), selectmode="single")
        hb_adv_scroll = ttk.Scrollbar(hb_adv_frame, orient="vertical", command=self._hb_adv_rules_listbox.yview)
        self._hb_adv_rules_listbox.configure(yscrollcommand=hb_adv_scroll.set)
        self._hb_adv_rules_listbox.pack(side="left", fill="both", expand=True)
        hb_adv_scroll.pack(side="right", fill="y")
        self._hb_adv_rules_listbox.bind("<Double-Button-1>", lambda e: self._hb_remove_advanced_keyword_rule())
        self._refresh_hb_adv_rules_list()

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))

        # Listagem em duas colunas: Categorias Únicas e Categorias e Subcategorias
        hb_lists_container = ttk.Frame(frm)
        hb_lists_container.pack(fill="both", expand=True, pady=(2, 0))
        hb_lists_container.columnconfigure(0, weight=1)
        hb_lists_container.columnconfigure(1, weight=1)
        hb_lists_container.rowconfigure(0, weight=1)

        # Coluna 1: Categorias Únicas
        hb_col1_frame = ttk.Frame(hb_lists_container)
        hb_col1_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._hb_unique_title_var = tk.StringVar(value="CATEGORIAS ÚNICAS (0)")
        ttk.Label(hb_col1_frame, textvariable=self._hb_unique_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        hb_c1_box = ttk.Frame(hb_col1_frame)
        hb_c1_box.pack(fill="both", expand=True)
        self._hb_unique_text = tk.Text(hb_c1_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        hb_c1_scroll = ttk.Scrollbar(hb_c1_box, orient="vertical", command=self._hb_unique_text.yview)
        self._hb_unique_text.configure(yscrollcommand=hb_c1_scroll.set)
        self._hb_unique_text.pack(side="left", fill="both", expand=True)
        hb_c1_scroll.pack(side="right", fill="y")
        self._hb_unique_text.config(state="disabled")

        # Coluna 2: Categorias e Subcategorias
        hb_col2_frame = ttk.Frame(hb_lists_container)
        hb_col2_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._hb_subcat_title_var = tk.StringVar(value="CATEGORIAS E SUBCATEGORIAS (0)")
        ttk.Label(hb_col2_frame, textvariable=self._hb_subcat_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        hb_c2_box = ttk.Frame(hb_col2_frame)
        hb_c2_box.pack(fill="both", expand=True)
        self._hb_subcat_text = tk.Text(hb_c2_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        hb_c2_scroll = ttk.Scrollbar(hb_c2_box, orient="vertical", command=self._hb_subcat_text.yview)
        self._hb_subcat_text.configure(yscrollcommand=hb_c2_scroll.set)
        self._hb_subcat_text.pack(side="left", fill="both", expand=True)
        hb_c2_scroll.pack(side="right", fill="y")
        self._hb_subcat_text.config(state="disabled")

        hb_search_row = ttk.Frame(frm)
        hb_search_row.pack(fill="x", pady=(6, 4))
        ttk.Label(hb_search_row, text="🔍 Pesquisar:").pack(side="left", padx=(0, 4))
        self._hb_search_var = tk.StringVar()
        self._hb_search_var.trace_add("write", lambda *args: self._hb_filter_categories())
        ttk.Entry(hb_search_row, textvariable=self._hb_search_var, width=28).pack(side="left", padx=(0, 8))
        ttk.Button(hb_search_row, text="🔄 Recarregar", command=self._reload_categories, width=14).pack(side="left")

    def _build_tab_marcas(self):
        """Constrói a aba 'Marcas' com mapeamento avançado por Marca, Categoria e Subcategoria."""
        frm = ttk.Frame(self.tab_marcas, padding=6)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Mapeamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

        brand_header_row = ttk.Frame(frm)
        brand_header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(brand_header_row, text="Crie categorias pai para agrupar as marcas e produtos", font=("Segoe UI", 9), foreground=GRAY_600).pack(side="left")
        ttk.Label(brand_header_row, text="  Fornecedor:", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self._brand_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._brand_fornecedor_combo = ttk.Combobox(brand_header_row, textvariable=self._brand_fornecedor_var, state="readonly", width=24)
        self._brand_fornecedor_combo.pack(side="left")
        self._brand_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_brand_fornecedor_change)
        self._refresh_brand_fornecedor_combo()

        brand_settings = get_highlights_brands_settings()
        self._brand_new_listbox = self._build_dynamic_list(
            parent=frm,
            label="Categorias Pai de Marcas",
            values=brand_settings.get("new_categories", []),
            add_command=self._add_brand_new_item,
            remove_command=self._remove_brand_new_item,
        )

        ttk.Button(frm, text="Guardar todas as configurações de Marcas", command=self._save_brand_settings, width=45).pack(anchor="w", pady=(4, 0))

        # ---- Mapeamento Avançado (regras por Marca, Categoria e Subcategoria) ----
        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))
        ttk.Label(frm, text="Mapeamento Avançado — Regras por Marca de produto.", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(frm, text="Associe automaticamente produtos a uma categoria pai com base na Marca, Categoria e Subcategoria originais do fornecedor.", font=("Segoe UI", 8), foreground=GRAY_600).pack(anchor="w", pady=(0, 2))

        brand_adv_row = ttk.Frame(frm)
        brand_adv_row.pack(fill="x", pady=2)
        ttk.Label(brand_adv_row, text="Marca:").pack(side="left", padx=(0, 2))
        self._brand_adv_marca_var = tk.StringVar()
        self._brand_adv_marca_combo = ttk.Combobox(brand_adv_row, textvariable=self._brand_adv_marca_var)
        self._brand_adv_marca_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(brand_adv_row, text="Cat.:").pack(side="left", padx=(4, 2))
        self._brand_adv_cat_var = tk.StringVar()
        self._brand_adv_cat_combo = ttk.Combobox(brand_adv_row, textvariable=self._brand_adv_cat_var)
        self._brand_adv_cat_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(brand_adv_row, text="Subcat.:").pack(side="left", padx=(4, 2))
        self._brand_adv_subcat_var = tk.StringVar()
        self._brand_adv_subcat_combo = ttk.Combobox(brand_adv_row, textvariable=self._brand_adv_subcat_var)
        self._brand_adv_subcat_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(brand_adv_row, text="Pai:").pack(side="left", padx=(4, 2))
        self._brand_pai_combo = ttk.Combobox(brand_adv_row, state="readonly")
        self._brand_pai_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(brand_adv_row, text="Adicionar Regra", command=self._brand_add_advanced_rule, width=14).pack(side="left", padx=(0, 4))
        ttk.Button(brand_adv_row, text="Remover Regra", command=self._brand_remove_advanced_rule, width=14).pack(side="left")
        self._refresh_brand_pai_combo()

        ttk.Label(frm, text="Regras configuradas (mais recente = maior prioridade) — selecione para remover:", font=("Segoe UI", 9), foreground=GRAY_600).pack(anchor="w", pady=(6, 2))
        brand_adv_frame = ttk.Frame(frm)
        brand_adv_frame.pack(fill="both", expand=True)
        self._brand_adv_rules_listbox = tk.Listbox(brand_adv_frame, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), selectmode="single")
        brand_adv_scroll = ttk.Scrollbar(brand_adv_frame, orient="vertical", command=self._brand_adv_rules_listbox.yview)
        self._brand_adv_rules_listbox.configure(yscrollcommand=brand_adv_scroll.set)
        self._brand_adv_rules_listbox.pack(side="left", fill="both", expand=True)
        brand_adv_scroll.pack(side="right", fill="y")
        self._brand_adv_rules_listbox.bind("<Double-Button-1>", lambda e: self._brand_remove_advanced_rule())
        self._refresh_brand_adv_rules_list()

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))

        # Listagem em duas colunas: Marcas únicas e Marcas Categorias/subcategorias
        brand_lists_container = ttk.Frame(frm)
        brand_lists_container.pack(fill="both", expand=True, pady=(2, 0))
        brand_lists_container.columnconfigure(0, weight=1)
        brand_lists_container.columnconfigure(1, weight=1)
        brand_lists_container.rowconfigure(0, weight=1)

        # Coluna 1: Marcas únicas
        brand_col1_frame = ttk.Frame(brand_lists_container)
        brand_col1_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._brand_unique_title_var = tk.StringVar(value="MARCAS ÚNICAS (0)")
        ttk.Label(brand_col1_frame, textvariable=self._brand_unique_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        bc1_box = ttk.Frame(brand_col1_frame)
        bc1_box.pack(fill="both", expand=True)
        self._brand_unique_text = tk.Text(bc1_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        bc1_scroll = ttk.Scrollbar(bc1_box, orient="vertical", command=self._brand_unique_text.yview)
        self._brand_unique_text.configure(yscrollcommand=bc1_scroll.set)
        self._brand_unique_text.pack(side="left", fill="both", expand=True)
        bc1_scroll.pack(side="right", fill="y")
        self._brand_unique_text.config(state="disabled")

        # Coluna 2: Marcas Categorias/subcategorias
        brand_col2_frame = ttk.Frame(brand_lists_container)
        brand_col2_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._brand_subcat_title_var = tk.StringVar(value="MARCAS CATEGORIAS E SUBCATEGORIAS (0)")
        ttk.Label(brand_col2_frame, textvariable=self._brand_subcat_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        bc2_box = ttk.Frame(brand_col2_frame)
        bc2_box.pack(fill="both", expand=True)
        self._brand_subcat_text = tk.Text(bc2_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        bc2_scroll = ttk.Scrollbar(bc2_box, orient="vertical", command=self._brand_subcat_text.yview)
        self._brand_subcat_text.configure(yscrollcommand=bc2_scroll.set)
        self._brand_subcat_text.pack(side="left", fill="both", expand=True)
        bc2_scroll.pack(side="right", fill="y")
        self._brand_subcat_text.config(state="disabled")

        brand_search_row = ttk.Frame(frm)
        brand_search_row.pack(fill="x", pady=(6, 4))
        ttk.Label(brand_search_row, text="🔍 Pesquisar:").pack(side="left", padx=(0, 4))
        self._brand_search_var = tk.StringVar()
        self._brand_search_var.trace_add("write", lambda *args: self._brand_filter_categories())
        ttk.Entry(brand_search_row, textvariable=self._brand_search_var, width=28).pack(side="left", padx=(0, 8))
        ttk.Button(brand_search_row, text="🔄 Recarregar", command=self._reload_categories, width=12).pack(side="left")

    def _save_highlights_brands_settings(self):
        try:
            new_cats = self._get_listbox_values(self._hb_new_listbox)
            set_highlights_brands_settings(
                new_categories=new_cats,
                apply_to_all=False,
                selected_prefix="",
                use_parent=True,
            )
        except Exception:
            pass
        self._refresh_hb_pai_combo()

    def _add_hb_new_item(self):
        """Adiciona um item à lista dinâmica de categorias pai de destaques."""
        if not hasattr(self, "_hb_new_listbox"):
            return
        value = self._hb_new_listbox._entry_var.get().strip()
        if not value:
            return
        self._hb_new_listbox._listbox.insert(tk.END, value)
        self._hb_new_listbox._entry_var.set("")
        self._save_highlights_brands_settings()

    def _remove_hb_new_item(self, listbox):
        """Remove o item selecionado da lista dinâmica de categorias pai de destaques."""
        selection = listbox.curselection()
        if selection:
            listbox.delete(selection[0])
            self._save_highlights_brands_settings()

    def _refresh_hb_pai_combo(self):
        try:
            hb_settings = get_highlights_brands_settings()
            new_cats = [c.strip() for c in hb_settings.get("new_categories", []) if c.strip()]
            if hasattr(self, "_hb_pai_combo"):
                self._hb_pai_combo["values"] = new_cats
        except Exception:
            pass

    def _refresh_hb_adv_combos(self):
        try:
            if hasattr(self, "_hb_adv_cat_combo"):
                self._hb_adv_cat_combo["values"] = getattr(self, "_unique_categories", [])
            if hasattr(self, "_hb_adv_subcat_combo"):
                self._hb_adv_subcat_combo["values"] = getattr(self, "_subcat_categories", [])
        except Exception:
            pass

    def _refresh_hb_fornecedor_combo(self):
        try:
            profiles = list_profiles()
            if hasattr(self, "_hb_fornecedor_combo"):
                self._hb_fornecedor_combo["values"] = profiles
                active = get_active_profile()
                if active not in profiles:
                    active = profiles[0] if profiles else ""
                self._hb_fornecedor_var.set(active)
        except Exception:
            pass

    def _on_hb_fornecedor_change(self, _event=None):
        name = self._hb_fornecedor_var.get().strip()
        if name:
            self._set_active_profile_global(name)

    def _hb_add_advanced_keyword_rule(self):
        cat_in = self._hb_adv_cat_var.get().strip()
        subcat_in = self._hb_adv_subcat_var.get().strip()
        parent_cat = self._hb_pai_combo.get().strip()
        if not cat_in or not parent_cat:
            messagebox.showwarning(translate("Atenção", self.language), translate("Preencha a Categoria e selecione a Categoria Pai de destino.", self.language), parent=self)
            return
        try:
            if add_highlights_brands_keyword_rule(cat_in, subcat_in, parent_cat, priority=10):
                self._hb_adv_cat_var.set("")
                self._hb_adv_subcat_var.set("")
                self._refresh_hb_adv_rules_list()
                messagebox.showinfo(translate("Guardado", self.language), translate("Regra avançada adicionada com sucesso.", self.language), parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar a regra.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _refresh_hb_adv_rules_list(self):
        try:
            rules = get_highlights_brands_keyword_rules()
            if hasattr(self, "_hb_adv_rules_listbox"):
                self._hb_adv_rules_listbox.delete(0, tk.END)
                if rules:
                    for r in rules:
                        if "keywords" in r:
                            kws = ", ".join(r.get("keywords", []))
                            self._hb_adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] [Legado] {kws} -> {r.get('parent_category', '')}")
                        else:
                            c = r.get("category", "")
                            s = r.get("subcategory", "")
                            p = r.get("parent_category", "")
                            sub_txt = f" > {s}" if s else " (Todas subcats)"
                            self._hb_adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] Cat: {c}{sub_txt} -> {p}")
                else:
                    self._hb_adv_rules_listbox.insert(tk.END, "(Nenhuma regra avançada configurada)")
        except Exception:
            pass

    def _hb_remove_advanced_keyword_rule(self):
        rules = get_highlights_brands_keyword_rules()
        if not rules:
            messagebox.showinfo(translate("Informação", self.language), translate("Não há regras para remover.", self.language), parent=self)
            return
        sel = self._hb_adv_rules_listbox.curselection()
        if sel:
            index = sel[0]
            if index < len(rules):
                r = rules[index]
                if "keywords" in r:
                    desc = ", ".join(r.get("keywords", []))
                else:
                    desc = f"Cat: {r.get('category','')}" + (f" > {r.get('subcategory','')}" if r.get('subcategory','') else "")
                cat = r.get("parent_category", "")
                if messagebox.askyesno("Remover Regra", f"Remover a regra:\n'{desc} → {cat}'?", parent=self):
                    remove_highlights_brands_keyword_rule(index)
                    self._refresh_hb_adv_rules_list()
            return
        messagebox.showwarning(translate("Atenção", self.language), translate("Selecione uma regra na lista para remover.", self.language), parent=self)

    def _refresh_brand_pai_combo(self):
        try:
            hb_settings = get_highlights_brands_settings()
            new_cats = [c.strip() for c in hb_settings.get("new_categories", []) if c.strip()]
            if hasattr(self, "_brand_pai_combo"):
                self._brand_pai_combo["values"] = new_cats
        except Exception:
            pass

    def _refresh_brand_adv_combos(self):
        try:
            if hasattr(self, "_brand_adv_marca_combo"):
                self._brand_adv_marca_combo["values"] = getattr(self, "_unique_brands", [])
            if hasattr(self, "_brand_adv_cat_combo"):
                self._brand_adv_cat_combo["values"] = getattr(self, "_unique_categories", [])
            if hasattr(self, "_brand_adv_subcat_combo"):
                self._brand_adv_subcat_combo["values"] = getattr(self, "_subcat_categories", [])
        except Exception:
            pass

    def _refresh_brand_fornecedor_combo(self):
        try:
            profiles = list_profiles()
            if hasattr(self, "_brand_fornecedor_combo"):
                self._brand_fornecedor_combo["values"] = profiles
                active = get_active_profile()
                if active not in profiles:
                    active = profiles[0] if profiles else ""
                self._brand_fornecedor_var.set(active)
        except Exception:
            pass

    def _on_brand_fornecedor_change(self, _event=None):
        name = self._brand_fornecedor_var.get().strip()
        if name:
            self._set_active_profile_global(name)

    def _save_brand_settings(self):
        try:
            new_cats = self._get_listbox_values(self._brand_new_listbox)
            set_highlights_brands_settings(
                new_categories=new_cats,
                apply_to_all=False,
                selected_prefix="",
                use_parent=True,
            )
        except Exception:
            pass
        self._refresh_brand_pai_combo()

    def _add_brand_new_item(self):
        """Adiciona um item à lista dinâmica de categorias pai de marcas."""
        if not hasattr(self, "_brand_new_listbox"):
            return
        value = self._brand_new_listbox._entry_var.get().strip()
        if not value:
            return
        self._brand_new_listbox._listbox.insert(tk.END, value)
        self._brand_new_listbox._entry_var.set("")
        self._save_brand_settings()

    def _remove_brand_new_item(self, listbox):
        """Remove o item selecionado da lista dinâmica de categorias pai de marcas."""
        selection = listbox.curselection()
        if selection:
            listbox.delete(selection[0])
            self._save_brand_settings()

    def _brand_add_advanced_rule(self):
        marca = self._brand_adv_marca_var.get().strip()
        cat = self._brand_adv_cat_var.get().strip()
        subcat = self._brand_adv_subcat_var.get().strip()
        parent_cat = self._brand_pai_combo.get().strip()
        if not marca or not parent_cat:
            messagebox.showwarning(translate("Atenção", self.language), translate("Preencha a Marca e selecione a Categoria Pai de destino.", self.language), parent=self)
            return
        try:
            if add_brands_keyword_rule(marca, cat, subcat, parent_cat, priority=10):
                self._brand_adv_marca_var.set("")
                self._brand_adv_cat_var.set("")
                self._brand_adv_subcat_var.set("")
                self._refresh_brand_adv_rules_list()
                messagebox.showinfo(translate("Guardado", self.language), translate("Regra de marca avançada adicionada com sucesso.", self.language), parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar a regra de marca.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _refresh_brand_adv_rules_list(self):
        try:
            rules = get_brands_keyword_rules()
            if hasattr(self, "_brand_adv_rules_listbox"):
                self._brand_adv_rules_listbox.delete(0, tk.END)
                if rules:
                    for r in rules:
                        m = r.get("marca", "")
                        c = r.get("category", "")
                        s = r.get("subcategory", "")
                        p = r.get("parent_category", "")
                        m_str = f"Marca: {m}" if m else "Marca: (Qualquer)"
                        c_str = f"Cat: {c}" if c else "Cat: (Todas)"
                        s_str = f"Subcat: {s}" if s else "Subcat: (Todas)"
                        self._brand_adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] {m_str} | {c_str} | {s_str} -> {p}")
                else:
                    self._brand_adv_rules_listbox.insert(tk.END, "(Nenhuma regra de marca avançada configurada)")
        except Exception:
            pass

    def _brand_remove_advanced_rule(self):
        rules = get_brands_keyword_rules()
        if not rules:
            messagebox.showinfo(translate("Informação", self.language), translate("Não há regras de marca para remover.", self.language), parent=self)
            return
        sel = self._brand_adv_rules_listbox.curselection()
        if sel:
            index = sel[0]
            if index < len(rules):
                r = rules[index]
                desc = f"Marca: {r.get('marca','')}" + (f", Cat: {r.get('category','')}" if r.get('category','') else "") + (f" > {r.get('subcategory','')}" if r.get('subcategory','') else "")
                cat = r.get("parent_category", "")
                if messagebox.askyesno("Remover Regra", f"Remover a regra de marca:\n'{desc} → {cat}'?", parent=self):
                    remove_brands_keyword_rule(index)
                    self._refresh_brand_adv_rules_list()
            return
        messagebox.showwarning(translate("Atenção", self.language), translate("Selecione uma regra na lista para remover.", self.language), parent=self)

    def _build_tab_sku_prefix(self):
        """Constrói a aba 'Prefixo SKU' — prefixo de 3 letras + traço por fornecedor."""
        frm = ttk.Frame(self.tab_sku_prefix, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Prefixo SKU", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            frm,
            text=(
                "O prefixo SKU é usado para certificar quem é o fornecedor dos produtos numa venda, "
                "quando há mais de 1 fornecedor e a encomenda pode ter produtos de vários fornecedores.\n\n"
                "Formato: 3 letras e um traço (ex: VIP-). O prefixo será colocado antes do SKU dos produtos.\n"
                "Cada fornecedor pode ter o seu próprio prefixo."
            ),
            font=("Segoe UI", 9),
            foreground=GRAY_600,
            justify="left",
            wraplength=700,
        ).pack(anchor="w", pady=(0, 12))

        # Linha: Prefixo SKU | Seletor de Fornecedor | Salvar
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=4)
        self._sku_prefix_var = tk.StringVar()
        ttk.Label(row, text="Prefixo SKU:").pack(side="left")
        self._sku_prefix_entry = ttk.Entry(row, textvariable=self._sku_prefix_var, width=12)
        self._sku_prefix_entry.pack(side="left", padx=(6, 12))

        ttk.Label(row, text="Fornecedor:").pack(side="left")
        self._sku_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._sku_fornecedor_combo = ttk.Combobox(row, textvariable=self._sku_fornecedor_var, state="readonly", width=24)
        self._sku_fornecedor_combo.pack(side="left", padx=(6, 12))
        self._sku_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_sku_fornecedor_change)
        self._refresh_sku_fornecedor_combo()

        ttk.Button(row, text="Salvar", command=self._save_sku_prefix, width=10).pack(side="left", padx=(4, 0))

        ttk.Label(
            frm,
            text="Exemplo: SKU '12345' com prefixo 'VIP-' fica 'VIP-12345'.",
            font=("Segoe UI", 8),
            foreground=GRAY_600,
        ).pack(anchor="w", pady=(8, 0))

    def _refresh_sku_fornecedor_combo(self):
        """Preenche o dropdown de fornecedor da aba Prefixo SKU e carrega o prefixo salvo."""
        try:
            profiles = list_profiles()
            if hasattr(self, "_sku_fornecedor_combo"):
                self._sku_fornecedor_combo["values"] = profiles
                active = get_active_profile()
                if active not in profiles:
                    active = profiles[0] if profiles else ""
                self._sku_fornecedor_var.set(active)
                # Carregar o prefixo salvo do fornecedor ativo
                if active and hasattr(self, "_sku_prefix_var"):
                    self._sku_prefix_var.set(get_sku_prefix(active))
        except Exception:
            pass

    def _on_sku_fornecedor_change(self, _event=None):
        """Quando muda o fornecedor na aba Prefixo SKU, recarrega o prefixo desse fornecedor."""
        name = self._sku_fornecedor_var.get().strip()
        if name:
            self._set_active_profile_global(name)

    def _save_sku_prefix(self):
        """Guarda o prefixo SKU para o fornecedor selecionado."""
        prefix = self._sku_prefix_var.get().strip()
        name = self._sku_fornecedor_var.get().strip()
        if not name:
            messagebox.showwarning(translate("Atenção", self.language), translate("Selecione um fornecedor.", self.language), parent=self)
            return
        if not prefix:
            set_sku_prefix("", name)
            messagebox.showinfo(translate("Guardado", self.language), f"{translate('Prefixo SKU removido para', self.language)} '{name}'.", parent=self)
            return
        # Valida: 3 letras + traço (ex: VIP-)
        import re
        if not re.match(r"^[A-Za-z]{3}-$", prefix):
            messagebox.showwarning(translate("Atenção", self.language), translate("O prefixo deve ter 3 letras seguidas de um traço (ex: VIP-).", self.language), parent=self)
            return
        prefix = prefix.upper()
        self._sku_prefix_var.set(prefix)
        if set_sku_prefix(prefix, name):
            messagebox.showinfo(translate("Guardado", self.language), f"{translate('Prefixo SKU guardado para', self.language)} '{name}': '{prefix}'.", parent=self)
        else:
            messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar o prefixo SKU.", self.language), parent=self)

    def _build_tab_highlights_brands(self):
        """Constrói a aba 'Destaques e Marcas' — idêntica à aba Categorias."""
        frm = ttk.Frame(self.tab_highlights_brands, padding=6)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Mapeamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

        # Linha de instrução com seletor de fornecedor ao lado (igual ao separador Categorias)
        hb_header_row = ttk.Frame(frm)
        hb_header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(hb_header_row, text="Crie categorias pai para agrupar as categorias do fornecedor", font=("Segoe UI", 9), foreground=GRAY_600).pack(side="left")
        ttk.Label(hb_header_row, text="  Fornecedor:", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self._hb_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._hb_fornecedor_combo = ttk.Combobox(hb_header_row, textvariable=self._hb_fornecedor_var, state="readonly", width=24)
        self._hb_fornecedor_combo.pack(side="left")
        self._hb_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_hb_fornecedor_change)
        self._refresh_hb_fornecedor_combo()

        hb_settings = get_highlights_brands_settings()
        self._hb_new_listbox = self._build_dynamic_list(
            parent=frm,
            label="Categorias Pai de Destaques e Marcas",
            values=hb_settings.get("new_categories", []),
            add_command=self._add_hb_new_item,
            remove_command=self._remove_hb_new_item,
        )

        # Manter hierarquia original está sempre activo (não é configurável pelo utilizador)
        self._hb_use_parent_var = tk.BooleanVar(value=True)

        ttk.Button(frm, text="Guardar todas as configurações de Destaques e Marcas", command=self._save_highlights_brands_settings, width=45).pack(anchor="w", pady=(4, 0))

        # ---- Mapeamento Avançado (regras por Categoria e Subcategoria) ----
        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))
        ttk.Label(frm, text="Mapeamento Avançado — regras por Categoria e Subcategoria", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(frm, text="Associe automaticamente produtos a uma categoria pai de destaques/marcas com base na Categoria e Subcategoria do fornecedor.", font=("Segoe UI", 8), foreground=GRAY_600).pack(anchor="w", pady=(0, 2))
        hb_adv_row = ttk.Frame(frm)
        hb_adv_row.pack(fill="x", pady=2)
        ttk.Label(hb_adv_row, text="Cat.:").pack(side="left", padx=(0, 2))
        self._hb_adv_cat_var = tk.StringVar()
        ttk.Entry(hb_adv_row, textvariable=self._hb_adv_cat_var, width=18).pack(side="left", padx=(0, 4))
        ttk.Label(hb_adv_row, text="Subcat.:").pack(side="left", padx=(4, 2))
        self._hb_adv_subcat_var = tk.StringVar()
        ttk.Entry(hb_adv_row, textvariable=self._hb_adv_subcat_var, width=18).pack(side="left", padx=(0, 4))
        ttk.Label(hb_adv_row, text="Pai:").pack(side="left", padx=(4, 2))
        self._hb_pai_combo = ttk.Combobox(hb_adv_row, state="readonly", width=22)
        self._hb_pai_combo.pack(side="left", padx=(0, 4))
        ttk.Button(hb_adv_row, text="Adicionar Regra", command=self._hb_add_advanced_keyword_rule, width=14).pack(side="left", padx=(0, 4))
        ttk.Button(hb_adv_row, text="Remover Regra", command=self._hb_remove_advanced_keyword_rule, width=14).pack(side="left")
        self._refresh_hb_pai_combo()

        ttk.Label(frm, text="Regras configuradas (mais recente = maior prioridade) — selecione para remover:", font=("Segoe UI", 9), foreground=GRAY_600).pack(anchor="w", pady=(6, 2))
        hb_adv_frame = ttk.Frame(frm)
        hb_adv_frame.pack(fill="both", expand=True)
        self._hb_adv_rules_listbox = tk.Listbox(hb_adv_frame, height=6, relief="sunken", bg=GRAY_100, font=("Consolas", 8), selectmode="single")
        hb_adv_scroll = ttk.Scrollbar(hb_adv_frame, orient="vertical", command=self._hb_adv_rules_listbox.yview)
        self._hb_adv_rules_listbox.configure(yscrollcommand=hb_adv_scroll.set)
        self._hb_adv_rules_listbox.pack(side="left", fill="both", expand=True)
        hb_adv_scroll.pack(side="right", fill="y")
        self._hb_adv_rules_listbox.bind("<Double-Button-1>", lambda e: self._hb_remove_advanced_keyword_rule())
        self._refresh_hb_adv_rules_list()

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 6))

        # Listagem em duas colunas: Categorias Únicas e Categorias e Subcategorias
        hb_lists_container = ttk.Frame(frm)
        hb_lists_container.pack(fill="both", expand=True, pady=(2, 0))
        hb_lists_container.columnconfigure(0, weight=1)
        hb_lists_container.columnconfigure(1, weight=1)
        hb_lists_container.rowconfigure(0, weight=1)

        # Coluna 1: Categorias Únicas
        hb_col1_frame = ttk.Frame(hb_lists_container)
        hb_col1_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._hb_unique_title_var = tk.StringVar(value="CATEGORIAS ÚNICAS (0)")
        ttk.Label(hb_col1_frame, textvariable=self._hb_unique_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        hb_c1_box = ttk.Frame(hb_col1_frame)
        hb_c1_box.pack(fill="both", expand=True)
        self._hb_unique_text = tk.Text(hb_c1_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        hb_c1_scroll = ttk.Scrollbar(hb_c1_box, orient="vertical", command=self._hb_unique_text.yview)
        self._hb_unique_text.configure(yscrollcommand=hb_c1_scroll.set)
        self._hb_unique_text.pack(side="left", fill="both", expand=True)
        hb_c1_scroll.pack(side="right", fill="y")
        self._hb_unique_text.config(state="disabled")

        # Coluna 2: Categorias e Subcategorias
        hb_col2_frame = ttk.Frame(hb_lists_container)
        hb_col2_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._hb_subcat_title_var = tk.StringVar(value="CATEGORIAS E SUBCATEGORIAS (0)")
        ttk.Label(hb_col2_frame, textvariable=self._hb_subcat_title_var, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))

        hb_c2_box = ttk.Frame(hb_col2_frame)
        hb_c2_box.pack(fill="both", expand=True)
        self._hb_subcat_text = tk.Text(hb_c2_box, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        hb_c2_scroll = ttk.Scrollbar(hb_c2_box, orient="vertical", command=self._hb_subcat_text.yview)
        self._hb_subcat_text.configure(yscrollcommand=hb_c2_scroll.set)
        self._hb_subcat_text.pack(side="left", fill="both", expand=True)
        hb_c2_scroll.pack(side="right", fill="y")
        self._hb_subcat_text.config(state="disabled")

        hb_search_row = ttk.Frame(frm)
        hb_search_row.pack(fill="x", pady=(6, 4))
        ttk.Label(hb_search_row, text="🔍 Pesquisar:").pack(side="left", padx=(0, 4))
        self._hb_search_var = tk.StringVar()
        self._hb_search_var.trace_add("write", lambda *args: self._hb_filter_categories())
        ttk.Entry(hb_search_row, textvariable=self._hb_search_var, width=28).pack(side="left", padx=(0, 8))
        ttk.Button(hb_search_row, text="🔄 Recarregar", command=self._reload_categories, width=14).pack(side="left")

    def _save_highlights_brands_settings(self):
        try:
            new_cats = self._get_listbox_values(self._hb_new_listbox)
            set_highlights_brands_settings(
                new_categories=new_cats,
                apply_to_all=False,
                selected_prefix="",
                use_parent=True,
            )
        except Exception:
            # Guardar silencioso no mapeamento (sem alertas)
            pass
        self._refresh_hb_pai_combo()

    def _refresh_hb_pai_combo(self):
        """Preenche o dropdown com as categorias pai já configuradas."""
        try:
            hb_settings = get_highlights_brands_settings()
            new_cats = [c.strip() for c in hb_settings.get("new_categories", []) if c.strip()]
            if hasattr(self, "_hb_pai_combo"):
                self._hb_pai_combo["values"] = new_cats
        except Exception:
            pass

    def _refresh_hb_fornecedor_combo(self):
        """Preenche o dropdown de fornecedor da aba Destaques e Marcas."""
        try:
            profiles = list_profiles()
            if hasattr(self, "_hb_fornecedor_combo"):
                self._hb_fornecedor_combo["values"] = profiles
                active = get_active_profile()
                if active not in profiles:
                    active = profiles[0] if profiles else ""
                self._hb_fornecedor_var.set(active)
        except Exception:
            pass

    def _on_hb_fornecedor_change(self, _event=None):
        """Muda o perfil ativo quando o usuário escolhe um fornecedor na aba Destaques e Marcas."""
        name = self._hb_fornecedor_var.get().strip()
        if name:
            self._set_active_profile_global(name)

    def _hb_add_advanced_keyword_rule(self):
        """Adiciona uma regra de mapeamento avançado baseada em Categoria e Subcategoria (Destaques e Marcas)."""
        cat_in = self._hb_adv_cat_var.get().strip()
        subcat_in = self._hb_adv_subcat_var.get().strip()
        parent_cat = self._hb_pai_combo.get().strip()
        if not cat_in or not parent_cat:
            messagebox.showwarning(translate("Atenção", self.language), translate("Preencha a Categoria e selecione a Categoria Pai de destino.", self.language), parent=self)
            return
        try:
            if add_highlights_brands_keyword_rule(cat_in, subcat_in, parent_cat, priority=10):
                self._hb_adv_cat_var.set("")
                self._hb_adv_subcat_var.set("")
                self._refresh_hb_adv_rules_list()
                messagebox.showinfo(translate("Guardado", self.language), translate("Regra avançada adicionada com sucesso.", self.language), parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar a regra.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _refresh_hb_adv_rules_list(self):
        """Preenche a lista de regras avançadas de Destaques e Marcas (maior prioridade primeiro)."""
        try:
            rules = get_highlights_brands_keyword_rules()
            if hasattr(self, "_hb_adv_rules_listbox"):
                self._hb_adv_rules_listbox.delete(0, tk.END)
                if rules:
                    for r in rules:
                        if "keywords" in r:
                            kws = ", ".join(r.get("keywords", []))
                            self._hb_adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] [Legado] {kws} -> {r.get('parent_category', '')}")
                        else:
                            c = r.get("category", "")
                            s = r.get("subcategory", "")
                            p = r.get("parent_category", "")
                            sub_txt = f" > {s}" if s else " (Todas subcats)"
                            self._hb_adv_rules_listbox.insert(tk.END, f"[P{r.get('priority', 0)}] Cat: {c}{sub_txt} -> {p}")
                else:
                    self._hb_adv_rules_listbox.insert(tk.END, "(Nenhuma regra avançada configurada)")
        except Exception:
            pass

    def _hb_remove_advanced_keyword_rule(self):
        """Remove a regra selecionada na lista de regras avançadas (aba Destaques e Marcas)."""
        rules = get_highlights_brands_keyword_rules()
        if not rules:
            messagebox.showinfo(translate("Informação", self.language), translate("Não há regras para remover.", self.language), parent=self)
            return
        sel = self._hb_adv_rules_listbox.curselection()
        if sel:
            index = sel[0]
            if index < len(rules):
                r = rules[index]
                if "keywords" in r:
                    desc = ", ".join(r.get("keywords", []))
                else:
                    desc = f"Cat: {r.get('category','')}" + (f" > {r.get('subcategory','')}" if r.get('subcategory','') else "")
                cat = r.get("parent_category", "")
                if messagebox.askyesno("Remover Regra", f"Remover a regra:\n'{desc} → {cat}'?", parent=self):
                    remove_highlights_brands_keyword_rule(index)
                    self._refresh_hb_adv_rules_list()
            return
        messagebox.showwarning(translate("Atenção", self.language), translate("Selecione uma regra na lista para remover.", self.language), parent=self)

    def _build_tab_configuracoes(self):
        """Constrói a aba de definições gerais da aplicação."""
        frm = ttk.Frame(self.tab_configuracoes, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=translate("Configurações", self.language), font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 10))
        language_row = ttk.Frame(frm)
        language_row.pack(anchor="w", fill="x")
        ttk.Label(language_row, text=translate("Idioma da interface:", self.language), width=24).pack(side="left")
        language_names = {
            "pt-PT": translate("Português europeu", self.language),
            "pt-BR": translate("Português brasileiro", self.language),
            "en": translate("Inglês", self.language),
        }
        self._language_codes = list(language_names)
        self._language_names = list(language_names.values())
        self._language_var = tk.StringVar(value=language_names.get(self.language, self._language_names[0]))
        self._language_combo = ttk.Combobox(
            language_row, textvariable=self._language_var,
            values=self._language_names, state="readonly", width=28,
        )
        self._language_combo.pack(side="left", padx=(0, 8))
        ttk.Button(
            language_row, text=translate("Guardar idioma", self.language),
            command=self._save_language, width=18,
        ).pack(side="left")
        ttk.Label(
            frm, text=translate("O idioma será aplicado ao reiniciar a aplicação.", self.language),
            foreground=GRAY_600,
        ).pack(anchor="w", pady=(8, 0))

        # Opções gerais da janela e atualizações
        options_label = ttk.Label(frm, text=translate("Opções gerais", self.language), font=("Segoe UI", 10, "bold"))
        options_label.pack(anchor="w", pady=(12, 4))
        self.start_maximized_var = tk.BooleanVar(value=get_start_maximized())
        ttk.Checkbutton(
            frm,
            text=translate("Abrir maximizado", self.language),
            variable=self.start_maximized_var,
            command=self._on_start_maximized_toggle,
        ).pack(anchor="w")
        self.auto_update_var = tk.BooleanVar(value=get_auto_check_updates())
        ttk.Checkbutton(
            frm,
            text=translate("Verificar atualizações automaticamente ao iniciar", self.language),
            variable=self.auto_update_var,
            command=self._on_auto_update_toggle,
        ).pack(anchor="w", pady=(2, 0))

    def _on_start_maximized_toggle(self):
        try:
            set_start_maximized(self.start_maximized_var.get())
        except Exception:
            pass

    def _save_language(self):
        selected_name = self._language_var.get()
        try:
            language = self._language_codes[self._language_names.index(selected_name)]
        except (ValueError, IndexError):
            language = "pt-PT"
        if set_language(language):
            messagebox.showinfo(
                translate("Idioma guardado", self.language),
                translate("Reinicie a aplicação para aplicar o novo idioma.", self.language),
                parent=self,
            )
        else:
            messagebox.showerror(
                translate("Erro", self.language),
                translate("Não foi possível guardar o idioma.", self.language),
                parent=self,
            )

    def _build_tab_sobre(self):
        """Constrói a aba 'Sobre' com informações da aplicação."""
        frm = ttk.Frame(self.tab_sobre, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Conversor Jumpseller", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Versão {get_current_version()}", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

        # Botão Verificar Atualizações
        check_up_btn = tk.Button(
            frm,
            text="🔄 Verificar Atualizações",
            command=self._check_for_updates,
            bg=BLUE_700,
            fg=WHITE,
            activebackground=BLUE_500,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=6,
            cursor="hand2",
        )
        check_up_btn.pack(anchor="w", pady=(0, 6))

        # Atualizações automáticas são configuradas na aba de definições;
        # aqui mostramos apenas o estado atual, sem duplicar o controlo.

        ttk.Label(frm, text="Notas de versão", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        notas = tk.Text(
            frm,
            height=10,
            relief="flat",
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 10),
            borderwidth=0,
            wrap="word",
            padx=0,
            pady=0,
        )
        notas.pack(fill="both", expand=True)
        notas.insert("1.0", """
        v0.4.0 (2026-11-12)
        - Versionamento semântico: funcionalidades novas elevam a versão de 0.3.x para 0.4.0.
        - Listas dinâmicas: Categorias Pai, Destaques, Marcas e regras de mapeamento passam a aceitar itens ilimitados com um único campo e botões Adicionar/Remover.
        - Responsividade: a janela lembra o tamanho usado pelo utilizador entre sessões, com opção "Abrir maximizado" nas definições.
        - Correções de português europeu na interface (ex.: "Definições", "Guardar", "Eliminar").
        - Atualizações: verificação passa a consultar a API pública do GitHub em vez do domínio antigo.
        - CATEGORIAS M: campo "Nome da regra:" adicionado na linha de regras, igual ao mapeamento avançado.
        - CATEGORIAS M: label duplicado "Categorias Pai" removido da coluna da esquerda.
        - Abas: "CATEGORIAS i" → "Categorias I"; "CATEGORIAS M" → "Categorias M".
        - UI: logo reduzida no header (160x60).

        v0.3.81 (2026-11-12)
        - Mapeamento massivo de categorias: nova aba "Categorias M" permite associar várias categorias de origem do fornecedor a uma categoria pai criada pelo utilizador, preservando a hierarquia original (até 4 níveis).
        - Correspondência de categorias sem distinção de maiúsculas/minúsculas e sem acentos; regras legadas continuam a funcionar.
        - Internacionalização: interface disponível em Português Europeu (padrão), Português Brasileiro e Inglês, com seleção na aba de Configurações.
        - Licença, atualizações e integração de pagamento traduzidas.
        - Documentação do projeto (CLAUDE.md) e plano de implementação adicionados.

        v0.3.80 (2026-11-11)
        - Atualizações automáticas: adicionada caixa de marcação na aba "Sobre" para ativar/desativar a verificação automática de atualizações no arranque com notificação inteligente.

        v0.3.79 (2026-11-11)
        - Licenciamento: adição de alerta automático exibido 7 dias antes da licença expirar.
        - Interface: exibição da contagem de produtos lidos no total e no preview nas árvores de dados.

        v0.3.78 (2026-11-11)
        - Ajustes na UI: botão "Comprar Licença" ocultado automaticamente quando existe uma licença válida; botão "Verificar Atualizações" movido para a aba "Sobre".

        v0.3.77 (2026-11-11)
        - Correção de interatividade: envio explícito da imagem de fundo para o fundo absoluto (lower()) e elevação do notebook de abas (lift()) para garantir que os separadores fiquem clicáveis.

        v0.3.76 (2026-11-11)
        - Otimização de desempenho no arranque e carregamento de ficheiros: leitura de CSV e extração de categorias movidas para thread em background (não bloqueia a interface / sem efeito de loading demorado).

        v0.3.75 (2026-11-11)
        - Correção do ícone da aplicação no Windows (uso explícito de iconbitmap com o ficheiro icon.ico para substituir o ícone padrão de pena do Tkinter).

        v0.3.74 (2026-11-11)
        - Correção no carregamento e visualização de CSVs após rebranding (filtragem de metadados de preço/SKU no mapeamento e auto-deteção inteligente robusta de colunas de fornecedor).

        v0.3.72 (2026-11-11)
        - Separação dos separadores Destaques e Marcas em abas independentes com mapeamento avançado específico por marca e listagens duplas de marcas.

        v0.3.71 (2026-11-11)
        - Refinamento das listas de categorias em duas colunas (Categorias Únicas e Categorias e Subcategorias) sem uso de barra como separador.

        v0.3.53 (2026-11-10)
        - Novo separador Fornecedores: gestão completa de fornecedores (perfis): listar, adicionar e remover fornecedores, com propagação instantânea da seleção para todo o programa

        v0.3.52 (2026-11-10)
        - Mapeamento Avançado: botão "Remover Regra" e seleção por lista adicionados nas abas Categorias Pai e Destaques e Marcas
        - Contagem de categorias: exibição da quantidade de categorias encontradas no ficheiro
        - Prefixo SKU: carregamento e persistência corrigidos por fornecedor ao iniciar/mudar perfil

        v0.3.51 (2026-11-10)
        - Visual / cabeçalho: logo reduzida no header e ícone da janela aplicado (assets/icon.png)

        v0.3.50 (2026-11-10)
        - Reordenação das abas: 1 Novo Ficheiro, 2 Atualizar Loja, 3 Lucro e Taxas, 4 Prefixo SKU, 5 Categorias Pai, 6 Destaques e Marcas, 7 Sobre; removida aba Como Usar; renomeada aba Categorias para Categorias Pai

        v0.3.49 (2026-11-10)
        - UI / aba Categorias e Destaques e Marcas: dropdown "Regra" integrado na linha do Mapeamento Avançado (substitui o segundo campo categoria pai), removido dropdown separado abaixo da lista de regras

        v0.3.48 (2026-11-10)
        - UI / aba Categorias e Destaques e Marcas: removido checkbox "Aplicar a TODAS as categorias do ficheiro" (padrão desmarcado), "Manter hierarquia original" sempre activo, removida seção "Aplicar apenas se a categoria contiver"; dropdown "Categorias pai configuradas" movido para dentro do Mapeamento Avançado como "Regra"

        v0.3.47 (2026-11-10)
        - Nova aba "Como Usar" com passo-a-passo instrutivo (licença, fornecedor/perfil, conversão, atualizar loja, categorias, mapeamento avançado, prefixo SKU, destaques e marcas, sobre)

        v0.3.46 (2026-11-10)
        - UI / aba Destaques e Marcas: refeita para ser idêntica ao separador Categorias (seletor de fornecedor na linha de instrução, 10 campos de categoria pai, dropdown de categorias configuradas e lista de categorias do ficheiro), para criar lista de destaques e marcas com mapeamento avançado abaixo

        v0.3.45 (2026-11-10)
        - UI / aba Destaques e Marcas: adicionada seção de Mapeamento Avançado com regras por palavra-chave, para escolher a categoria pai de destaques ou marcas e agrupar as respetivas categorias

        v0.3.44 (2026-11-10)
        - UI / aba Prefixo SKU: prefixo agora é por fornecedor, com seletor de fornecedor ao lado do campo e botão Salvar

        v0.3.43 (2026-11-10)
        - UI / aba Destaques e Marcas: refeita para ser idêntica à aba Categorias (10 campos de categoria pai, checkboxes, dropdown de categorias configuradas e lista de categorias do ficheiro)

        v0.3.42 (2026-11-10)
        - UI / cabeçalho: o fornecedor (perfil ativo) fica visível no topo da janela, para orientar quem está a trabalhar

        v0.3.41 (2026-11-10)
        - Novo separador Prefixo SKU: prefixo de 3 letras + traço (ex: VIP-) antes do SKU para identificar o fornecedor
        - Novo separador Destaques e Marcas: categorias pai para destaques e marcas com mapeamento avançado
        - Fix: Sobre mostra a versão correta (get_current_version lê VERSION.txt da raiz do projeto)

        v0.3.40 (2026-11-10)
        - UI / aba Categorias: removidas as colunas de palavras-chave das 10 categorias pai
        - UI / aba Categorias: adicionado seletor de fornecedor na linha de instrução
        - UI / aba Categorias: restaurada a seção de Mapeamento Avançado (regras por palavra-chave com prioridade)

        v0.3.36 (2026-11-09)
        - Sobre: links clicáveis para e-mail (mailto) e WhatsApp (wa.me) nos contatos do desenvolvedor, revendedor e suporte

        v0.3.35 (2026-11-09)
        - Novo: Mapeamento de Categorias por Palavras-Chave com Prioridade na aba "Categorias"
        - Associar produtos a uma categoria pai através de palavras-chave, com sistema de prioridade (regras mais recentes vencem)
        - Funciona tanto na "Conversão" (novo ficheiro) quanto no "Atualizar Loja" (merge)
        - Interface: categoria pai + palavras-chave + botão "Adicionar Regra" + lista de regras

        v0.3.33 (2026-11-09)
        - Atualizada página de download e version.txt para v0.3.32
        - Botão 'Verificar Atualizações' consulta o site público (version.txt)
        - Simplificado estilo de alerta na página de download (removido border lateral)

        v0.3.32 (2026-11-09)
        - UI: Janela maximizada por padrão
        - UI: Fundo aplicado em toda a janela
        - UI: Logo redimensionado (máx 140x50) e espaço vazio reduzido no cabeçalho
        - Correção: duplicidade na criação de abas (causava espaço extra)

        v0.3.31 (2026-11-09)
        - Logo redimensionado (máx 140x50) para não empurrar as tabs e botões do cabeçalho
        - PIL/Pillow necessário para redimensionamento automático da logo

        v0.3.30 (2026-11-08)
        - Novo: até 10 categorias pai (Categoria 1 ... Categoria 10) para agrupar categorias do fornecedor
        - Removida a aba Organizador de Categorias (arrastar/soltar)
        - Mantido o mapeamento direto de categorias pai na conversão

        v0.3.29 (2026-11-08)
        - Novo: mapeamento de categorias do fornecedor para categoria pai da Jumpseller (até 10 associações)
        - Campo 1: categoria do fornecedor; Campo 2: categoria pai da Jumpseller
        - Substituído o sistema de arrastar/soltar por mapeamento direto de categorias pai

        v0.3.28 (2026-11-08)
        - Janela agora abre maximizada
        - Logo redimensionado (máx 200x70) para não empurrar as tabs e botões do cabeçalho
        - Fundo apenas na área de drop da conversão

        v0.3.27 (2026-11-07)
        - Novo: integração das logos/identidade com assets/logo.png e assets/fundo.png
        - Consistência: opção "RETIRAR PRODUTOS INDISPONÍVEIS" aplicada também ao fluxo "Atualizar loja" (merge_update)
        - UI: pequenas melhorias de layout e branding

        v0.3.26 (2026-11-07)
        - Novo: opção "RETIRAR PRODUTOS INDISPONÍVEIS" (ignora stock 0 / not-available na conversão)
        - Confirmação: stock 0 no fornecedor é convertido como Status not-available

        v0.3.25 (2026-11-07)
        - Correção: exportar hierarquia completa de categorias no CSV (inclui nível raiz do mapeamento em todos os caminhos Jumpseller)

        v0.3.24 (2026-11-05)
        - UI: "Mapeamento" (removido "Macro"), texto do filtro mais claro, guardar sem alertas no mapeamento

        v0.3.23 (2026-11-05)
        - Correção: exibir subcategorias/filhas na árvore do organizador (render recursivo como no standalone)

        v0.3.22 (2026-11-05)
        - Correção: árvore de categorias vazia no organizador (scrollregion/dimensionamento do canvas) + log de diagnóstico

        v0.3.21 (2026-11-05)
        - Carregador visual na área da árvore de categorias durante o carregamento

        v0.3.20 (2026-11-04)
        - Melhorias no organizador de categorias (arrastar/soltar, persistência)
        - Guardar organização de categorias entre sessões

        v0.3.14 (2026-10-28)
        - Fix: Ajuste de layout no diálogo "Mapear Campos" (evitar truncamento de texto)

        v0.3.14 (2026-10-28)
        - Fix: Layout dos botões no diálogo de mapeamento (empilhamento vertical)
        - Tradução completa das instruções de mapeamento para pt-PT

        v0.3.13 (2026-10-28)
        - Fix: Limitar categorias a 4 níveis e normalizar "/" por " e " no modo Atualizar loja

        v0.3.11 (2026-10-27)
        - Fix: Substituir "/" por " e " nos nomes de categorias e subcategorias

        v0.3.10 (2026-10-11)
        - Fix: NameError no _refresh_profile_combo (_PROFILE_DEFAULT não importado)
        - Fix: import _PROFILE_DEFAULT do field_mapping na dropdown de fornecedores

        v0.3.8 (2026-10-10)
        - Mapeamento de campos personalizável
        - Suporte a CSVs com nomes de colunas diferentes dos padrão
        - Botão "Mapear Campos..." para configurar
        - Arquivo de configuração: field_mapping_config.json

        v0.3.7 (2026-10-07)
        - Fix: verificar atualizações usa o site público (version.txt)

        v0.3.6 (2026-10-07)
        - Fix: repo correto para verificar atualizações
        - Fix: VERSION.txt embutido no exe
        - Fix: versão no exe mostra corretamente

        v0.3.5 (2026-10-07)
        - Fix: VERSION.txt embutido no exe
        - Fix: versão no exe mostra corretamente
        - Fix: repo correto para verificar atualizações

        v0.3.4 (2026-10-07)
        - Fix: versão no exe via version_info.txt
        - Fix: licença Sair fecha o programa
        - Fix: Sover com versão, desenvolvedor e contacto
        - Fix: ttk.Button.Tonal not found

        v0.3.3 (2026-10-07)
        - Fix: Sair no diálogo de licença fecha o programa
        - Fix: Sover agora mostra versão correcta
        - Fix: Sover inclui desenvolvedor e contacto
        - Fix: ttk.Button.Tonal not found — usar tk.Button
        - Fix: get_current_version import

        v0.3.2 (2026-10-07)
        - Fix: ttk.Button.Tonal not found — usar tk.Button

        v0.3.1 (2026-10-07)
        - Fix: import get_current_version na aba Sover (NameError)
        - Aba Sover com notas de versão e estado da licença
        - _open_license_window fecha dialog se licença válida
        - Botão Comprar Licença desativado
        - Botão Verificar Atualizações

        v0.3.0 (2026-10-07)
        - Aba Sover com notas de versão e estado da licença
        - _open_license_window verifica licença e fecha dialog se válida
        - Botão Comprar Licença desativado
        - Botão Verificar Atualizações

        v0.2.0 (2026-10-07)
        - Correção de encoding UTF-16 em arquivos de loja
        - Botão Comprar Licença desativado até integração com Stripe
        - Botão Verificar Atualizações
        - Licença não pede novamente se válida

        v0.1.0 (2026-10-03)
        - Versão inicial com licença offline
        - Conversão de CSV para Jumpseller
        - Atualização de loja com cruza de dados
        """)
        notas.config(state="disabled")
        
        ttk.Label(frm, text="Mapeamento de Campos", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        mapping_info = tk.Text(
            frm,
            height=6,
            relief="flat",
            bg=BG_WINDOW,
            fg=GRAY_800,
            font=("Segoe UI", 9),
            borderwidth=0,
            wrap="word",
            padx=0,
            pady=0,
        )
        mapping_info.pack(fill="both", expand=True)
        mapping_info.insert("1.0", """
        v0.3.10 (2026-10-11)
        - Fix: NameError no _refresh_profile_combo (_PROFILE_DEFAULT não importado)
        - Fix: import _PROFILE_DEFAULT do field_mapping na dropdown de fornecedores

        v0.3.8 (2026-10-10)
        - Mapeamento de campos personalizável
        - Suporte a CSVs com nomes de colunas diferentes
        - Botão "Mapear Campos..." para configurar
        - Arquivo de configuração: field_mapping_config.json
        - Compatibilidade mantida com CSVs antigos (mapeamento vazio por padrão)

        """)
        mapping_info.config(state="disabled")
        
        ttk.Label(frm, text="Licença", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        lic_path = self._stored_license_path()
        lic_status = "Não detectada"
        if lic_path.is_file():
            try:
                data = json.loads(lic_path.read_text(encoding="utf-8"))
                lic_status = f"Válida até: {data.get('expires', '—')}"
            except (OSError, ValueError):
                lic_status = "Inválida"
        ttk.Label(frm, text=lic_status, font=("Segoe UI", 10)).pack(anchor="w")

        ttk.Label(frm, text="Desenvolvedor", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        ttk.Label(frm, text="Alexsander Fernandes", font=("Segoe UI", 10)).pack(anchor="w")
        self._make_link_label(frm, "afgouveia90@gmail.com", "mailto:afgouveia90@gmail.com").pack(anchor="w")
        self._make_link_label(frm, "WhatsApp: +351 923 337 992", "https://wa.me/351923337992").pack(anchor="w")

        ttk.Label(frm, text="Revendedor Autorizado", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        ttk.Label(frm, text="Miguel Meireles", font=("Segoe UI", 10)).pack(anchor="w")
        self._make_link_label(frm, "inforgreen.recondicionados@gmail.com", "mailto:inforgreen.recondicionados@gmail.com").pack(anchor="w")
        self._make_link_label(frm, "WhatsApp: +351 914 321 860", "https://wa.me/351914321860").pack(anchor="w")

        ttk.Label(frm, text="Contacto", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        self._make_link_label(frm, "E-mail de Suporte: afgouveia90@gmail.com", "mailto:afgouveia90@gmail.com").pack(anchor="w")
        self._make_link_label(frm, "E-mail de Vendas: inforgreen.recondicionados@gmail.com", "mailto:inforgreen.recondicionados@gmail.com").pack(anchor="w")

        btn_lic = tk.Button(
            frm,
            text="Renovar Licença",
            command=self._open_license_window,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            relief="flat",
            font=("Segoe UI", 10),
            padx=12,
            pady=4,
            cursor="hand2",
        )
        btn_lic.pack(anchor="w", pady=(12, 0))

    def _make_link_label(self, parent, text: str, url: str) -> tk.Label:
        """Cria um label de texto azul, sublinhado e clicável que abre url no navegador."""
        lbl = tk.Label(
            parent,
            text=text,
            fg="#1565C0",
            cursor="hand2",
            font=("Segoe UI", 10, "underline"),
        )
        lbl.bind("<Button-1>", lambda e: webbrowser.open(url))
        return lbl

    # -- handlers -------------------------------------------------------

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Selecione o CSV de entrada",
            filetypes=[("CSVs", "*.csv"), ("Todos os arquivos", "*")],
        )
        if path:
            self.path_var.set(path)
            set_last_input_file(path)
            self._update_drop_text(path)
            self._extract_categories_from_file(path)

    def _browse_export(self):
        path = filedialog.askopenfilename(
            title="Selecione o export da loja (Jumpseller)",
            filetypes=[("CSVs", "*.csv"), ("Todos os arquivos", "*")],
        )
        if path:
            self.export_var.set(path)

    def _browse_fornecedor(self):
        path = filedialog.askopenfilename(
            title="Selecione o novo ficheiro do fornecedor",
            filetypes=[("CSVs", "*.csv"), ("Todos os arquivos", "*")],
        )
        if path:
            self.fornecedor_var.set(path)
            self._extract_categories_from_file(path)

    def _merge(self):
        out_dir = self.out_dir_var.get().strip()
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror(translate("Erro", self.language), translate("Escolha uma pasta de destino valida.", self.language), parent=self)
            return
        export_raw = self.export_var.get().strip().strip('"').strip("'")
        forn_raw = self.fornecedor_var.get().strip().strip('"').strip("'")
        if not export_raw or not forn_raw:
            messagebox.showwarning("Faltam ficheiros",
                                   "Selecione o export da loja E o novo ficheiro do fornecedor.",
                                   parent=self)
            return
        if not os.path.isfile(export_raw):
            messagebox.showerror(translate("Erro", self.language), f"{translate('Export da loja nao encontrado:', self.language)}\n{export_raw}", parent=self)
            return
        if not os.path.isfile(forn_raw):
            messagebox.showerror(translate("Erro", self.language), f"{translate('Ficheiro do fornecedor nao encontrado:', self.language)}\n{forn_raw}", parent=self)
            return

        self.merge_btn.config(state="disabled")
        self._set_drop_text("A atualizar loja em background (otimizado com cache e threads)...", "#FFF9C4", "#F57F17", widget=self.drop_text_update)
        self.update_idletasks()

        def worker():
            try:
                exclude_unavailable = bool(getattr(self, "exclude_unavailable_var", None) and self.exclude_unavailable_var.get())
                out, n_atual, n_novos, n_intactos, removed = merge_update(export_raw, forn_raw, out_dir, exclude_unavailable=exclude_unavailable)
                self.last_output = Path(out)
                resumo = (
                    f"Atualizados: {n_atual}\nNovos: {n_novos}\n"
                    f"Intactos (so na loja): {n_intactos}\n"
                )
                if exclude_unavailable and removed:
                    resumo += f"Removidos indisponíveis: {removed}\n"
                resumo += f"\nFicheiro: {out}"

                def on_success():
                    self._set_drop_text(resumo, BLUE_100, BLUE_700, widget=self.drop_text_update)
                    self.open_folder_btn.config(state="normal")
                    self.open_folder_btn2.config(state="normal")
                    messagebox.showinfo("Concluido", resumo, parent=self)
                    self.merge_btn.config(state="normal")
                self.after(0, on_success)
            except Exception as exc:
                err_msg = f"Erro inesperado: {exc}"
                def on_err():
                    self._set_drop_text(err_msg, "#FFEBEE", "#C62828", widget=self.drop_text_update)
                    messagebox.showerror(translate("Erro", self.language), err_msg, parent=self)
                    self.merge_btn.config(state="normal")
                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _browse_output(self):
        d = filedialog.askdirectory(
            title="Selecione a pasta de destino", initialdir=self.out_dir_var.get(),
        )
        if d:
            self.out_dir_var.set(d)

    def _on_drop(self, event):
        files = event.data.strip().strip("{}")
        candidates = files.replace("\r\n", " ").split()
        csv_found = next((f for f in candidates if f.lower().endswith(".csv")), None)
        if csv_found:
            self.path_var.set(csv_found)
            set_last_input_file(csv_found)
            self._update_drop_text(csv_found)
            self._extract_categories_from_file(csv_found)
        else:
            messagebox.showwarning("Arquivo invalido", "Arraste apenas um arquivo .csv.", parent=self)

    def _set_drop_text(self, text, bg, fg, widget=None):
        target = widget or self._status_widget
        if target is None:
            return
        target.config(state="normal", bg=bg, fg=fg)
        target.delete("1.0", "end")
        target.insert("1.0", text)
        target.config(state="disabled")

    def _update_drop_text(self, path):
        self._set_drop_text(
            f"Arquivo: {Path(path).name}", BLUE_100, BLUE_700,
            widget=self._status_widget,
        )

    def _open_folder(self):
        out = self.last_output
        if not out or not out.exists():
            self._set_drop_text("Nenhum resultado recente para abrir.", "#FFEBEE", "#C62828")
            return
        folder = str(out.parent)
        try:
            subprocess.Popen(["explorer.exe", folder])
        except Exception as exc:
            messagebox.showerror("Nao foi possivel abrir", f"Erro ao abrir a pasta:\n{exc}", parent=self)

    # -- gate de licenca ------------------------------------------------

    def _ensure_license(self):
        """
        Garante que existe uma licenca valida antes de qualquer conversao.

        Devolve True quando a licenca actual e valida. Devolve False se o
        utilizador fechou o dialog sem conseguir activar.

        A validacao corre dentro do ciclo do dialog, e nao depois: assim o
        utilizador pode tentar varias licencas seguidas sem sair da
        aplicacao, e o motivo da recusa aparece no proprio ecra onde ele
        esta a arrastar o ficheiro.
        """
        lic_path = self._stored_license_path()
        ok, reason = check_license(lic_path)
        if ok:
            # Licença válida: verificar aviso de expiração (nos próximos 7 dias)
            if not getattr(self, "_license_warning_shown", False):
                self._license_warning_shown = True
                warning_msg = check_license_expiry_warning(lic_path)
                if warning_msg:
                    messagebox.showwarning("Aviso de Validade da Licença", warning_msg, parent=self)
            return True

        # primeira tentativa: explicar porquê, se houver cached path
        dialog = LicenseDialog(
            self,
            LICENSE_DIR,
            reason=reason,
            on_submit=self._accept_license,
            on_cancel=self._deny_license,
        )
        self.wait_window(dialog.win)
        return self._licensed

    def _deny_license(self):
        """Chamado quando o utilizador clica em 'Sair' no diálogo de licença."""
        self._licensed = False
        # Forçar fechamento da aplicação — não permite usar sem licença
        self.after(100, self.destroy)

    def _stored_license_path(self) -> Path:
        """Licença guardada na ultima activacao, ou o caminho por defeito."""
        cached = load_license_state().get("license_path")
        if cached and Path(cached).is_file():
            return Path(cached)
        return LICENSE_DIR / "conversor.lic"

    def _accept_license(self, path: Path) -> tuple[bool, str]:
        """
        Chamado pelo dialog com o .lic escolhido. Devolve (ok, message).

        Guarda a licença em %LOCALAPPDATA% para sobreviver a reinicios e
        move-a para a pasta de licenças, de modo a que o caminho guardado
        aponte para um ficheiro que o cliente não vá mover.
        """
        ok, reason = check_license(path)
        if ok:
            try:
                LICENSE_DIR.mkdir(parents=True, exist_ok=True)
                target = LICENSE_DIR / "conversor.lic"
                if path.resolve() != target.resolve():
                    target.write_text(
                        path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
            except OSError as exc:
                messagebox.showwarning(
                    "Aviso",
                    f"Licença válida, mas não foi possível guardá-la:\n{exc}\n"
                    "Volte a arrastá-la na próxima vez que abrir o programa.",
                    parent=self,
                )
            self._licensed = True
            self._license_warning_shown = False
            msg = f"Licença ativa: {path.name}"
            self._last_license_message = msg
            warning_msg = check_license_expiry_warning(path)
            if warning_msg:
                messagebox.showwarning("Aviso de Validade da Licença", warning_msg, parent=self)
            return True, msg
        else:
            self._licensed = False
            self._last_license_message = reason
            return False, reason

    # -- acesso a licenca (botao no rodape) -------------------------------

    def _open_license_window(self):
        """Botão 'Licença…': mostra a licença ativa e permite renovar/carregar novo ficheiro .lic."""
        lic_path = self._stored_license_path()
        ok, reason = check_license(lic_path)

        detail = ""
        if lic_path.is_file():
            try:
                data = json.loads(lic_path.read_text(encoding="utf-8"))
                detail = (
                    f"Licença ativa:\n"
                    f"• Loja / Licenciado: {data.get('licensee', '—')}\n"
                    f"• Válida até: {data.get('expires', '—')}\n\n"
                )
            except (OSError, ValueError):
                pass

        msg = f"{detail}Deseja carregar ou renovar um novo ficheiro de licença (.lic)?" if ok else f"Licença inválida ou não encontrada.\n{reason}\n\nPretende carregar um ficheiro .lic?"

        if messagebox.askyesno("Gestão de Licença", msg, parent=self):
            dialog = LicenseDialog(
                self,
                LICENSE_DIR,
                reason=reason if not ok else "",
                on_submit=self._accept_license,
            )
            self.wait_window(dialog.win)

    def _save_price_settings(self):
        """Guarda as configurações de preços."""
        try:
            profit_str = self._price_profit_var.get().strip().replace(",", ".")
            iva_str = self._price_iva_var.get().strip().replace(",", ".")
            shipping_str = self._price_shipping_var.get().strip().replace(",", ".")

            profit_pct = None
            iva_pct = None
            shipping = None

            if profit_str:
                try:
                    p = float(profit_str)
                    if p > 0:
                        profit_pct = p
                except ValueError:
                    pass
            if iva_str:
                try:
                    p = float(iva_str)
                    if p >= 0:
                        iva_pct = p
                except ValueError:
                    pass
            if shipping_str:
                try:
                    p = float(shipping_str)
                    if p >= 0:
                        shipping = p
                except ValueError:
                    pass

            from core.field_mapping import get_active_profile
            if set_price_settings(profit_percentage=profit_pct, iva_percentage=iva_pct, shipping_cost=shipping, price_formula="detailed", profile_name=get_active_profile()):
                messagebox.showinfo(translate("Guardado", self.language), translate("Configurações de preços guardadas para este perfil.", self.language), parent=self)
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Não foi possível guardar as configurações de preços.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}: {e}", parent=self)

    def _auto_save_price_settings(self):
        """Guarda automaticamente as configurações de preços da interface antes de converter."""
        try:
            if not hasattr(self, "_price_profit_var"):
                return
            profit_str = self._price_profit_var.get().strip().replace(",", ".")
            iva_str = self._price_iva_var.get().strip().replace(",", ".")
            shipping_str = self._price_shipping_var.get().strip().replace(",", ".")

            profit_pct = None
            iva_pct = None
            shipping = None

            if profit_str:
                try:
                    p = float(profit_str)
                    if p > 0:
                        profit_pct = p
                except ValueError:
                    pass
            if iva_str:
                try:
                    p = float(iva_str)
                    if p >= 0:
                        iva_pct = p
                except ValueError:
                    pass
            if shipping_str:
                try:
                    p = float(shipping_str)
                    if p >= 0:
                        shipping = p
                except ValueError:
                    pass

            from core.field_mapping import get_active_profile, set_price_settings
            set_price_settings(
                profit_percentage=profit_pct,
                iva_percentage=iva_pct,
                shipping_cost=shipping,
                price_formula="detailed",
                profile_name=get_active_profile()
            )
        except Exception:
            pass

    def _open_stripe_checkout(self):
        """Botão 'Comprar Licença': abre a página de pagamento Stripe."""
        open_stripe_checkout(language=self.language)

    def _check_for_updates(self):
        """Botão 'Verificar Atualizações': verifica se há novas versões."""
        check_for_updates(show_message=True, parent=self, language=self.language)

    def _on_auto_update_toggle(self):
        try:
            set_auto_check_updates(self.auto_update_var.get())
        except Exception:
            pass

    def _check_updates_startup(self):
        if not get_auto_check_updates():
            return
        def worker():
            try:
                from core.updater import get_latest_version, _parse_version, get_current_version
                current = get_current_version()
                latest = get_latest_version()
                if latest and _parse_version(latest) > _parse_version(current):
                    def notify():
                        if messagebox.askyesno(
                            translate("Atualização disponível", self.language),
                            f"{translate('Nova versão disponível:', self.language)} {latest}\n\n{translate('Pretende abrir a página de download?', self.language)}",
                            parent=self
                        ):
                            import webbrowser
                            webbrowser.open("https://alexsanderfer.github.io/conversor/")
                    self.after(0, notify)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_profile_combo(self):
        """Actualiza a lista de fornecedores na dropdown."""
        profiles = list_profiles()
        self.profile_combo["values"] = profiles
        active = get_active_profile()
        if active not in profiles:
            active = profiles[0] if profiles else _PROFILE_DEFAULT
            set_active_profile(active)
        self.profile_var.set(active)

    def _on_profile_change(self, _event=None):
        """Chamado quando o utilizador troca o fornecedor na dropdown."""
        name = self.profile_var.get().strip()
        if name:
            self._set_active_profile_global(name)

    def _new_profile(self):
        """Cria um novo perfil de fornecedor."""
        name = simpledialog.askstring(
            "Novo fornedor",
            "Nome do novo fornedor:",
            parent=self,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        try:
            if save_profile(name, {}) and set_active_profile(name):
                self._refresh_profile_combo()
                messagebox.showinfo(
                    "Fornedor criado",
                    f"Perfil '{name}' criado (mapeamento vazio).\n"
                    "Use o botão 'Mapear Campos...' para configurar os campos.",
                    parent=self,
                )
            else:
                messagebox.showerror(translate("Erro", self.language), translate("Nao foi possivel criar o perfil.", self.language), parent=self)
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}:\n{e}", parent=self)

    def _delete_profile(self):
        """Apaga o perfil de fornedor atualmente selecionado."""
        name = self.profile_var.get().strip()
        if not name:
            return
        try:
            if delete_profile(name):
                self._refresh_profile_combo()
                messagebox.showinfo(translate("Fornedor apagado", self.language), f"{translate('Perfil foi removido.', self.language)}: '{name}'", parent=self)
            else:
                messagebox.showwarning(
                    "Nao foi possivel apagar",
                    "Nao e possivel apagar o unico perfil existente.", parent=self,
                )
        except Exception as e:
            messagebox.showerror(translate("Erro", self.language), f"{translate('Erro', self.language)}:\n{e}", parent=self)

    def _open_field_mapping(self):
        """Botão 'Mapear Campos...': abre o diálogo de mapeamento de campos."""
        current_mapping = load_field_mapping()
        detected_mapping = {}
        # Try to auto-detect from selected file if available
        try:
            selected_file = self.path_var.get().strip().strip('"').strip("'")
            if selected_file and os.path.isfile(selected_file):
                headers, _ = _read_csv_any_delimiter(selected_file)
                detected_mapping = _detect_field_mapping_from_headers(headers)
        except Exception:
            detected_mapping = {}
        # Also try for update tab files
        if not detected_mapping:
            try:
                fornecedor_file = self.fornecedor_var.get().strip().strip('"').strip("'")
                if fornecedor_file and os.path.isfile(fornecedor_file):
                    headers, _ = _read_csv_any_delimiter(fornecedor_file)
                    detected_mapping = _detect_field_mapping_from_headers(headers)
            except Exception:
                detected_mapping = {}

        dialog = FieldMappingDialog(self, current_mapping, detected_mapping)
        result = dialog.show()
        if result is not None:
            messagebox.showinfo(
                "Mapeamento atualizado",
                "O mapeamento de campos foi atualizado.\n"
                "A próxima conversão usará as novas configurações.",
                parent=self,
            )

    def _convert(self):
        if not self._ensure_license():
            return
        raw = self.path_var.get().strip().strip('"').strip("'")
        if not raw:
            messagebox.showwarning("Campo vazio", "Selecione ou digite um arquivo CSV primeiro.", parent=self)
            return
        self._auto_save_price_settings()
        self.convert_btn.config(state="disabled")
        self._set_drop_text("A processar conversão em background (otimizado com cache e threads)...", "#FFF9C4", "#F57F17", widget=self._status_widget)
        self.update_idletasks()

        def worker():
            try:
                import time
                start_time = time.time()
                out_dir = self.out_dir_var.get()
                exclude_unavailable = bool(getattr(self, "exclude_unavailable_var", None) and self.exclude_unavailable_var.get())
                n, out, removed = process_csv(raw, out_dir, exclude_unavailable=exclude_unavailable)
                elapsed = time.time() - start_time
                if elapsed < 60:
                    time_str = f"{elapsed:.1f} segundos"
                else:
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    time_str = f"{mins}m {secs}s"

                self.last_output = Path(out)
                status_msg = f"Concluído: {n} linha(s) em {time_str} -> {self.last_output.name}"
                if exclude_unavailable and removed:
                    status_msg += f" | Removidos indisponíveis: {removed}"

                def on_success():
                    self._set_drop_text(
                        status_msg,
                        BLUE_100, BLUE_700, widget=self._status_widget,
                    )
                    self.open_folder_btn.config(state="normal")
                    info_msg = f"{n} linha(s) convertidas com sucesso em {time_str}!\nFicheiro guardado em:\n{out}"
                    if exclude_unavailable:
                        info_msg += f"\n\nProdutos indisponíveis removidos (stock 0 / not-available): {removed}"
                    info_msg += "\n\nAbrir pasta do resultado abaixo."
                    messagebox.showinfo("Concluído", info_msg, parent=self)
                    self.convert_btn.config(state="normal")
                self.after(0, on_success)
            except FileNotFoundError as exc:
                err_msg = str(exc)
                def on_err1():
                    self._set_drop_text(err_msg, ERROR_BG, ERROR_FG, widget=self._status_widget)
                    messagebox.showerror(translate("Erro", self.language), err_msg, parent=self)
                    self.convert_btn.config(state="normal")
                self.after(0, on_err1)
            except Exception as exc:
                err_msg = f"Erro inesperado: {exc}"
                def on_err2():
                    self._set_drop_text(err_msg, ERROR_BG, ERROR_FG, widget=self._status_widget)
                    messagebox.showerror(translate("Erro", self.language), err_msg, parent=self)
                    self.convert_btn.config(state="normal")
                self.after(0, on_err2)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = App()
    # Antes do mainloop: enquanto nao houver licenca valida, so se ve o
    # dialog de activacao. E preciso rodar o loop para o dialog funcionar.
    app._licensed = False
    app._last_license_message = ""
    app.update_idletasks()
    app.lift()
    app.attributes('-topmost', True)
    app.after(100, lambda: app.attributes('-topmost', False))
    if app._ensure_license():
        app.lift()
        app.attributes('-topmost', True)
        app.after(100, lambda: app.attributes('-topmost', False))
        app.mainloop()