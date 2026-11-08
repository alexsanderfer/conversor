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
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from tkinterdnd2 import DND_FILES, Tk

from license_dialog import LicenseDialog
from license_manager import check_license, load_license_state
from stripe_integration import open_stripe_checkout
from updater import check_for_updates, get_current_version
from theme import (
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
from field_mapping import (
    load_field_mapping, get_mapped_value, save_field_mapping, DEFAULT_FIELD_MAPPING,
    list_profiles, get_active_profile, set_active_profile,
    get_profile_mapping, save_profile, delete_profile, _PROFILE_DEFAULT,
    get_profit_margin, get_price_settings, set_price_settings,
    get_category_settings, set_category_settings,
)
from category_classifier import classify_product, load_rules, save_rules, learn_from_product, learn_from_file_rows

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
ASSETS = Path(__file__).parent / "assets"

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
        from field_mapping import get_active_profile
        settings = get_price_settings(get_active_profile())
        formula = settings.get("price_formula", "margin")
        if formula == "detailed":
            profit_pct = float(settings.get("profit_percentage", 40.0))
            iva_pct = float(settings.get("iva_percentage", 0.0))
            shipping = float(settings.get("shipping_cost", 0.0))
            # Preço final = (Preço custo * (1 + lucro%)) + portes + IVA
            price = preco * (1.0 + profit_pct / 100.0) + shipping
            if iva_pct and iva_pct > 0:
                price = price * (1.0 + iva_pct / 100.0)
            return str(round(price, 2))
        else:
            price = preco * get_profit_margin()
            return str(round(price, 2))
    except Exception:
        try:
            price = preco * get_profit_margin()
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


def build_categories(row: dict, mapping: dict = None) -> str:
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

    def normalize(val):
        return re.sub(r'\s*/\s*', ' e ', val)

    familia = normalize(get_mapped_value(row, "familia_principal", mapping))
    sub_familia = normalize(get_mapped_value(row, "sub_familia", mapping))
    sub_sub_familia = normalize(get_mapped_value(row, "sub_sub_familia", mapping))

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
        new_cats_parent = cat_settings.get("new_categories_parent", [""]*10)
        # Construir dicionário: categoria_fornecedor -> categoria_pai
        cat_to_parent = {}
        for i, nc in enumerate(new_cats):
            if nc:
                par = new_cats_parent[i].strip() if i < len(new_cats_parent) else ""
                cat_to_parent[nc] = par
        if cat_to_parent and categories:
            # Determinar o pai para a categoria principal (familia)
            familia = categories[0] if categories else ""
            parent_cat = cat_to_parent.get(familia, "")
            if parent_cat:
                # Jumpseller needs ALL hierarchy levels from root to leaf.
                # When mapping to a parent, output: [parent, parent/cat1, parent/cat1/cat2, ...]
                result = [parent_cat]
                for cat_path in categories:
                    cp = (cat_path or "").strip().strip("/")
                    if not cp:
                        continue
                    prefixed = f"{parent_cat}/{cp}"
                    if prefixed not in result:
                        result.append(prefixed)
                return ",".join(result)
    except Exception:
        pass

    return ",".join(categories)


def convert_row(row: dict, mapping: dict = None) -> dict:
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
    dest_row["Categories"] = build_categories(row, mapping)
    dest_row["Images"] = get_mapped_value(row, "imagem", mapping)
    dest_row["Digital"] = "NO"
    dest_row["Featured"] = "NO"
    stock_val = parse_stock(get_mapped_value(row, "stock", mapping))
    dest_row["Status"] = "available" if stock_val > 0 else "not-available"
    dest_row["SKU"] = get_mapped_value(row, "ref", mapping)
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
    output_name = f"{input_name}_jumpseller.csv"
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
            converted = convert_row(row, mapping)
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
    _write_xlsx_preview(
        rows, os.path.join(os.path.dirname(output_path),
                           Path(output_path).stem + "_visualizar.xlsx")
    )
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
            out.append((convert_row(row, mapping), _parse_pt_number(row.get("preco", ""))))
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

    output_path = os.path.join(output_dir, "loja_atualizada_jumpseller.csv")
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=DEST_COLUMNS, delimiter=";", quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(merged)

    _write_xlsx_preview(merged, os.path.join(output_dir, "loja_atualizada_visualizar.xlsx"))
    save_price_state(output_dir, new_state)

    n_atualizados = len(matched_skus)
    n_novos = (len(fornecedor_rows) - removed_unavailable) - n_atualizados
    if n_novos < 0:
        n_novos = 0
    n_intactos = sum(len(v) for v in by_sku.values()) - n_atualizados
    return output_path, n_atualizados, n_novos, n_intactos, removed_unavailable


def _write_xlsx_preview(rows, path):
    try:
        from openpyxl import Workbook
    except ImportError:
        return None
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("loja_atualizada")
    ws.freeze_panes = "A2"
    ws.append([str(c) for c in DEST_COLUMNS])
    for row in rows:
        ws.append([str(row.get(col, "") or "") for col in DEST_COLUMNS])
    wb.save(path)
    return path


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
        self.title("Conversor CSV → Jumpseller")
        self.geometry("1200x800")
        self.minsize(900, 650)
        self.resizable(True, True)
        self.state("zoomed")  # abre maximizado
        self.last_output = None
        self._status_widget = None   # widget onde _set_drop_text escreve
        self._build_ui()

    def _build_ui(self):
        apply_theme(self)

        # container superior com logo, botão de compra e botão de atualização
        top_container = tk.Frame(self, bg=BG_WINDOW)
        top_container.pack(fill="x", pady=(0, 4))

        # logo (graceful: se o asset faltar, o label nao aparece)
        self._logo_label = self._load_logo()
        if self._logo_label:
            self._logo_label.pack(in_=top_container, anchor="w", pady=(0, 4))

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
            pady=4,
            cursor="hand2",
            state="disabled",
        )
        self._buy_license_btn.pack(in_=top_container, side="right", padx=(0, 8), pady=(0, 4))

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
            pady=4,
            cursor="hand2",
        )
        self._check_updates_btn.pack(in_=top_container, side="right", pady=(0, 4))

        # barra de separadores
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        # barra de separadores
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self.tab_novo = ttk.Frame(self.tabs, padding=8)
        self.tab_update = ttk.Frame(self.tabs, padding=8)
        self.tab_lucro = ttk.Frame(self.tabs, padding=8)
        self.tab_categorias = ttk.Frame(self.tabs, padding=8)
        self.tab_sobre = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.tab_novo, text="  Novo ficheiro  ")
        self.tabs.add(self.tab_update, text="  Atualizar loja  ")
        self.tabs.add(self.tab_lucro, text="  Lucro e Taxas  ")
        self.tabs.add(self.tab_categorias, text="  Categorias  ")
        self.tabs.add(self.tab_sobre, text="  Sobre  ")

        self._build_tab_novo()
        self._build_tab_update()
        self._build_tab_lucro()
        self._build_tab_categorias()
        self._build_tab_sobre()
        self._build_footer()

    # -- logo -----------------------------------------------------------

    def _load_logo(self):
        for name in ("logo.png", "logo.gif"):
            p = ASSETS / name
            if p.is_file():
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(p)
                    # Limitar largura e altura para caber no header (logo pequeno, não empurra as tabs)
                    max_w, max_h = 200, 70
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
        for name in ("fundo.png", "background.png", "bg.png"):
            p = ASSETS / name
            if p.is_file():
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(p)
                    # Redimensionar para caber na área de drop (~300x200)
                    im2 = im.resize((300, 200), Image.LANCZOS)
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
            from field_mapping import get_active_profile
            price_settings = get_price_settings(get_active_profile())
        except Exception:
            price_settings = get_price_settings()
        self._price_profit_var = tk.StringVar(value=str(price_settings.get("profit_percentage", 40.0)))
        self._price_iva_var = tk.StringVar(value=str(price_settings.get("iva_percentage", 0.0)))
        self._price_shipping_var = tk.StringVar(value=str(price_settings.get("shipping_cost", 0.0)))
        self._price_formula_var = tk.StringVar(value=price_settings.get("price_formula", "margin"))

        ttk.Label(frm_preco, text="Lucro %:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm_preco, textvariable=self._price_profit_var, width=10).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(frm_preco, text="IVA %:").grid(row=0, column=2, sticky="w")
        ttk.Entry(frm_preco, textvariable=self._price_iva_var, width=10).grid(row=0, column=3, sticky="w", padx=(4, 12))
        ttk.Label(frm_preco, text="Portes (€):").grid(row=0, column=4, sticky="w")
        ttk.Entry(frm_preco, textvariable=self._price_shipping_var, width=10).grid(row=0, column=5, sticky="w", padx=(4, 12))

        ttk.Label(frm_preco, text="Fórmula:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        formula_combo = ttk.Combobox(frm_preco, textvariable=self._price_formula_var, values=["margin", "detailed"], state="readonly", width=12)
        formula_combo.grid(row=1, column=1, sticky="w", padx=(4, 12), pady=(4, 0))
        ttk.Button(frm_preco, text="Guardar", command=self._save_price_settings, width=10).grid(row=1, column=2, sticky="w", pady=(4, 0))

        ttk.Label(frm, text="As configurações são guardadas por perfil e aplicadas apenas quando definidas.\nValores vazios ou zero não são aplicados.", font=("Segoe UI", 9), foreground=GRAY_600, justify="left").pack(anchor="w", pady=(8, 0))

    def _build_tab_categorias(self):
        """Constrói a aba 'Categorias' com mapeamento de categorias."""
        frm = ttk.Frame(self.tab_categorias, padding=6)
        frm.pack(fill="both", expand=True)

        # Criar notebook para separar seções
        cat_notebook = ttk.Notebook(frm)
        cat_notebook.pack(fill="both", expand=True)

        tab_macro = ttk.Frame(cat_notebook, padding=10)
        tab_organizer = ttk.Frame(cat_notebook, padding=10)
        cat_notebook.add(tab_macro, text="  Mapeamento  ")
        cat_notebook.add(tab_organizer, text="  Organizador  ")

        # Aba Mapeamento
        ttk.Label(tab_macro, text="Associar categorias do fornecedor a categorias pai da Jumpseller", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(tab_macro, text="Crie até 10 associações. No campo 1 escreve o nome da categoria do fornecedor; no campo 2 escolhe a categoria pai da Jumpseller.", font=("Segoe UI", 9), foreground=GRAY_600).pack(anchor="w", pady=(0, 8))

        cat_settings = get_category_settings()
        self._cat_new_vars = []
        self._cat_parent_vars = []
        for i in range(10):
            val = cat_settings.get("new_categories", [""]*10)[i] if i < len(cat_settings.get("new_categories", [])) else ""
            par = cat_settings.get("new_categories_parent", [""]*10)[i] if i < len(cat_settings.get("new_categories_parent", [])) else ""
            v = tk.StringVar(value=val)
            pv = tk.StringVar(value=par)
            self._cat_new_vars.append(v)
            self._cat_parent_vars.append(pv)
            row = ttk.Frame(tab_macro)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"{i+1}.", width=3).pack(side="left")
            ttk.Label(row, text="Categoria do fornecedor:", width=22).pack(side="left")
            ttk.Entry(row, textvariable=v, width=28).pack(side="left", padx=(4, 6))
            ttk.Label(row, text="→ Categoria pai Jumpseller:", width=24).pack(side="left")
            ttk.Entry(row, textvariable=pv, width=28).pack(side="left", padx=(4, 6))
            ttk.Button(row, text="Guardar", command=self._save_category_settings, width=8).pack(side="left", padx=(4, 0))

        self._cat_prefix_var = tk.StringVar(value="")

        ttk.Button(tab_macro, text="Guardar todas as configurações de categorias", command=self._save_category_settings, width=45).pack(anchor="w", pady=(4, 0))

        ttk.Separator(tab_macro, orient="horizontal").pack(fill="x", pady=(10, 6))
        ttk.Label(tab_macro, text="Categorias encontradas no ficheiro selecionado", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        cat_frame = ttk.Frame(tab_macro)
        cat_frame.pack(fill="both", expand=True)
        self._cat_list_text = tk.Text(cat_frame, height=5, relief="sunken", bg=GRAY_100, font=("Consolas", 8), wrap="none")
        cat_scroll = ttk.Scrollbar(cat_frame, orient="vertical", command=self._cat_list_text.yview)
        self._cat_list_text.configure(yscrollcommand=cat_scroll.set)
        self._cat_list_text.pack(side="left", fill="both", expand=True)
        cat_scroll.pack(side="right", fill="y")
        self._cat_list_text.config(state="disabled")

        # Aba Organizador
        ttk.Label(tab_organizer, text="Organizador de Categorias (Arrastar e Soltar)", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(tab_organizer, text="Carregue as categorias do ficheiro para organizar e reestruturar", font=("Segoe UI", 9), foreground=GRAY_600).pack(anchor="w", pady=(0, 6))

        org_btn_frame = ttk.Frame(tab_organizer)
        org_btn_frame.pack(fill="x", pady=(0, 6))
        self._org_load_btn = ttk.Button(
            org_btn_frame, text="Carregar Categorias do Ficheiro",
            command=self._load_categories_for_organizer,
        )
        self._org_load_btn.pack(side="left")
        ttk.Button(org_btn_frame, text="Guardar Organização", command=self._save_category_organization).pack(side="left", padx=(4, 0))
        ttk.Button(org_btn_frame, text="Editar Selecionado", command=lambda: self._edit_category_name(self._get_selected_category())).pack(side="left", padx=(4, 0))

        # Botões de expansão
        ttk.Button(org_btn_frame, text="Expandir Todos", command=self._expand_all).pack(side="left", padx=(4, 0))
        ttk.Button(org_btn_frame, text="Esconder Todos", command=self._collapse_all).pack(side="left", padx=(4, 0))

        self._org_container = ttk.Frame(tab_organizer)
        self._org_container.pack(fill="both", expand=True, pady=(4, 0))
        self._org_canvas = tk.Canvas(self._org_container, bg=GRAY_100, highlightthickness=1, highlightbackground=GRAY_600)
        org_scroll = ttk.Scrollbar(self._org_container, orient="vertical", command=self._org_canvas.yview)
        self._org_frame = tk.Frame(self._org_canvas, bg=GRAY_100)
        self._org_frame.bind("<Configure>", lambda e: self._org_canvas.configure(scrollregion=self._org_canvas.bbox("all")))
        self._org_window = self._org_canvas.create_window((0, 0), window=self._org_frame, anchor="nw")
        self._org_canvas.configure(yscrollcommand=org_scroll.set)
        self._org_canvas.pack(side="left", fill="both", expand=True)
        org_scroll.pack(side="right", fill="y")

        # Soltar no fundo = mover para raiz
        self._org_canvas.bind("<ButtonRelease-1>", self._on_org_canvas_release)

        self._org_loading_overlay = tk.Frame(self._org_container, bg=GRAY_100)
        self._org_loading_label = tk.Label(
            self._org_loading_overlay,
            text="A carregar categorias...",
            bg=GRAY_100,
            fg=GRAY_800,
            font=("Segoe UI", 10, "bold"),
        )
        self._org_loading_label.pack(pady=(24, 8))
        self._org_loading_bar = ttk.Progressbar(
            self._org_loading_overlay, mode="indeterminate", length=220,
        )
        self._org_loading_bar.pack(pady=(0, 24))

        self._category_tree = {}
        self._category_items = {}  # label widget -> category name
        self._drag_data = {"item": None, "category": None, "parent": None, "level": 0, "hover_target": None, "orig_place": None, "last_motion_ts": 0.0}

    def _extract_categories_from_file(self, filepath):
        try:
            if not filepath or not os.path.isfile(filepath):
                return
            headers, rows = _read_csv_any_delimiter(filepath)
            if not headers:
                return
            mapping = load_field_mapping()
            cats_set = set()
            for row in rows[:1000]:  # Limitar para performance
                try:
                    familia = get_mapped_value(row, "familia_principal", mapping)
                    sub_familia = get_mapped_value(row, "sub_familia", mapping)
                    sub_sub_familia = get_mapped_value(row, "sub_sub_familia", mapping)
                    def normalize(val):
                        return re.sub(r'\s*/\s*', ' e ', val)
                    familia_n = normalize(familia)
                    sub_familia_n = normalize(sub_familia)
                    sub_sub_familia_n = normalize(sub_sub_familia)
                    if familia_n:
                        cats_set.add(familia_n)
                    if sub_familia_n and familia_n:
                        cats_set.add(f"{familia_n}/{sub_familia_n}")
                    if sub_sub_familia_n and familia_n and sub_familia_n:
                        cats_set.add(f"{familia_n}/{sub_familia_n}/{sub_sub_familia_n}")
                except Exception:
                    continue
            if hasattr(self, '_cat_list_text') and cats_set:
                cats_list = sorted(list(cats_set))
                self._cat_list_text.config(state="normal")
                self._cat_list_text.delete("1.0", "end")
                self._cat_list_text.insert("1.0", "\n".join(cats_list))
                self._cat_list_text.config(state="disabled")
        except Exception:
            pass

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

    def _show_org_loading(self, text="A carregar categorias..."):
        try:
            if hasattr(self, "_org_loading_label"):
                self._org_loading_label.config(text=text)
            if hasattr(self, "_org_loading_overlay"):
                self._org_loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
                self._org_loading_overlay.lift()
            if hasattr(self, "_org_loading_bar"):
                self._org_loading_bar.start(10)
            if hasattr(self, "_org_load_btn"):
                self._org_load_btn.config(state="disabled")
            self.update_idletasks()
        except Exception:
            pass

    def _hide_org_loading(self):
        try:
            if hasattr(self, "_org_loading_bar"):
                self._org_loading_bar.stop()
            if hasattr(self, "_org_loading_overlay"):
                self._org_loading_overlay.place_forget()
            if hasattr(self, "_org_load_btn"):
                self._org_load_btn.config(state="normal")
        except Exception:
            pass

    def _load_categories_for_organizer(self):
        selected_file = self.path_var.get().strip().strip('"').strip("'")
        if not selected_file or not os.path.isfile(selected_file):
            selected_file = self.fornecedor_var.get().strip().strip('"').strip("'")
        if not selected_file or not os.path.isfile(selected_file):
            messagebox.showwarning("Atenção", "Selecione ou arraste um ficheiro CSV primeiro.", parent=self)
            return

        self._show_org_loading("A carregar categorias...")

        def worker():
            result = {"ok": False, "error": None, "tree": None}
            log_path = None
            try:
                import traceback, datetime
                try:
                    base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConversorJumpseller"
                    base_dir.mkdir(parents=True, exist_ok=True)
                    log_path = base_dir / "debug_organizer.log"
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now()}] START _load_categories_for_organizer\n")
                        f.write(f"[{datetime.datetime.now()}] selected_file={selected_file}\n")
                except Exception:
                    try:
                        log_path = Path(__file__).parent / "debug_organizer.log"
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now()}] START _load_categories_for_organizer\n")
                    except Exception:
                        pass

                headers, rows = _read_csv_any_delimiter(selected_file)
                try:
                    if log_path:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now()}] rows={len(rows)}\n")
                except Exception:
                    pass
                if not rows:
                    result["error"] = "Não foi possível ler o ficheiro ou está vazio."
                    return

                mapping = load_field_mapping()
                saved = self._load_saved_category_organization()
                try:
                    if log_path:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now()}] saved={'yes' if saved else 'no'} tree_keys={len(saved) if isinstance(saved, dict) else None}\n")
                except Exception:
                    pass

                category_tree = {}
                if saved is not None:
                    try:
                        if isinstance(saved, dict):
                            for k, v in saved.items():
                                if isinstance(v, set):
                                    category_tree[k] = set(v)
                                elif isinstance(v, list):
                                    category_tree[k] = set(v)
                                else:
                                    category_tree[k] = set()
                        if "" not in category_tree:
                            category_tree[""] = set()
                        # Quebrar ciclos
                        for _ in range(30):
                            fixed = False
                            for parent, children in list(category_tree.items()):
                                for child in list(children):
                                    if child == parent or child == "":
                                        try:
                                            children.discard(child)
                                        except Exception:
                                            pass
                                        fixed = True
                                        continue
                                    if child in category_tree and parent in category_tree.get(child, set()):
                                        try:
                                            children.discard(child)
                                        except Exception:
                                            pass
                                        fixed = True
                            if not fixed:
                                break
                    except Exception as ex:
                        try:
                            if log_path:
                                with open(log_path, "a", encoding="utf-8") as f:
                                    f.write(f"[{datetime.datetime.now()}] saved load err {ex}\n")
                                    f.write(traceback.format_exc())
                        except Exception:
                            pass
                        category_tree = {"": set()}
                else:
                    try:
                        if log_path:
                            with open(log_path, "a", encoding="utf-8") as f:
                                f.write(f"[{datetime.datetime.now()}] building tree from scratch, mapping keys sample: {list(mapping.keys())[:10]}, headers: {headers[:15]}\n")
                    except Exception:
                        pass
                    found = 0
                    for row in rows[:10000]:
                        try:
                            f1 = get_mapped_value(row, "familia_principal", mapping).strip()
                            f2 = get_mapped_value(row, "sub_familia", mapping).strip()
                            f3 = get_mapped_value(row, "sub_sub_familia", mapping).strip()

                            if 'faminome' in row and str(row.get('faminome')).strip():
                                val = str(row['faminome']).strip()
                                if val and not val.isdigit() and val.lower() not in ['null', 'none']:
                                    f1 = val
                            if not f1 or f1.isdigit():
                                for k in ['faminome', 'familia_nome', 'nome_familia']:
                                    if k in row and str(row[k]).strip() and not str(row[k]).strip().isdigit():
                                        f1 = str(row[k]).strip()
                                        break
                            if not f1:
                                for key in ['categoria', 'category', 'grupo', 'departamento', 'familia', 'família', 'categoria_principal']:
                                    for k, v in row.items():
                                        kl = str(k).lower().strip()
                                        if k and (key == kl or (key in kl and len(kl) < 25)):
                                            val = str(v).strip()
                                            if val and not val.isdigit() and val.lower() not in ['categoria', 'categorias']:
                                                f1 = val
                                                break
                                    if f1:
                                        break
                            if 'sub_familia' in row and str(row.get('sub_familia')).strip():
                                f2 = str(row['sub_familia']).strip()
                            if not f2:
                                for key in ['subcategoria', 'sub_categoria', 'subfamilia']:
                                    for k, v in row.items():
                                        kl = str(k).lower().strip()
                                        if k and (key == kl or key in kl):
                                            val = str(v).strip()
                                            if val:
                                                f2 = val
                                                break
                                    if f2:
                                        break
                            if 'sub_sub_familia' in row and str(row.get('sub_sub_familia')).strip():
                                f3 = str(row['sub_sub_familia']).strip()
                            if not f3:
                                for key in ['subsubcategoria', 'sub_sub_categoria']:
                                    for k, v in row.items():
                                        kl = str(k).lower().strip()
                                        if k and (key == kl or key in kl):
                                            val = str(v).strip()
                                            if val:
                                                f3 = val
                                                break
                                    if f3:
                                        break

                            if f1:
                                found += 1
                                if "" not in category_tree:
                                    category_tree[""] = set()
                                category_tree[""].add(f1)
                                if f1 not in category_tree:
                                    category_tree[f1] = set()
                                if f2:
                                    category_tree[f1].add(f2)
                                    if f2 not in category_tree:
                                        category_tree[f2] = set()
                                    if f3:
                                        category_tree[f2].add(f3)
                                        if f3 not in category_tree:
                                            category_tree[f3] = set()
                        except Exception:
                            continue
                    try:
                        if log_path:
                            with open(log_path, "a", encoding="utf-8") as f:
                                f.write(f"[{datetime.datetime.now()}] found categories from rows: {found}, roots in tree: {len(category_tree.get('', set()))}\n")
                    except Exception:
                        pass

                result["tree"] = category_tree
                result["ok"] = True
                try:
                    if log_path:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now()}] worker ok\n")
                except Exception:
                    pass
            except Exception as e:
                try:
                    import traceback, datetime
                    if log_path:
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now()}] FATAL {e}\n")
                            f.write(traceback.format_exc())
                except Exception:
                    pass
                result["error"] = str(e)

            self.after(0, lambda: self._on_org_categories_loaded(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_org_categories_loaded(self, result):
        try:
            if not result.get("ok"):
                self._hide_org_loading()
                messagebox.showwarning(
                    "Atenção",
                    result.get("error") or "Não foi possível carregar as categorias.",
                    parent=self,
                )
                return

            tree = result.get("tree") or {"": set()}
            self._category_tree = tree
            try:
                self._rebuild_org_tree()
            except Exception:
                try:
                    self._category_tree = {"": set(list((tree or {}).get("", set()))[:30])}
                    self._rebuild_org_tree()
                except Exception:
                    pass

            self._hide_org_loading()
            roots = len((self._category_tree or {}).get("", set()) or set())
            nodes = len(getattr(self, "_category_items", {}) or {})
            if nodes <= 0 and roots <= 0:
                messagebox.showwarning(
                    "Carregado",
                    "O carregamento terminou, mas não há categorias para mostrar.\n"
                    "Isto pode acontecer se não existirem colunas de categoria no ficheiro ou se o mapeamento de campos não encontrar a coluna correta.",
                    parent=self,
                )
            else:
                messagebox.showinfo("Carregado", f"Categorias carregadas com sucesso.\nRaízes: {roots} | Itens: {nodes}", parent=self)
        except Exception as e:
            self._hide_org_loading()
            messagebox.showerror("Erro", f"Erro ao carregar categorias: {e}", parent=self)

    def _rebuild_org_tree(self):
        """Reconstrói a árvore visual baseada no estado atual de `self._category_tree`."""
        def _log(msg):
            try:
                base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConversorJumpseller"
                base_dir.mkdir(parents=True, exist_ok=True)
                with open(base_dir / "debug_organizer.log", "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.datetime.now()}] [rebuild] {msg}\n")
            except Exception:
                pass

        try:
            for widget in self._org_frame.winfo_children():
                widget.destroy()
        except Exception:
            pass

        self._category_items = {}
        self._current_y = 10

        try:
            tree = getattr(self, '_category_tree', {}) or {}
            # Garantir estrutura limpa
            clean_tree = {}
            for k, v in tree.items():
                if isinstance(v, set):
                    clean_tree[k] = set([c for c in v if c and str(c).strip()])
                elif isinstance(v, list):
                    clean_tree[k] = set([c for c in v if c and str(c).strip()])
                else:
                    clean_tree[k] = set()
            tree = clean_tree
            # Garantir que todas as categorias apareçam
            all_children = set()
            for children in tree.values():
                for c in children:
                    all_children.add(c)
            # Se há chaves que não aparecem em nenhum lugar, colocar em ""
            if "" not in tree:
                tree[""] = set()
            for k in list(tree.keys()):
                if k != "" and k not in all_children:
                    tree[""].add(k)
            # Se "" ficou vazio mas há outras chaves, mover todas
            if not tree.get("") and tree:
                roots = [k for k in tree if k != ""]
                tree[""] = set(roots)

            content_width = 1020

            def render(parent_name, level, indent, visited=None):
                if visited is None:
                    visited = set()
                if level > 12:
                    return
                children = sorted([c for c in (tree.get(parent_name, set()) or set()) if c])
                for child in children:
                    if child in visited or child == parent_name or child == "":
                        continue
                    try:
                        bg_colors = [WHITE, GRAY_100, "#E0E0E0", "#D0D0D0"]
                        bg = bg_colors[min(level, len(bg_colors)-1)]
                        if level == 0:
                            prefix = "📁 "
                        elif level == 1:
                            prefix = "  └─ "
                        else:
                            prefix = "      └─ "
                        display_text = f"{prefix}{child}"

                        lbl = tk.Label(
                            self._org_frame, text=display_text, bg=bg, fg=GRAY_800,
                            font=("Segoe UI", 9, "bold" if level == 0 else "normal"),
                            padx=6, pady=3, cursor="hand2", relief="solid", borderwidth=1,
                            anchor="w",
                        )
                        lbl.place(x=10 + indent, y=self._current_y, width=max(120, content_width - (10 + indent) - 16))

                        lbl.bind("<Button-1>", lambda e, c=child, p=parent_name, w=lbl, lv=level: self._on_org_drag_start(e, c, p, w, lv))
                        lbl.bind("<ButtonRelease-1>", self._on_org_drag_end)
                        lbl.bind("<B1-Motion>", self._on_org_drag_motion)

                        self._category_items[lbl] = {"name": child, "parent": parent_name, "level": level}
                        self._current_y += 35 if level == 0 else 32
                    except Exception:
                        continue

                    nv = set(visited)
                    nv.add(child)
                    render(child, level + 1, indent + 26, nv)

            render("", 0, 0)

            content_height = max(getattr(self, "_current_y", 10) + 100, 220)
            if len(self._category_items) == 0:
                try:
                    tk.Label(
                        self._org_frame,
                        text="Nenhuma categoria encontrada para mostrar.\nVerifique o mapeamento de campos (família/categoria) ou o ficheiro selecionado.",
                        bg=GRAY_100, fg=GRAY_800, justify="left", padx=12, pady=12, wraplength=760,
                    ).place(x=12, y=12)
                    content_height = 140
                except Exception:
                    pass

            try:
                self._org_frame.configure(width=content_width, height=content_height)
            except Exception:
                pass
            try:
                if hasattr(self, "_org_window") and self._org_window:
                    self._org_canvas.itemconfigure(self._org_window, width=content_width)
            except Exception:
                pass

            self._org_frame.update_idletasks()
            self._org_canvas.update_idletasks()
            try:
                bbox = self._org_canvas.bbox("all")
                self._org_canvas.configure(scrollregion=bbox or (0, 0, content_width, content_height))
            except Exception:
                self._org_canvas.configure(scrollregion=(0, 0, content_width, content_height))
            try:
                self._org_canvas.yview_moveto(0)
            except Exception:
                pass
            _log(f"ok nodes={len(self._category_items)} roots={len(tree.get('', set()))} h={content_height}")
        except Exception as e:
            try:
                import traceback
                _log(f"ERR {e}\n{traceback.format_exc()}")
            except Exception:
                pass

    def _is_org_descendant(self, potential_parent, target_cat, _seen=None):
        """True se potential_parent está na subárvore de target_cat (evita ciclos)."""
        if not potential_parent or not target_cat:
            return False
        if _seen is None:
            _seen = set()
        if target_cat in _seen:
            return False
        _seen.add(target_cat)
        children = self._category_tree.get(target_cat, set()) or set()
        if potential_parent in children:
            return True
        for child in children:
            if self._is_org_descendant(potential_parent, child, _seen):
                return True
        return False

    def _org_level_bg(self, level):
        if level == 0:
            return WHITE
        if level == 1:
            return GRAY_100
        return "#E0E0E0"

    def _clear_org_drag_highlight(self):
        target = (self._drag_data or {}).get("hover_target")
        if target and target in self._category_items:
            try:
                lvl = self._category_items[target].get("level", 0)
                target.configure(relief="solid", borderwidth=1, bg=self._org_level_bg(lvl))
            except Exception:
                pass
        self._drag_data["hover_target"] = None

    def _on_org_drag_start(self, event, category, parent, widget, level):
        try:
            orig = widget.place_info()
        except Exception:
            orig = {}
        self._drag_data = {
            "item": widget,
            "category": category,
            "parent": parent,
            "level": level,
            "hover_target": None,
            "orig_place": orig,
            "last_motion_ts": 0.0,
        }
        try:
            widget.configure(relief="raised", borderwidth=2)
            widget.lift()
        except Exception:
            pass

    def _on_org_drag_motion(self, event):
        import time
        item = (self._drag_data or {}).get("item")
        if not item:
            return
        now = time.monotonic()
        if now - float(self._drag_data.get("last_motion_ts") or 0.0) < 0.03:
            return
        self._drag_data["last_motion_ts"] = now
        try:
            x = event.x_root - self._org_frame.winfo_rootx() - 10
            y = event.y_root - self._org_frame.winfo_rooty() - 10
            item.place_configure(x=x, y=y)
        except Exception:
            return
        target = None
        try:
            item.place_forget()
            self._org_frame.update_idletasks()
            widget_under = self.winfo_containing(event.x_root, event.y_root)
            if widget_under in self._category_items and widget_under is not item:
                target = widget_under
        except Exception:
            target = None
        finally:
            try:
                x = event.x_root - self._org_frame.winfo_rootx() - 10
                y = event.y_root - self._org_frame.winfo_rooty() - 10
                item.place_configure(x=x, y=y)
                item.lift()
            except Exception:
                pass
        if target is not self._drag_data.get("hover_target"):
            self._clear_org_drag_highlight()
            if target:
                try:
                    target.configure(relief="solid", borderwidth=2, bg="#FFF3CD")
                except Exception:
                    pass
                self._drag_data["hover_target"] = target

    def _on_org_canvas_release(self, event):
        if (self._drag_data or {}).get("item"):
            self._on_org_drag_end(event)

    def _on_org_drag_end(self, event):
        item = (self._drag_data or {}).get("item")
        cat = (self._drag_data or {}).get("category")
        old_parent = (self._drag_data or {}).get("parent")
        if not item or not cat:
            self._drag_data = {"item": None, "category": None, "parent": None, "level": 0, "hover_target": None, "orig_place": None, "last_motion_ts": 0.0}
            return

        self._clear_org_drag_highlight()
        target_widget = None
        try:
            item.place_forget()
            self._org_frame.update_idletasks()
            target_widget = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            target_widget = getattr(event, "widget", None)

        moved = False
        move_msg = None
        invalid_msg = None

        if target_widget in self._category_items and target_widget is not item:
            new_parent = self._category_items[target_widget]["name"]
            if new_parent == cat or old_parent == new_parent:
                pass
            elif self._is_org_descendant(new_parent, cat):
                invalid_msg = "Não pode mover uma categoria para dentro do seu próprio filho/subcategoria."
            else:
                if cat in (self._category_tree.get(old_parent) or set()):
                    self._category_tree[old_parent].discard(cat)
                self._category_tree.setdefault(new_parent, set()).add(cat)
                moved = True
                move_msg = f"'{cat}' movido para dentro de '{new_parent}'."
        elif target_widget in (self._org_canvas, self._org_frame, self._org_loading_overlay):
            if old_parent != "":
                if cat in (self._category_tree.get(old_parent) or set()):
                    self._category_tree[old_parent].discard(cat)
                self._category_tree.setdefault("", set()).add(cat)
                moved = True
                move_msg = f"'{cat}' movido para a categoria raiz/pai."

        orig_place = (self._drag_data or {}).get("orig_place") or {}
        self._drag_data = {"item": None, "category": None, "parent": None, "level": 0, "hover_target": None, "orig_place": None, "last_motion_ts": 0.0}

        if invalid_msg:
            restored = False
            try:
                if orig_place and item and item.winfo_exists():
                    item.place(**orig_place)
                    lvl = 0
                    restored = True
            except Exception:
                restored = False
            if not restored:
                self.after_idle(self._rebuild_org_tree)
            messagebox.showwarning("Aviso", invalid_msg, parent=self)
            return

        if moved:
            self.after_idle(self._rebuild_org_tree)
            if move_msg:
                self.after(50, lambda m=move_msg: messagebox.showinfo("Movido", m, parent=self))
        else:
            restored = False
            try:
                if orig_place and item and item.winfo_exists():
                    item.place(**orig_place)
                    info = self._category_items.get(item, {})
                    item.configure(relief="solid", borderwidth=1, bg=self._org_level_bg(info.get("level", 0)))
                    restored = True
            except Exception:
                restored = False
            if not restored:
                self.after_idle(self._rebuild_org_tree)

    def _expand_all(self):
        # Implementação para expandir (por enquanto rebuild força a exibição completa)
        self._rebuild_org_tree()
        messagebox.showinfo("Expandido", "Todas as categorias foram expandidas.", parent=self)

    def _collapse_all(self):
        # Implementação para esconder (colapsar)
        # Uma abordagem simples seria filtrar a árvore para mostrar apenas raízes
        # Precisa ser alinhado com a lógica de renderização
        messagebox.showinfo("Em desenvolvimento", "Funcionalidade de 'Esconder Todos' em implementação.", parent=self)

    # Compatibilidade com referências antigas (se existirem)
    def _on_drag_start(self, *args, **kwargs):
        return self._on_org_drag_start(*args, **kwargs)

    def _on_drag_motion(self, *args, **kwargs):
        return self._on_org_drag_motion(*args, **kwargs)

    def _on_drag_end(self, event):
        return self._on_org_drag_end(event)

    def _reset_widget_style(self, widget, level):
        try:
            widget.configure(relief="solid", borderwidth=1, bg=self._org_level_bg(level))
        except Exception:
            pass

    def _get_selected_category(self):
        return (self._drag_data or {}).get("category")

    def _edit_category_name(self, old_name):
        if not old_name:
            messagebox.showwarning("Atenção", "Selecione ou clique numa categoria para editar.", parent=self)
            return
        new_name = simpledialog.askstring("Editar categoria", "Novo nome da categoria:", initialvalue=old_name, parent=self)
        if new_name and new_name.strip() and new_name.strip() != old_name:
            # Atualizar visualmente
            for widget, info in getattr(self, '_category_items', {}).items():
                if info.get('name') == old_name:
                    if info.get('level', 0) == 0:
                        widget.configure(text=f"📁 {new_name.strip()}")
                    elif info.get('level', 0) == 1:
                        widget.configure(text=f"  └─ {new_name.strip()}")
                    else:
                        widget.configure(text=f"      └─ {new_name.strip()}")
                    info['name'] = new_name.strip()
                    break
            messagebox.showinfo("Editado", f"Categoria renomeada para '{new_name.strip()}'.\nUse 'Guardar organização' para aplicar.", parent=self)

    def _get_category_org_path(self):
        try:
            if getattr(sys, 'frozen', False):
                base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConversorJumpseller"
                base_dir.mkdir(parents=True, exist_ok=True)
                return base_dir / "category_organization.json"
        except Exception:
            pass
        return Path(__file__).parent / "category_organization.json"

    def _save_category_organization(self):
        try:
            tree_data = {}
            for parent, children in getattr(self, '_category_tree', {}).items():
                if isinstance(children, set):
                    tree_data[parent] = sorted(list(children))
                elif isinstance(children, list):
                    tree_data[parent] = sorted(children)
                else:
                    tree_data[parent] = []
            path = self._get_category_org_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tree_data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Guardado", "Organização de categorias guardada com sucesso.\nAs alterações serão aplicadas na próxima conversão.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar: {e}", parent=self)

    def _load_saved_category_organization(self):
        try:
            path = self._get_category_org_path()
            if not path.is_file():
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            tree = {}
            for k, v in data.items():
                if isinstance(v, list):
                    tree[k] = set(v)
                elif isinstance(v, set):
                    tree[k] = v
                else:
                    tree[k] = set()
            # Remover ciclos simples
            def clean_cycles():
                changed = True
                while changed:
                    changed = False
                    for parent, children in list(tree.items()):
                        for child in list(children):
                            if child == parent:
                                children.discard(child)
                                changed = True
                                continue
                            if child in tree and parent in tree.get(child, set()):
                                # Remover link direto para quebrar ciclo
                                children.discard(child)
                                changed = True
            clean_cycles()
            return tree
        except Exception:
            return None

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
            new_cats_parent = [v.get().strip() for v in self._cat_parent_vars]
            set_category_settings(
                new_categories=new_cats,
                new_categories_parent=new_cats_parent,
                apply_to_all=True,
                selected_prefix="",
                use_parent=True,
            )
        except Exception:
            # Guardar silencioso no mapeamento (sem alertas)
            pass

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
        ttk.Label(frm, text="alexsanderfer@gmail.com", font=("Segoe UI", 10)).pack(anchor="w")
        ttk.Label(frm, text="WhatsApp: +351 910 000 000", font=("Segoe UI", 10)).pack(anchor="w")

        ttk.Label(frm, text="Contacto", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        ttk.Label(frm, text="GitHub: github.com/alexsanderfer/conversor", font=("Segoe UI", 10)).pack(anchor="w")
        ttk.Label(frm, text="Releases: github.com/alexsanderfer/conversor/releases", font=("Segoe UI", 10)).pack(anchor="w")

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
        self.update_idletasks()
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
            self._set_drop_text(resumo, GREEN_100, GREEN_700, widget=self.drop_text_update)
            self.open_folder_btn.config(state="normal")
            self.open_folder_btn2.config(state="normal")
            messagebox.showinfo("Concluido", resumo, parent=self)
        except Exception as exc:
            self._set_drop_text(f"Erro inesperado: {exc}", "#FFEBEE", "#C62828", widget=self.drop_text_update)
            messagebox.showerror("Erro", f"Erro inesperado:\n{exc}", parent=self)
        finally:
            self.merge_btn.config(state="normal")

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

            formula = self._price_formula_var.get().strip()
            from field_mapping import get_active_profile
            if set_price_settings(profit_percentage=profit_pct, iva_percentage=iva_pct, shipping_cost=shipping, price_formula=formula, profile_name=get_active_profile()):
                messagebox.showinfo("Guardado", "Configurações de preços guardadas para este perfil.", parent=self)
            else:
                messagebox.showerror("Erro", "Não foi possível guardar as configurações de preços.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar: {e}", parent=self)

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
            try:
                set_active_profile(name)
                # Reload price settings for the new profile
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
                messagebox.showerror("Erro", f"Erro ao alterar perfil:\n{e}", parent=self)

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
        self.convert_btn.config(state="disabled")
        self.update_idletasks()
        try:
            out_dir = self.out_dir_var.get()
            exclude_unavailable = bool(getattr(self, "exclude_unavailable_var", None) and self.exclude_unavailable_var.get())
            n, out, removed = process_csv(raw, out_dir, exclude_unavailable=exclude_unavailable)
            self.last_output = Path(out)
            status_msg = f"Concluido: {n} linha(s) -> {self.last_output.name}"
            if exclude_unavailable and removed:
                status_msg += f" | Removidos indisponíveis: {removed}"
            self._set_drop_text(
                status_msg,
                GREEN_100, GREEN_700, widget=self._status_widget,
            )
            self.open_folder_btn.config(state="normal")
            info_msg = f"{n} linha(s) escrita(s) em:\n{out}"
            if exclude_unavailable:
                info_msg += f"\n\nProdutos indisponíveis removidos (stock 0 / not-available): {removed}"
            info_msg += "\n\nAbrir pasta do resultado abaixo."
            messagebox.showinfo("Concluido", info_msg, parent=self)
        except FileNotFoundError as exc:
            self._set_drop_text(str(exc), ERROR_BG, ERROR_FG, widget=self._status_widget)
            messagebox.showerror("Erro", str(exc), parent=self)
        except Exception as exc:
            self._set_drop_text(f"Erro inesperado: {exc}", ERROR_BG, ERROR_FG, widget=self._status_widget)
            messagebox.showerror("Erro", f"Erro inesperado:\n{exc}", parent=self)
        finally:
            self.convert_btn.config(state="normal")


if __name__ == "__main__":
    app = App()
    # Antes do mainloop: enquanto nao houver licenca valida, so se ve o
    # dialog de activacao. E preciso rodar o loop para o dialog funcionar.
    app._licensed = False
    app._last_license_message = ""
    app._ensure_license()
    app.mainloop()