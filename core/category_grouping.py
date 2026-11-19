"""
Motor de agrupamento automático de categorias por palavras-chave.

Reutiliza as regras padrão do classificador (`core.category_classifier`) para
sugerir categorias pai para as categorias únicas de um CSV de fornecedor.
Função pura: não escreve em ficheiros nem tem estado.
"""
from core.category_classifier import DEFAULT_RULES, _normalize


def suggest_groupings(unique_categories: list) -> dict:
    """Agrupa categorias únicas sob categorias pai sugeridas.

    Devolve {categoria_pai_sugerida: [categorias_agrupadas]} com as chaves
    ordenadas alfabeticamente e as listas de categorias ordenadas também.
    Categorias sem correspondência são IGNORADAS (não há chave "(sem área)").
    Uma categoria só pode pertencer a UMA área: a regra com maior pontuação
    (soma do comprimento das palavras-chave que casam) ganha; empate -> a
    regra que aparece primeiro em DEFAULT_RULES.
    """
    regras = []
    for regra in DEFAULT_RULES:
        categoria_pai = (regra.get("category") or "").strip()
        if not categoria_pai:
            continue
        palavras_chave = []
        for kw in regra.get("keywords", []):
            normalizada = _normalize(kw)
            if normalizada:
                palavras_chave.append(normalizada)
        if palavras_chave:
            regras.append((categoria_pai, palavras_chave))

    agrupamentos = {}
    for categoria in unique_categories or []:
        if not isinstance(categoria, str) or not categoria.strip():
            continue
        texto = _normalize(categoria)
        if not texto:
            continue

        # Em empate de pontuação, a regra que aparece primeiro em
        # DEFAULT_RULES ganha (por isso o `>` em vez de `>=`).
        melhor_categoria = None
        melhor_pontuacao = 0
        for categoria_pai, palavras_chave in regras:
            pontuacao = 0
            for kw in palavras_chave:
                if kw in texto:
                    pontuacao += len(kw)
            if pontuacao > melhor_pontuacao:
                melhor_categoria = categoria_pai
                melhor_pontuacao = pontuacao

        if melhor_categoria is None:
            continue

        if categoria in agrupamentos.get(melhor_categoria, []):
            continue
        agrupamentos.setdefault(melhor_categoria, []).append(categoria)

    return {
        pai: sorted(agrupamentos[pai])
        for pai in sorted(agrupamentos.keys())
    }
