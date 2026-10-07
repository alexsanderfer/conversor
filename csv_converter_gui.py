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
import tkinter as tk
import unicodedata
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import DND_FILES, Tk

from license_dialog import LicenseDialog
from license_manager import check_license, load_license_state
from stripe_integration import open_stripe_checkout
from updater import check_for_updates
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
    price = preco * 1.40 * 1.23
    return str(round(price, 2))


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


def build_description(row: dict) -> str:
    parts = []
    for i in range(1, 7):
        val = row.get(f"desc{i}", "") or ""
        for linha in re.split(r"[\r\n]+", val):
            cleaned = clean_text(linha)
            if cleaned:
                parts.append(cleaned)
    return ". ".join(parts)


def build_categories(row: dict) -> str:
    familia = row.get("familia_principal", "").strip()
    sub_familia = row.get("sub_familia", "").strip()
    sub_sub_familia = row.get("sub_sub_familia", "").strip()
    categories = []
    if familia:
        categories.append(familia)
    if sub_familia:
        categories.append(f"{familia}/{sub_familia}")
    if sub_sub_familia:
        categories.append(f"{familia}/{sub_familia}/{sub_sub_familia}")
    return ",".join(categories)


def convert_row(row: dict) -> dict:
    dest_row = OrderedDict()
    for dest_col in DEST_COLUMNS:
        dest_row[dest_col] = ""
    name = row.get("design", "").strip()
    if name.startswith("=") and len(name) > 1:
        name = name[1:].strip()
    dest_row["Permalink"] = ""
    dest_row["Name"] = name
    dest_row["Description"] = build_description(row)
    dest_row["Meta Title"] = clean_text(name)
    dest_row["Meta Description"] = build_description(row)
    width, length, height = parse_dimensions(row.get("dimensoes", ""))
    dest_row["Width"] = width
    dest_row["Length"] = length
    dest_row["Height"] = height
    dest_row["Brand"] = row.get("marca", "").strip()
    dest_row["Barcode"] = row.get("codigo", "").strip()
    dest_row["Categories"] = build_categories(row)
    dest_row["Images"] = row.get("imagem", "").strip()
    dest_row["Digital"] = "NO"
    dest_row["Featured"] = "NO"
    stock_val = parse_stock(row.get("stock", ""))
    dest_row["Status"] = "available" if stock_val > 0 else "not-available"
    dest_row["SKU"] = row.get("ref", "").strip()
    dest_row["Weight"] = row.get("peso", "").strip()
    dest_row["Cost per item"] = ""
    dest_row["Compare at price"] = ""
    dest_row["Stock"] = str(stock_val)
    dest_row["Stock Unlimited"] = "NO"
    dest_row["Stock Notification"] = "YES"
    dest_row["Stock Threshold"] = ""
    dest_row["Price"] = _calc_price(row.get("preco", ""))
    return dest_row


def get_output_path(input_path: str, output_dir: str = None) -> str:
    if output_dir is None:
        output_dir = str(Path.home() / "Downloads")
    input_name = Path(input_path).stem
    output_name = f"{input_name}_jumpseller.csv"
    return os.path.join(output_dir, output_name)


def process_csv(input_path: str, output_dir: str = None):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Arquivo nao encontrado: '{input_path}'")
    output_path = get_output_path(input_path, output_dir)
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
            rows.append(convert_row(row))
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
    return len(rows), output_path


# ---------------------------------------------------------------------------
# ATUALIZACAO DA LOJA
# ---------------------------------------------------------------------------
STATE_FILENAME = "_jumpseller_precos.json"


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
            out.append((convert_row(row), _parse_pt_number(row.get("preco", ""))))
    return out


def merge_update(export_path: str, fornecedor_path: str, output_dir: str):
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

    for row, preco_origem in fornecedor_rows:
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
                    row[col] = (existing[col] or "").strip()
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
    n_novos = len(fornecedor_rows) - n_atualizados
    n_intactos = sum(len(v) for v in by_sku.values()) - n_atualizados
    return output_path, n_atualizados, n_novos, n_intactos


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
# GUI
# ---------------------------------------------------------------------------

class App(Tk):
    def __init__(self):
        super().__init__()
        from tkinterdnd2 import TkinterDnD
        TkinterDnD.require(self)
        self.title("Conversor CSV → Jumpseller")
        self.geometry("620x480")
        self.resizable(False, False)
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

        self.tab_novo = ttk.Frame(self.tabs, padding=8)
        self.tab_update = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.tab_novo, text="  Novo ficheiro  ")
        self.tabs.add(self.tab_update, text="  Atualizar loja  ")

        self._build_tab_novo()
        self._build_tab_update()
        self._build_footer()

    # -- logo -----------------------------------------------------------

    def _load_logo(self):
        for name in ("logo.png", "logo.gif"):
            p = ASSETS / name
            if p.is_file():
                img = tk.PhotoImage(file=str(p))
                lbl = tk.Label(self, image=img, bg=WHITE)
                lbl.image = img  # keep reference
                return lbl
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
            self.tab_novo, height=4, relief="sunken",
            bg=GRAY_100, font=("Segoe UI", 10), borderwidth=1, wrap="word",
        )
        self.drop_text.pack(fill="both", expand=True, pady=(8, 8))
        self.drop_text.drop_target_register(DND_FILES)
        self.drop_text.dnd_bind("<<Drop>>", self._on_drop)
        self._set_drop_text(
            "Arraste um arquivo .csv aqui, ou clique em 'Escolher arquivo…'",
            GRAY_100, GRAY_800,
            widget=self.drop_text,
        )
        self._status_widget = self.drop_text

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
        self.convert_btn.pack(side="right")
        self.path_entry.bind("<Return>", lambda ev: self._convert())

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
            self.tab_update, height=4, relief="sunken",
            bg=GRAY_100, font=("Segoe UI", 10), borderwidth=1, wrap="word",
        )
        self.drop_text_update.pack(fill="both", expand=True, pady=(0, 8))
        style_drop_area(self.drop_text_update)

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
        self.merge_btn.pack(side="right")

    # -- handlers -------------------------------------------------------

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Selecione o CSV de entrada",
            filetypes=[("CSVs", "*.csv"), ("Todos os arquivos", "*")],
        )
        if path:
            self.path_var.set(path)
            self._update_drop_text(path)

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
            out, n_atual, n_novos, n_intactos = merge_update(export_raw, forn_raw, out_dir)
            self.last_output = Path(out)
            resumo = (
                f"Atualizados: {n_atual}\nNovos: {n_novos}\n"
                f"Intactos (so na loja): {n_intactos}\n\nFicheiro: {out}"
            )
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
            on_cancel=lambda: None,
        )
        self.wait_window(dialog.win)
        return self._licensed

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

    def _open_stripe_checkout(self):
        """Botão 'Comprar Licença': abre a página de pagamento Stripe."""
        from stripe_integration import open_stripe_checkout
        open_stripe_checkout()

    def _check_for_updates(self):
        """Botão 'Verificar Atualizações': verifica se há novas versões."""
        from updater import check_for_updates
        check_for_updates(show_message=True, parent=self)

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
            n, out = process_csv(raw, out_dir)
            self.last_output = Path(out)
            self._set_drop_text(
                f"Concluido: {n} linha(s) → {self.last_output.name}",
                GREEN_100, GREEN_700, widget=self._status_widget,
            )
            self.open_folder_btn.config(state="normal")
            messagebox.showinfo("Concluido",
                                f"{n} linha(s) escrita(s) em:\n{out}\nAbrir pasta do resultado abaixo.",
                                parent=self)
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