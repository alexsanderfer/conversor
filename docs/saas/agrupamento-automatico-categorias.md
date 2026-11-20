# Agrupamento Automático de Categorias — guia de implementação para o SaaS

> Documento de transferência: a funcionalidade foi implementada primeiro no
> desktop (`conversor`, Python/Tkinter). Este README descreve o comportamento
> e a arquitetura para ser reproduzida no SaaS. Deve ser adaptado à stack do
> SaaS (a parte "Notas para o SaaS" assinala os pontos de decisão).

## 1. Problema

Os fornecedores enviam CSVs com categorias próprias, com granularidade e
vocabulário que variam de fornecedor para fornecedor. Quem importa precisa de
agrupar essas categorias em categorias pai coerentes com a loja (por exemplo,
todas as categorias relacionadas com informática ficarem sob
`Loja de Informática`).

Fazer isto à mão é lento e inconsistente. O objetivo é o sistema **sugerir**
os agrupamentos automaticamente e o utilizador **limitarem-se a ver e aprovar**
(e a retirar o que estiver mal). É o mesmo padrão de "sugestão + aprovação" que
se quer usar com IA no SaaS: o motor propõe, o humano decide.

## 2. Solução

Um motor de correspondência por palavras-chave que, a partir da lista de
categorias únicas de um fornecedor, devolve os agrupamentos sugeridos:

```
{ "Informática": ["Informática", "Informática > Portáteis", "Acessórios > Rato"], ... }
```

Cada categoria é atribuída a **uma só** área. A atribuição é feita pelo motor
de regras existente (`core/category_classifier.py` no desktop), que já cobre
as áreas principais (Informática, Iluminação, Jardinagem, Móveis, Casa e
Cozinha, Moda, Beleza e Cuidados, Desporto, Brinquedos, Ferramentas) e
aprende com os casos que o utilizador corrige.

O utilizador vê as sugestões, desmarca o que não quer, e aprova. Só aí as
regras de agrupamento ficam gravadas e passam a ser aplicadas na conversão.

## 3. Arquitetura (desktop)

```
CSV carregado
   │
   ▼
lista de categorias únicas  ──────────────┐
   │                                      │
   ▼                                      ▼
core/category_classifier.py      core/category_grouping.py
  DEFAULT_RULES (palavras-chave)    suggest_groupings(categorias) -> {area: [cats]}
  _normalize() (NFKD, sem acentos)        │
   │                                      ▼
   │                              Diálogo "Sugestões de Agrupamento"
   │                              (Listbox multi-seleção por área = aprovação)
   │                                      │
   │                                      ▼
   │                              _apply_grouping_suggestions()
   │                                      │
   │                                      ▼
   │                              core/field_mapping.py
   │                              save_massive_category_rule(...)
   │                                      │
   ▼                                      ▼
 conversão usa as regras  ◄────  regra massiva por área
```

Peças novas ( desktop):

| Ficheiro | Responsabilidade |
|---|---|
| `core/category_grouping.py` | Motor puro: `suggest_groupings(unique_categories: list) -> dict`. Sem I/O, sem Tkinter, testável de forma isolada. |
| `gui/csv_converter_gui.py` (aba CATEGORIAS M) | Botão `Analisar Sugestões`, diálogo de sugestões com seleção, `_apply_grouping_suggestions()`. |
| `tests/test_category_grouping.py` | Testes do motor. |

O motor **reutiliza** `core/category_classifier.py` (não o duplica): as
palavras-chave e a normalização de texto já lá estavam, e o classificador já é
usado no fluxo de conversão.

## 4. Regras de negócio do motor

1. **Correspondência por palavras-chave** contra as categorias (normalizadas:
   minúsculas, sem acentos, sem pontuação).
2. **Uma área por categoria**: quando várias áreas casam, ganha a que tiver
   maior pontuação (soma do comprimento das palavras-chave que casaram);
   empate → a regra que aparece primeiro em `DEFAULT_RULES`.
3. **Categorias sem correspondência não são sugeridas** (não há chave
   "Outros"/"Sem área"). O utilizador trata-as manualmente.
4. **Entrada vazia → dicionário vazio.**
5. **Ordenação**: chaves e listas de categorias ordenadas alfabeticamente,
   para a UI ser estável entre execuções.
6. **Sem persistência no motor**: é uma função pura; quem grava é a camada de
   regras (`save_massive_category_rule`).

## 5. Comportamento na UI

1. O utilizador carrega o CSV na aba CATEGORIAS M.
2. Clica em `Analisar Sugestões`.
3. Surge um diálogo com uma secção por área sugerida; em cada secção, a
   `Listbox` lista as categorias propostas, **selecionadas por omissão**
   (a aprovação é a norma, a exclusão é a exceção — é o que torna a tarefa
   rápida quando a sugestão está certa).
4. O utilizador desmarca o que estiver mal e carrega em `Aprovar Selecionadas`.
5. São gravadas regras massivas (uma por área) e a lista de regras da aba
   reflete o resultado.

A seleção ser a aprovação reduz o número de cliques quando a sugestão está
certa, mas **não** é uma garantia de correção: com o motor de palavras-chave,
a qualidade depende de as categorias do fornecedor usarem o vocabulário das
regras. No SaaS, com IA, a taxa de acerto sobe — e é exatamente por isso que a
revisão continua a ser obrigatória.

