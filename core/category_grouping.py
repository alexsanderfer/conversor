"""
Motor de agrupamento automático de categorias por palavras-chave.

Reutiliza as regras padrão do classificador (`core.category_classifier`) para
sugerir categorias pai para as categorias únicas de um CSV de fornecedor.
Função pura: não escreve em ficheiros nem tem estado.
"""
from core.category_classifier import DEFAULT_RULES, _normalize


def _texto_para_tokens(texto: str) -> list:
    """Divide o texto normalizado em tokens (letras/dígitos).

    O separador hierárquico ``>`` e a pontuação já foram convertidos em espaço
    por ``_normalize``, por isso basta dividir pelo que não é letra/dígito.
    """
    return [token for token in _normalize(texto).split() if token]


def _palavra_casa(palavra: str, tokens: list) -> bool:
    """Indica se a keyword (já normalizada) casa como palavra inteira.

    A keyword pode ter várias palavras ("cabo rede", "cadeira gamer"); nesse
    caso só casa se aparecer a sequência completa de palavras. Palavras
    simples aceitam plural flexionado ("computador" casa em "computadores",
    "chave" em "chaves") mas nunca substring de outra palavra ("ram" não casa
    em "ferramentas").
    """
    if " " not in palavra:
        for token in tokens:
            if token == palavra:
                return True
            if (
                len(palavra) >= 3
                and len(token) > len(palavra)
                and token.startswith(palavra)
                and token[len(palavra):] in ("s", "es")
            ):
                return True
        return False

    partes = palavra.split()
    return any(
        tokens[i:i + len(partes)] == partes
        for i in range(len(tokens) - len(partes) + 1)
    )


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
        palavras_chave = [
            _normalize(kw)
            for kw in regra.get("keywords", [])
            if _normalize(kw)
        ]
        if palavras_chave:
            regras.append((categoria_pai, palavras_chave))

    agrupamentos = {}
    for categoria in unique_categories or []:
        if not isinstance(categoria, str) or not categoria.strip():
            continue
        tokens = _texto_para_tokens(categoria)
        if not tokens:
            continue

        # Em empate de pontuação, a regra que aparece primeiro em
        # DEFAULT_RULES ganha (por isso o `>` em vez de `>=`).
        melhor_categoria = None
        melhor_pontuacao = 0
        for categoria_pai, palavras_chave in regras:
            pontuacao = sum(
                len(kw)
                for kw in palavras_chave
                if _palavra_casa(kw, tokens)
            )
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
