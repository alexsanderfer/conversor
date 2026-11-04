"""
Classificador automático de categorias baseado em palavras-chave.
"""
import json
import os
import re
import unicodedata
from pathlib import Path
import sys

# Regras padrão
DEFAULT_RULES = [
    {"keywords": ["rato", "mouse", "teclado", "webcam", "ssd", "disco", "fonte", "placa", "processador", "memoria", "ram", "router", "switch", "cabo rede", "hub", "impressora", "scanner", "monitor", "portatil", "notebook", "computador", "cadeira gamer"], "category": "Informática", "priority": 10},
    {"keywords": ["luminaria", "lampada", "candeeiro", "fita led", "plafon", "abajur", "holofote", "projetor led"], "category": "Iluminação", "priority": 10},
    {"keywords": ["torneira", "regador", "mangueira", "aspersor", "vaso", "semente", "adubo", "ferramenta jardim"], "category": "Jardinagem", "priority": 10},
    {"keywords": ["sofa", "cadeira", "mesa", "armario", "estante", "cama", "colchao", "travesseiro", "almofada", "tapete"], "category": "Móveis", "priority": 10},
    {"keywords": ["panela", "frigideira", "talher", "prato", "copo", "taça", "colher", "garfo", "faca", "bule", "liquidificador", "batedeira"], "category": "Casa e Cozinha", "priority": 10},
    {"keywords": ["camiseta", "calca", "vestido", "camisa", "sapato", "tenis", "bota", "meia", "cueca", "soutien", "jaqueta", "casaco"], "category": "Moda", "priority": 10},
    {"keywords": ["shampoo", "creme", "perfume", "desodorante", "sabonte", "condicionador", "batom", "base", "rímel"], "category": "Beleza e Cuidados", "priority": 10},
    {"keywords": ["bola", "raquete", "bicicleta", "capacete", "luva", "halter", "barra", "esteira"], "category": "Desporto", "priority": 10},
    {"keywords": ["brinquedo", "boneca", "carrinho", "puzzle", "jogo", "lego"], "category": "Brinquedos", "priority": 10},
    {"keywords": ["chave", "martelo", "serrote", "parafuso", "porca", "broca", "furadeira", "serra"], "category": "Ferramentas", "priority": 10},
]

def _config_dir():
    try:
        if getattr(sys, 'frozen', False):
            base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ConversorJumpseller"
            base_dir.mkdir(parents=True, exist_ok=True)
            return base_dir
    except Exception:
        pass
    return Path(__file__).parent

def _rules_path():
    return _config_dir() / "category_classification_rules.json"

def _normalize(text: str) -> str:
    if not text:
        return ""
    text = str(text).strip().lower()
    try:
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
    except Exception:
        pass
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def load_rules():
    path = _rules_path()
    if not path.is_file():
        data = {"rules": DEFAULT_RULES, "learned": [], "enabled": True}
        save_rules(data)
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"rules": DEFAULT_RULES, "learned": [], "enabled": True}
        if "rules" not in data:
            data["rules"] = DEFAULT_RULES
        if "learned" not in data:
            data["learned"] = []
        if "enabled" not in data:
            data["enabled"] = True
        return data
    except Exception:
        data = {"rules": DEFAULT_RULES, "learned": [], "enabled": True}
        save_rules(data)
        return data

def save_rules(data):
    path = _rules_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def classify_product(product_name: str, current_category: str = ""):
    if not product_name:
        return ""
    data = load_rules()
    if not data.get("enabled", True):
        return ""
    # Se já tem categoria do fornecedor e não está vazia, não sobrescrever
    if current_category and str(current_category).strip():
        return ""
    
    norm_name = _normalize(product_name)
    if not norm_name:
        return ""
    
    # Verificar aprendizagens primeiro (maior prioridade)
    learned = data.get("learned", [])
    for item in learned:
        if not item.get("category"):
            continue
        keywords = item.get("keywords", [])
        if not keywords:
            continue
        matches = 0
        for kw in keywords:
            nkw = _normalize(kw)
            if nkw and nkw in norm_name:
                matches += 1
        if matches > 0 and matches >= len(keywords) * 0.5:  # Pelo menos 50% das keywords
            return item["category"]
    
    # Verificar regras padrão
    rules = data.get("rules", DEFAULT_RULES)
    best_match = None
    best_score = 0
    best_priority = -1
    
    for rule in rules:
        category = rule.get("category", "").strip()
        if not category:
            continue
        keywords = rule.get("keywords", [])
        priority = rule.get("priority", 0)
        score = 0
        for kw in keywords:
            nkw = _normalize(kw)
            if not nkw:
                continue
            if nkw in norm_name:
                score += len(nkw)  # Palavras mais longas têm mais peso
        if score > best_score or (score == best_score and priority > best_priority):
            best_score = score
            best_priority = priority
            best_match = category
    
    if best_match and best_score > 0:
        return best_match
    return ""

def learn_from_product(product_name: str, category: str):
    if not product_name or not category:
        return False
    data = load_rules()
    norm_name = _normalize(product_name)
    # Extrair palavras-chave significativas (mais de 3 caracteres)
    words = [w for w in norm_name.split() if len(w) > 3]
    if not words:
        return False
    # Pegar até 3 palavras mais relevantes
    keywords = words[:3]
    
    learned = data.get("learned", [])
    # Verificar se já existe
    for item in learned:
        if item.get("category") == category and set(item.get("keywords", [])) == set(keywords):
            return True
    learned.append({
        "keywords": keywords,
        "category": category,
        "product_example": product_name[:50]
    })
    data["learned"] = learned[-100:]  # Limitar a 100 aprendizagens
    return save_rules(data)
