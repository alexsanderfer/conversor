# Confirmar fornecedor ao converter e lista de categorias não mapeadas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Ao clicar em Converter, abrir um diálogo de confirmação que mostre o fornecedor ativo e o respetivo prefixo SKU, permitindo confirmar ou escolher outro perfil antes de converter, para evitar que um CSV de um fornecedor fique com o prefixo de outro. (2) Na secção de mapeamento avançado (aba Categorias), a lista "CATEGORIAS ÚNICAS" passa a mostrar apenas as categorias que ainda NÃO foram mapeadas com uma regra de keyword, e quando se cria uma nova regra, essa categoria deixa de aparecer na lista, para o utilizador saber quando o mapeamento está concluído.

**Architecture:** Dois ajustes pontuais em `gui/csv_converter_gui.py`, sem novos ficheiros nem dependências. (1) Em `_convert`, antes de chamar `process_csv`, abrir um `Toplevel` modal com o fornecedor ativo, o prefixo SKU desse perfil e os restantes perfis disponíveis; o utilizador confirma (usa o prefixo do perfil escolhido) ou cancela. Se mudar de fornecedor no diálogo, esse perfil passa a ser o ativo (`set_active_profile`). (2) Calcular o conjunto de categorias únicas já mapeadas (quando `apply_keyword_rules(categoria, "")` devolve um pai) e mostrá-las fora da lista de não-mapeadas; a coluna 1 da aba Categorias mostra só as não-mapeadas, com o título a dizer quantas faltam. Ao adicionar uma regra em `_add_advanced_keyword_rule`, recalcular e refrescar a lista.

**Tech Stack:** Python 3.14, Tkinter/ttk (mesmo padrão de diálogo de `_open_massive_origem_selector_dialog` e de `_open_grouping_suggestions_dialog`).

**Spec:** CLAUDE.md + requisitos do utilizador (dia 2026-11-20).

## Global Constraints

- Python 3.14; Tkinter/ttk para UI.
- Sem dependências novas (não usar scikit-learn, numpy, etc.).
- Todos os textos visíveis via `translate(texto, self.language)`.
- Não alterar `core/category_grouping.py` nem a lógica de negócio de `apply_keyword_rules`/`apply_compiled_keyword_rules`.
- `build/` e `dist/` nunca são commitados.
- Não usar `--novo-segredo` nem tocar em ficheiros de licença/segredo.

## Review Focus

1. **Prefixo errado:** confirmar que o diálogo não deixa converter sem escolher/confirmar o fornecedor, e que mudar de fornecedor no diálogo o torna o ativo para o resto da sessão.
2. **Lista de não-mapeadas:** garantir que as categorias mapeadas (por regra de keyword exata ou por substring) deixam de aparecer na coluna única, e que o título reflete as que faltam.
3. **Recálculo após criar regra:** criar uma regra deve fazer a categoria desaparecer da lista imediatamente, sem recarregar o CSV.
4. **Vazio:** quando não há categorias não-mapeadas, mostrar mensagem apropriada em vez de lista vazia sem contexto.
5. **No Regression:** a conversão (`process_csv`) e a lista original de categorias (para a coluna de subcategorias e para o diálogo de agrupamento) devem continuar a funcionar igual.

---

### Task 1: Diálogo de confirmação do fornecedor/prefixo ao converter

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: `get_active_profile()`, `get_sku_prefix(name)`, `list_profiles()`, `set_active_profile(name)`.
- Produces: um novo método `_confirmar_fornecedor_ao_converter() -> bool | None` que devolve `True` (prosseguir com o fornecedor escolhido), `False` (cancelar) ou `None` (erro).

- [ ] **Step 1: Implementar o diálogo de confirmação** em `_convert`, antes de `process_csv`.

- [ ] **Step 2: Testar manualmente** (sem automatizar cliques): verificar que mostra o fornecedor ativo e o respetivo prefixo, que mudar de fornecedor no diálogo o torna ativo, e que cancelar não converte.

- [ ] **Step 3: Commit**

```
git add gui/csv_converter_gui.py
git commit -m "fix: confirmar fornecedor e prefixo SKU antes de converter"
```
Mensagem a terminar com `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

---

### Task 2: Lista de categorias não mapeadas na aba Categorias

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: `get_keyword_rules()` (e `apply_keyword_rules`), `self._unique_categories` (já populado por `update_categories`).
- Produces: um novo método `_categorias_nao_mapeadas() -> list[str]` e a coluna única da aba Categorias passa a mostrar apenas essas, com o título `CATEGORIAS ÚNICAS SEM MAPEAMENTO (N de M)`; quando N == 0 mostra "(todas as categorias mapeadas)".

- [ ] **Step 1: Implementar o cálculo de não-mapeadas** (uma categoria está mapeada se `apply_keyword_rules(categoria, "")` devolve um pai não vazio).

- [ ] **Step 2: Implementar a coluna única com as não-mapeadas** e atualizar o título com a contagem; manter a coluna 2 (únicas + subcategorias) completa.

- [ ] **Step 3: Recarregar a lista ao criar regra** em `_add_advanced_keyword_rule` (chamar o refrescar da coluna única) para a categoria mapeada desaparecer imediatamente.

- [ ] **Step 4: Commit**

```
git add gui/csv_converter_gui.py
git commit -m "feat: lista de categorias não mapeadas no mapeamento avançado"
```
Mensagem a terminar com `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

---

## Decisões tomadas (a validar com o utilizador)

1. **Diálogo de confirmação:** aberto sempre ao clicar em Converter (não só quando há divergência), como pedido pelo utilizador.
2. **Categoria "mapeada":** considerada mapeada quando existe uma regra avançada (formato novo `{category, subcategory, parent_category}` ou legado `keywords`) que `apply_keyword_rules` aplica a essa categoria (ou a uma subcategoria dela). Isto pode gerar falsos positivos/negativos por substring (ex.: "ram" em "ferramentas"), mas é a mesma semântica já usada na conversão — consistente.
3. **A coluna única mostra só não-mapeadas; a coluna 2 mantém todas as subcategorias** (é para consulta). O utilizador escolheu "a lista única passa a mostrar só as não mapeadas".

---

## Pendente

- [ ] O utilizador rever este plano e confirmar que capta o que quer. Se sim, usar execução subagent-driven (uma subagent por tarefa, revisão após cada uma).