Se não houver sugestões, mostra-se um aviso informativo em vez do diálogo.

## 6. Notas para o SaaS

O desktop usa um motor de palavras-chave. No SaaS, o mesmo fluxo pode ser
feito com um modelo de linguagem, mantendo a forma (não o motor):

- **Manter a forma do contrato**: entrada = lista de categorias únicas;
  saída = `{categoria_pai: [categorias]}`. É o que a UI e a gravação esperam,
  e é o que permite trocar o motor sem tocar na interface.
- **A IA como motor, não como novidade de interface**: o valor está em o
  utilizador só ter de rever. Manter a aprovação explícita (desmarcar em vez de
  marcar) e a regra gravada por área.
- **Candidato natural**: o SaaS já tem as categorias do fornecedor e a
  nomenclatura da loja; um prompt com essas duas listas pede os agrupamentos.
  Tratar a resposta como **sugestão** (validar contra a lista real, descartar
  categorias inexistentes) e nunca aplicar automaticamente.
- **Regras de salvamento**: no SaaS, as regras gravadas devem ter o mesmo
  formato (`description`, `source_categories`, `parent_category`, `priority`)
  para a conversão e a atualização da loja continuarem a funcionar sem mudanças.
- **Custos e latência**: no SaaS a análise deve correr em background (tarefa
  assíncrona com estado visível), ao contrário do desktop, onde é síncrona
  porque a lista é pequena e o motor é instantâneo.

## 7. Testes a reproduzir no SaaS

- Agrupa categorias corretamente por palavra-chave.
- Categorias sem correspondência não aparecem em nenhuma área.
- Lista vazia → sem sugestões (não erro).
- Categoria ambígua fica só na área de maior pontuação.
- Chaves e listas ordenadas.
- (UI) Diálogo não abre quando não há sugestões.
- (UI) Aprovar sem nenhuma categoria selecionada não grava regra.

---

# (Anexo) Confirmação de fornecedor e lista de pendentes — v0.5.10

Duas correções de usabilidade feitas no desktop em novembro de 2026, que se
aplicam tal ao SaaS.

## A. Confirmar o fornecedor antes de converter

**Problema real relatado pelo utilizador:** o CSV era carregado de um
fornecedor estando outro ativo, e o CSV convertido ficava com o prefixo SKU do
fornecedor errado (ex.: CSV da Viptrónica com o prefixo `GRE-` da GreenFever).
O prefixo vai para o SKU de todos os produtos, pelo que o erro propaga-se para
a loja.

**Solução no desktop:** ao clicar em Converter, abre um diálogo modal com o
fornecedor ativo, o respetivo prefixo SKU e a lista de perfis; o utilizador
confirma (usa o prefixo do perfil escolhido, que passa a ser o ativo) ou
cancela. Cancelar não converte.

**No SaaS:**
- **Confirmar sempre**, não apenas quando houver divergência — o custo de um
  clique é inferior ao custo de um lote com o prefixo errado.
- Mostrar o **prefixo** em vez do nome do fornecedor: é o prefixo que o
  utilizador consegue verificar contra o resultado, e é o que está em causa.
- Se o SaaS associa o CSV a um fornecedor por upload/pasta, mostrar essa
  associação e permitir corrigi-la no diálogo.
- Regra de bolso: o prefixo aplicado deve ser sempre lido **no momento da
  conversão** (`get_sku_prefix(perfil_ativo)`), nunca guardado em variável antes
  do diálogo.

## B. Lista das categorias por mapear

**Problema real relatado pelo utilizador:** com muitas categorias, é fácil
esquecer de mapear algumas, e não havia forma de saber quais ficaram por
mapear.

**Solução no desktop:** a lista de categorias únicas do mapeamento avançado
passa a mostrar apenas as que ainda não têm regra, com o título
`CATEGORIAS ÚNICAS SEM MAPEAMENTO (N de M)`. Criar uma regra faz a categoria
desaparecer; remover a regra fá-la reaparecer. Quando a lista fica vazia, o
mapeamento está concluído.

**No SaaS:**
- Manter a lista de "por mapear" como indicador de progresso, não como
  obstáculo: não bloquear a conversão por categorias por mapear.
- O critério de "já mapeada" deve ser o **mesmo** que a conversão usa. No
  desktop foi preciso alinhar isto: a lista inicial usava `apply_keyword_rules`
  (que ignora regras com subcategoria) e passava a usar as regras compiladas
  (`apply_compiled_keyword_rules`), incluindo as subcategorias. Sem este
  alinhamento, categorias já mapeadas continuavam listadas como pendentes.
- Útil no SaaS: um contador por fornecedor ("faltam 7") na listagem de
  fornecedores, derivado do mesmo critério.

## Testes a reproduzir no SaaS (anexo)

- Com um fornecedor ativo e um CSV de outro, o diálogo mostra o prefixo do
  ativo e, ao confirmar com outro perfil, o prefixo aplicado é o desse perfil.
- Cancelar o diálogo não produz CSV de saída.
- Com regras de subcategoria, a categoria pai não fica listada como pendente.
- Remover uma regra volta a mostrar a categoria na lista de pendentes.
- Com todas as categorias mapeadas, a lista mostra o estado "concluído".
