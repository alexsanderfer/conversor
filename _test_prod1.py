import csv, re, sys
from collections import OrderedDict

# Read mapping/category settings as the user used: "Loja INFORMÁTICA" as parent
parent_cat = "Loja INFORMÁTICA"
apply_to_all = True
use_parent = True

def normalize(val):
    return re.sub(r'\s*/\s*', ' e ', (val or "").strip())

def build_categories(familia, sub_familia, sub_sub_familia=""):
    familia = normalize(familia); sub_familia = normalize(sub_familia); sub_sub_familia = normalize(sub_sub_familia)
    categories = []
    if familia:
        categories.append(familia)
    if sub_familia:
        cat2 = f"{familia}/{sub_familia}"
        parts = cat2.split('/')
        if len(parts) > 4: cat2 = '/'.join(parts[:4])
        categories.append(cat2)
    if sub_sub_familia:
        cat3 = f"{familia}/{sub_familia}/{sub_sub_familia}"
        parts = cat3.split('/')
        if len(parts) > 4: cat3 = '/'.join(parts[:4])
        categories.append(cat3)
    if apply_to_all and categories and use_parent:
        result = [parent_cat]
        for cat_path in categories:
            cp = (cat_path or "").strip().strip("/")
            if not cp: continue
            prefixed = f"{parent_cat}/{cp}"
            if prefixed not in result: result.append(prefixed)
        return ",".join(result)
    return ",".join(categories)

path = r"C:\Users\Alexsander\IdeaProjects\conversor\csv_examples\produtos (1).csv"
with open(path, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f, delimiter=';')
    rows = list(reader)

print(f"Total linhas de dados: {len(rows)}")
# Find lines resembling user's examples
for i, row in enumerate(rows, start=2): # header is line 1
    cat = (row.get('categoria') or '').strip()
    sub = (row.get('subcategoria') or '').strip()
    name = (row.get('nome') or '').strip()[:60]
    orig = f"{cat} / {sub}" if sub else cat
    out = build_categories(cat, sub)
    mark = ""
    if "Smartphones" in cat or "Smartphones" in sub or "Recondicionados" in cat or "AIO" in sub or "All-in-One" in sub:
        mark = "  <-- EXEMPLO"
    if mark or i <= 12:
        print(f"L{i}: {orig}")
        print(f"  -> {out}{mark}")
