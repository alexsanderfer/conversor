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

from core.license_dialog import LicenseDialog
from core.license_manager import check_license, load_license_state
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
    GREEN_100,
    GREEN_500,
    GREEN_700,
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
)
from core.category_classifier import classify_product, load_rules, save_rules, learn_from_product, learn_from_file_rows

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


def load_price_state(output_dir: str) -> dict:
    path = os.path.join(output_dir, STATE_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_price_state(output_dir: str, state: dict):
    path = os.path.join(output_dir, STATE_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as exc:
        raise OSError(f"Nao foi possivel guardar o estado dos precos: {exc}")


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
    prev_state = load_price_state(output_dir)
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

    save_price_state(output_dir, new_state)

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
        self._status_widget = None   # widget onde _set_drop_text escreve
        self._apply_window_icon()
        self._build_ui()

    def _build_ui(self):
        apply_theme(self)

        # aplicar fundo
        bg_img = self._load_background()
        if bg_img:
            self.bg_label = tk.Label(self, image=bg_img)
            self.bg_label.image = bg_img
            self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)

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

        # botão comprar licença (desativado até integrar Stripe)
        self._buy_license_btn = tk.Button(
            top_container,
            text="Comprar Licença",
            command=self._open_stripe_checkout,
            bg=GREEN_700,
            fg=WHITE,
            activebackground=GREEN_500,
            activeforeground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=2,
            cursor="hand2",
            state="disabled",
        )
        self._buy_license_btn.pack(in_=top_container, side="right", padx=(0, 8), pady=2)

        # botão verificar atualizações
        self._check_updates_btn = tk.Button(
            top_container,
            text="Verificar Atualizações",
            command=self._check_for_updates,
            bg=GRAY_100,
            fg=GRAY_800,
            activebackground="#E0E0E0",
            activeforeground=GRAY_800,
            relief="flat",
            font=("Segoe UI", 9),
            padx=12,
            pady=2,
            cursor="hand2",
        )
        self._check_updates_btn.pack(in_=top_container, side="right", pady=2)

        # barra de separadores
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(2, 6))

        self.tab_fornecedores = ttk.Frame(self.tabs, padding=8)
        self.tab_novo = ttk.Frame(self.tabs, padding=8)
        self.tab_update = ttk.Frame(self.tabs, padding=8)
        self.tab_lucro = ttk.Frame(self.tabs, padding=8)
        self.tab_sku_prefix = ttk.Frame(self.tabs, padding=8)
        self.tab_categorias = ttk.Frame(self.tabs, padding=8)
        self.tab_highlights_brands = ttk.Frame(self.tabs, padding=8)
        self.tab_sobre = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.tab_fornecedores, text="  Fornecedores  ")
        self.tabs.add(self.tab_novo, text="  Novo Ficheiro  ")
        self.tabs.add(self.tab_update, text="  Atualizar Loja  ")
        self.tabs.add(self.tab_lucro, text="  Lucro e Taxas  ")
        self.tabs.add(self.tab_sku_prefix, text="  Prefixo SKU  ")
        self.tabs.add(self.tab_categorias, text="  Categorias  ")
        self.tabs.add(self.tab_highlights_brands, text="  Destaques e Marcas  ")
        self.tabs.add(self.tab_sobre, text="  Sobre  ")

        self._build_tab_fornecedores()
        self._build_tab_novo()
        self._build_tab_update()
        self._build_tab_lucro()
        self._build_tab_sku_prefix()
        self._build_tab_categorias()
        self._build_tab_highlights_brands()
        self._build_tab_sobre()
        self._build_footer()

    # -- ícone da janela --------------------------------------------------

    def _apply_window_icon(self):
        """Define o ícone da aplicação (barra de título e taskbar)."""
        try:
            p = ASSETS / "icon.png"
            if p.is_file():
                from PIL import Image, ImageTk
                img = ImageTk.PhotoImage(file=str(p))
                self.iconphoto(True, img)
                self._window_icon = img  # manter referência para não ser coletado pelo GC
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
                    max_w, max_h = 80, 25
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

        self.drop_text = tk.Text(
            self.tab_novo, height=6, relief="sunken",
            bg=GRAY_100, font=("Segoe UI", 10), borderwidth=1, wrap="word",
        )
        self.drop_text.pack(fill="both", expand=True, pady=(8, 8))

        # Background image inside drop text area
        self._bg_image = self._load_background()
        if getattr(self, '_bg_image', None):
            try:
                self._bg_label = tk.Label(self.drop_text, image=self._bg_image, bg=WHITE)
                self._bg_label.place(relx=0.5, rely=0.5, anchor="center")
            except Exception:
                pass

        self.drop_text.drop_target_register(DND_FILES)
        self.drop_text.dnd_bind("<<Drop>>", self._on_drop)
        self._set_drop_text(
            "Arraste um arquivo .csv aqui, ou clique em 'Escolher arquivo…'",
            GRAY_100, GRAY_800,
            widget=self.drop_text,
        )
        self._status_widget = self.drop_text

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

        self.drop_text_update = tk.Text(
            self.tab_update, height=6, relief="sunken",
            bg=GRAY_100, font=("Segoe UI", 10), borderwidth=1, wrap="word",
        )
        self.drop_text_update.pack(fill="both", expand=True, pady=(0, 8))
        style_drop_area(self.drop_text_update)

        # Background image inside drop text area
        if getattr(self, '_bg_image', None):
            try:
                self._bg_label_up = tk.Label(self.drop_text_update, image=self._bg_image, bg=WHITE)
                self._bg_label_up.place(relx=0.5, rely=0.5, anchor="center")
            except Exception:
                pass

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
            messagebox.showerror("Erro", f"Erro ao propagar fornecedor: {e}", parent=self)

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
            messagebox.showwarning("Atenção", "Insira o nome do novo fornecedor.", parent=self)
            return
        try:
            if save_profile(name, {}):
                self._new_forn_var.set("")
                self._set_active_profile_global(name)
                self._refresh_profile_combo()
                self._refresh_cat_fornecedor_combo()
                self._refresh_hb_fornecedor_combo()
                self._refresh_sku_fornecedor_combo()
                messagebox.showinfo("Sucesso", f"Fornecedor '{name}' criado e selecionado com sucesso.", parent=self)
            else:
                messagebox.showerror("Erro", "Não foi possível criar o fornecedor.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao criar fornecedor: {e}", parent=self)

    def _tab_set_active_selected_profile(self):
        sel = self._forn_listbox.curselection()
        if not sel:
            messagebox.showwarning("Atenção", "Selecione um fornecedor na lista.", parent=self)
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
            messagebox.showinfo("Ativo", f"Fornecedor '{name}' definido como ativo.", parent=self)

    def _tab_delete_selected_profile(self):
        sel = self._forn_listbox.curselection()
        if not sel:
            messagebox.showwarning("Atenção", "Selecione um fornecedor na lista para eliminar.", parent=self)
            return
        profiles = list_profiles()
        idx = sel[0]
        if idx < len(profiles):
            name = profiles[idx]
            if len(profiles) <= 1:
                messagebox.showwarning("Atenção", "Não pode eliminar o último fornecedor restante.", parent=self)
                return
            if messagebox.askyesno("Eliminar", f"Tem certeza que deseja eliminar o fornecedor '{name}'?", parent=self):
                if delete_profile(name):
                    new_active = get_active_profile()
                    self._set_active_profile_global(new_active)
                    self._refresh_profile_combo()
                    self._refresh_cat_fornecedor_combo()
                    self._refresh_hb_fornecedor_combo()
                    self._refresh_sku_fornecedor_combo()
                    messagebox.showinfo("Eliminado", f"Fornecedor '{name}' eliminado com sucesso.", parent=self)
                else:
                    messagebox.showerror("Erro", "Não foi possível eliminar o fornecedor.", parent=self)

    def _build_tab_categorias(self):
        """Constrói a aba 'Categorias' com mapeamento de categorias."""
        frm = ttk.Frame(self.tab_categorias, padding=6)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Mapeamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

        # Linha de instrução com seletor de fornecedor ao lado
        header_row = ttk.Frame(frm)
        header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(header_row, text="Crie até 10 categorias pai para agrupar as categorias do fornecedor", font=("Segoe UI", 9), foreground=GRAY_600).pack(side="left")
        ttk.Label(header_row, text="  Fornecedor:", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self._cat_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._cat_fornecedor_combo = ttk.Combobox(header_row, textvariable=self._cat_fornecedor_var, state="readonly", width=24)
        self._cat_fornecedor_combo.pack(side="left")
        self._cat_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_cat_fornecedor_change)
        self._refresh_cat_fornecedor_combo()

        cat_settings = get_category_settings()
        self._cat_new_vars = []
        for i in range(10):
            val = cat_settings.get("new_categories", [""] * 10)[i] if i < len(cat_settings.get("new_categories", [])) else ""
            v = tk.StringVar(value=val)
            self._cat_new_vars.append(v)
            row = ttk.Frame(frm)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"Categoria {i+1}:", width=12).pack(side="left")
            ttk.Entry(row, textvariable=v, width=34).pack(side="left", padx=(4, 6))
            ttk.Button(row, text="Guardar", command=self._save_category_settings, width=8).pack(side="left", padx=(4, 0))

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
        ttk.Entry(adv_row, textvariable=self._adv_cat_var, width=18).pack(side="left", padx=(0, 4))
        ttk.Label(adv_row, text="Subcat.:").pack(side="left", padx=(4, 2))
        self._adv_subcat_var = tk.StringVar()
        ttk.Entry(adv_row, textvariable=self._adv_subcat_var, width=18).pack(side="left", padx=(0, 4))
        ttk.Label(adv_row, text="Pai:").pack(side="left", padx=(4, 2))
        self._cat_pai_combo = ttk.Combobox(adv_row, state="readonly", width=22)
        self._cat_pai_combo.pack(side="left", padx=(0, 4))
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

    def _extract_categories_from_file(self, filepath):
        try:
            if not filepath or not os.path.isfile(filepath):
                return
            self._last_loaded_filepath = filepath
            headers, rows = _read_csv_any_delimiter(filepath)
            if not headers:
                return
            mapping = load_field_mapping()
            unique_cats_set = set()
            subcat_cats_set = set()
            for row in rows:  # Analisar todas as linhas do ficheiro sem limite artificial
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
                except Exception:
                    continue
            self._unique_categories = sorted(list(unique_cats_set)) if unique_cats_set else []
            self._subcat_categories = sorted(list(subcat_cats_set)) if subcat_cats_set else []
            self._all_categories = self._subcat_categories
            self._filter_categories()
            self._hb_filter_categories()
        except Exception:
            pass

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
                messagebox.showinfo("Sucesso", "Categorias recarregadas com sucesso a partir do ficheiro!", parent=self)
            else:
                messagebox.showwarning("Atenção", "Nenhum ficheiro CSV válido selecionado para recarregar.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao recarregar categorias: {e}", parent=self)

    def _toggle_auto_classification(self):
        try:
            from category_classifier import load_rules, save_rules
            data = load_rules()
            data["enabled"] = bool(self._auto_cat_enabled_var.get())
            save_rules(data)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar: {e}", parent=self)

    def _add_classification_rule(self):
        try:
            from category_classifier import load_rules, save_rules
            keyword = self._rule_keyword_var.get().strip()
            category = self._rule_category_var.get().strip()
            if not keyword or not category:
                messagebox.showwarning("Atenção", "Preencha palavra-chave e categoria destino.", parent=self)
                return
            data = load_rules()
            rules = data.get("rules", [])
            rules.append({"keywords": [keyword.lower()], "category": category, "priority": 15})
            data["rules"] = rules
            if save_rules(data):
                self._rule_keyword_var.set("")
                self._rule_category_var.set("")
                self._refresh_rules_list()
                messagebox.showinfo("Guardado", "Regra adicionada com sucesso.", parent=self)
            else:
                messagebox.showerror("Erro", "Não foi possível guardar a regra.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar: {e}", parent=self)

    def _learn_from_current_file(self):
        try:
            selected_file = self.path_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                selected_file = self.fornecedor_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                messagebox.showwarning("Atenção", "Selecione ou arraste um ficheiro CSV primeiro.", parent=self)
                return
            headers, rows = _read_csv_any_delimiter(selected_file)
            if not rows:
                messagebox.showwarning("Atenção", "Não foi possível ler o ficheiro ou está vazio.", parent=self)
                return
            mapping = load_field_mapping()
            count = learn_from_file_rows(rows, mapping)
            self._refresh_rules_list()
            if hasattr(self, '_category_settings_cache'):
                self._category_settings_cache = None
            messagebox.showinfo("Aprendido", f"Aprendidas {count} novas regras com base no ficheiro.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao aprender: {e}", parent=self)

    def _preview_classification(self):
        try:
            selected_file = self.path_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                selected_file = self.fornecedor_var.get().strip().strip('"').strip("'")
            if not selected_file or not os.path.isfile(selected_file):
                messagebox.showwarning("Atenção", "Selecione ou arraste um ficheiro CSV primeiro.", parent=self)
                return
            headers, rows = _read_csv_any_delimiter(selected_file)
            if not rows:
                messagebox.showwarning("Atenção", "Não foi possível ler o ficheiro ou está vazio.", parent=self)
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
            messagebox.showerror("Erro", f"Erro ao pré-visualizar: {e}", parent=self)

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
            new_cats = [v.get().strip() for v in self._cat_new_vars]
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
            messagebox.showwarning("Atenção", "Preencha a Categoria e selecione a Categoria Pai de destino.", parent=self)
            return
        try:
            if add_keyword_rule(cat_in, subcat_in, parent_cat, priority=10):
                self._adv_cat_var.set("")
                self._adv_subcat_var.set("")
                self._refresh_adv_rules_list()
                messagebox.showinfo("Guardado", "Regra avançada adicionada com sucesso.", parent=self)
            else:
                messagebox.showerror("Erro", "Não foi possível guardar a regra.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar regra: {e}", parent=self)

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
            messagebox.showinfo("Informação", "Não há regras para remover.", parent=self)
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
        messagebox.showwarning("Atenção", "Selecione uma regra na lista para remover.", parent=self)

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
            messagebox.showwarning("Atenção", "Selecione um fornecedor.", parent=self)
            return
        if not prefix:
            set_sku_prefix("", name)
            messagebox.showinfo("Guardado", f"Prefixo SKU removido para '{name}'.", parent=self)
            return
        # Valida: 3 letras + traço (ex: VIP-)
        import re
        if not re.match(r"^[A-Za-z]{3}-$", prefix):
            messagebox.showwarning("Atenção", "O prefixo deve ter 3 letras seguidas de um traço (ex: VIP-).", parent=self)
            return
        prefix = prefix.upper()
        self._sku_prefix_var.set(prefix)
        if set_sku_prefix(prefix, name):
            messagebox.showinfo("Guardado", f"Prefixo SKU '{prefix}' guardado para '{name}'.", parent=self)
        else:
            messagebox.showerror("Erro", "Não foi possível guardar o prefixo SKU.", parent=self)

    def _build_tab_highlights_brands(self):
        """Constrói a aba 'Destaques e Marcas' — idêntica à aba Categorias."""
        frm = ttk.Frame(self.tab_highlights_brands, padding=6)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Mapeamento", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))

        # Linha de instrução com seletor de fornecedor ao lado (igual ao separador Categorias)
        hb_header_row = ttk.Frame(frm)
        hb_header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(hb_header_row, text="Crie até 10 categorias pai para agrupar as categorias do fornecedor", font=("Segoe UI", 9), foreground=GRAY_600).pack(side="left")
        ttk.Label(hb_header_row, text="  Fornecedor:", font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self._hb_fornecedor_var = tk.StringVar(value=get_active_profile())
        self._hb_fornecedor_combo = ttk.Combobox(hb_header_row, textvariable=self._hb_fornecedor_var, state="readonly", width=24)
        self._hb_fornecedor_combo.pack(side="left")
        self._hb_fornecedor_combo.bind("<<ComboboxSelected>>", self._on_hb_fornecedor_change)
        self._refresh_hb_fornecedor_combo()

        hb_settings = get_highlights_brands_settings()
        self._hb_new_vars = []
        for i in range(10):
            val = hb_settings.get("new_categories", [""] * 10)[i] if i < len(hb_settings.get("new_categories", [])) else ""
            v = tk.StringVar(value=val)
            self._hb_new_vars.append(v)
            row = ttk.Frame(frm)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"Categoria {i+1}:", width=12).pack(side="left")
            ttk.Entry(row, textvariable=v, width=34).pack(side="left", padx=(4, 6))
            ttk.Button(row, text="Guardar", command=self._save_highlights_brands_settings, width=8).pack(side="left", padx=(4, 0))

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
            new_cats = [v.get().strip() for v in self._hb_new_vars]
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
            messagebox.showwarning("Atenção", "Preencha a Categoria e selecione a Categoria Pai de destino.", parent=self)
            return
        try:
            if add_highlights_brands_keyword_rule(cat_in, subcat_in, parent_cat, priority=10):
                self._hb_adv_cat_var.set("")
                self._hb_adv_subcat_var.set("")
                self._refresh_hb_adv_rules_list()
                messagebox.showinfo("Guardado", "Regra avançada adicionada com sucesso.", parent=self)
            else:
                messagebox.showerror("Erro", "Não foi possível guardar a regra.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar regra: {e}", parent=self)

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
            messagebox.showinfo("Informação", "Não há regras para remover.", parent=self)
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
        messagebox.showwarning("Atenção", "Selecione uma regra na lista para remover.", parent=self)

    def _build_tab_sobre(self):
        """Constrói a aba 'Sobre' com informações da aplicação."""
        frm = ttk.Frame(self.tab_sobre, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Conversor Jumpseller", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Versão {get_current_version()}", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 16))

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
            messagebox.showerror("Erro", "Escolha uma pasta de destino valida.", parent=self)
            return
        export_raw = self.export_var.get().strip().strip('"').strip("'")
        forn_raw = self.fornecedor_var.get().strip().strip('"').strip("'")
        if not export_raw or not forn_raw:
            messagebox.showwarning("Faltam ficheiros",
                                   "Selecione o export da loja E o novo ficheiro do fornecedor.",
                                   parent=self)
            return
        if not os.path.isfile(export_raw):
            messagebox.showerror("Erro", f"Export da loja nao encontrado:\n{export_raw}", parent=self)
            return
        if not os.path.isfile(forn_raw):
            messagebox.showerror("Erro", f"Ficheiro do fornecedor nao encontrado:\n{forn_raw}", parent=self)
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
                    self._set_drop_text(resumo, GREEN_100, GREEN_700, widget=self.drop_text_update)
                    self.open_folder_btn.config(state="normal")
                    self.open_folder_btn2.config(state="normal")
                    messagebox.showinfo("Concluido", resumo, parent=self)
                    self.merge_btn.config(state="normal")
                self.after(0, on_success)
            except Exception as exc:
                err_msg = f"Erro inesperado: {exc}"
                def on_err():
                    self._set_drop_text(err_msg, "#FFEBEE", "#C62828", widget=self.drop_text_update)
                    messagebox.showerror("Erro", err_msg, parent=self)
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
            f"Arquivo: {Path(path).name}", GREEN_100, GREEN_700,
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
            # Licença válida: não abre dialog, devolve diretamente
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

    def _accept_license(self, path: Path) -> bool:
        """
        Chamado pelo dialog com o .lic escolhido. Devolve True se fechou.

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
            self._last_license_message = f"Licença activa: {path.name}"
        else:
            self._licensed = False
            self._last_license_message = reason
        return self._licensed

    # -- acesso a licenca (botao no rodape) -------------------------------

    def _open_license_window(self):
        """Botao 'Licença…': mostra a licencia activa ou permite renovar."""
        lic_path = self._stored_license_path()
        ok, reason = check_license(lic_path)
        if ok:
            # Licença válida: fecha o diálogo sem mostrar popup
            self._licensed = True
            return
        detail = ""
        if lic_path.is_file():
            try:
                data = json.loads(lic_path.read_text(encoding="utf-8"))
                detail = (
                    f"\n\nLoja: {data.get('licensee', '—')}\n"
                    f"Válida até: {data.get('expires', '—')}"
                )
            except (OSError, ValueError):
                pass
        messagebox.showinfo(
            "Licença",
            f"Aplicação Conversor Jumpseller.{detail}\n\n"
            "Para activar ou renovar, arraste o novo ficheiro .lic para a janela.",
            parent=self,
        )

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
                messagebox.showinfo("Guardado", "Configurações de preços guardadas para este perfil.", parent=self)
            else:
                messagebox.showerror("Erro", "Não foi possível guardar as configurações de preços.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar: {e}", parent=self)

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
        from stripe_integration import open_stripe_checkout
        open_stripe_checkout()

    def _check_for_updates(self):
        """Botão 'Verificar Atualizações': verifica se há novas versões."""
        from updater import check_for_updates, get_current_version
        check_for_updates(show_message=True, parent=self)

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
                messagebox.showerror("Erro", "Nao foi possivel criar o perfil.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao criar perfil:\n{e}", parent=self)

    def _delete_profile(self):
        """Apaga o perfil de fornedor atualmente selecionado."""
        name = self.profile_var.get().strip()
        if not name:
            return
        try:
            if delete_profile(name):
                self._refresh_profile_combo()
                messagebox.showinfo("Fornedor apagado", f"Perfil '{name}' foi removido.", parent=self)
            else:
                messagebox.showwarning(
                    "Nao foi possivel apagar",
                    "Nao e possivel apagar o unico perfil existente.", parent=self,
                )
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao apagar perfil:\n{e}", parent=self)

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
                        GREEN_100, GREEN_700, widget=self._status_widget,
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
                    messagebox.showerror("Erro", err_msg, parent=self)
                    self.convert_btn.config(state="normal")
                self.after(0, on_err1)
            except Exception as exc:
                err_msg = f"Erro inesperado: {exc}"
                def on_err2():
                    self._set_drop_text(err_msg, ERROR_BG, ERROR_FG, widget=self._status_widget)
                    messagebox.showerror("Erro", err_msg, parent=self)
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