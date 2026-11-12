# Mapeamento Massivo com Regras Operacionais — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer com que as regras massivas selecionáveis associem várias categorias de origem a uma categoria pai criada pelo usuário e tenham efeito real no CSV convertido.

**Architecture:** As regras persistirão a descrição, uma lista de categorias de origem e a categoria pai de destino. A lógica de conversão normalizará as categorias da linha e verificará se a categoria principal da linha é uma das origens selecionadas; quando houver correspondência, manterá a hierarquia original abaixo da categoria pai. A aba CATEGORIAS M exibirá as descrições das oito regras padrão, permitirá selecionar múltiplas categorias de origem do CSV e guardará a associação por regra.

**Tech Stack:** Python 3.14, Tkinter/ttk, JSON de configuração, CSV com `csv.DictReader`, PyInstaller.

**Spec:** Requisitos confirmados na conversa de 12/11/2026: categorias pai são criadas pelo usuário; categorias de origem vêm do fornecedor e são selecionáveis; uma regra pode conter várias categorias de origem apontando para uma categoria pai; subcategorias e sub-subcategorias devem ser preservadas automaticamente.

## Global Constraints

- Não criar categorias pai automaticamente a partir do CSV; elas são destinos definidos pelo usuário.
- Não tratar o texto descritivo da regra como categoria literal do fornecedor.
- Uma regra pode selecionar várias categorias de origem.
- A correspondência deve ser case-insensitive, sem depender de acentos.
- A hierarquia original deve ser mantida sob a categoria pai e limitada a quatro níveis.
- O limite da interface continua em 10 regras configuradas.
- A conversão e a atualização da loja devem usar a mesma lógica de regras massivas.
- Não instalar dependências novas.

## Review Focus

- Uma linha com categoria principal selecionada e descendentes deve gerar pai + hierarquia completa; testar com CSV real.
- Uma linha de uma categoria não selecionada não deve ser capturada por outra regra apenas por compartilhar texto parcial; testar categorias próximas.
- Uma regra com várias origens deve capturar todas as origens e preservar cada hierarquia; testar com `produtos (3).csv`.
- Categorias com acentos e diferenças de caixa devem corresponder; testar `Download_de_produtos_em_CSV (26).csv`.
- Configuração antiga em formato `category_group` deve continuar funcionando ou ser migrada sem perda; testar leitura de configuração legada.

---

### Task 1: Modelo persistente e motor de regras massivas

**Files:**
- Modify: `core/field_mapping.py:957-1058`
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: regras antigas com `category_group` e regras novas com `rule_id`, `description`, `source_categories`, `parent_category`, `priority`.
- Produces: `get_massive_category_rules()`, `add_massive_category_rule(...)`, `apply_massive_category_rules(...)` compatíveis com o restante do projeto; nova função `apply_massive_category_rules_to_categories(...)` se necessário para testar múltiplas origens.

- [x] **Step 1: Escrever testes que falham**
  - Adicionar teste de uma regra com `source_categories=["Computadores", "Portáteis"]` capturando ambas.
  - Adicionar teste de normalização sem acentos e sem diferença de caixa.
  - Adicionar teste de prioridade entre regras sobrepostas.
  - Adicionar teste de compatibilidade com regra antiga contendo `category_group`.

- [x] **Step 2: Executar os testes para confirmar a falha**

Run: `pytest tests/test_massive_categories.py -q`

Expected: FAIL nos testes das novas listas de origens.

- [x] **Step 3: Implementar o modelo e a aplicação**
  - Normalizar origem e categorias com `unicodedata` e `casefold()`.
  - Fazer `get_massive_category_rules()` devolver regras novas e converter regras antigas de `category_group` para uma origem única.
  - Permitir `source_categories` como lista, mantendo `category_group` para compatibilidade.
  - Definir que a regra sem prioridade explícita recebe prioridade acima da existente.
  - Aplicar uma regra quando a categoria principal da linha for igual a uma origem selecionada; não usar substring para evitar capturas indevidas.

- [x] **Step 4: Executar os testes para confirmar a passagem**

Run: `pytest tests/test_massive_categories.py -q`

Expected: todos os testes passam.

- [x] **Step 5: Commit**

```bash
git add core/field_mapping.py tests/test_massive_categories.py
git commit -m "feat: aplicar regras massivas por varias origens"
```

### Task 2: Aplicação no conversor e nos CSVs reais

**Files:**
- Modify: `gui/csv_converter_gui.py:269-467, 767-851`
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: motor de regras da Task 1 e campos mapeados `familia_principal`, `sub_familia`, `sub_sub_familia`.
- Produces: `build_categories()` e `process_csv()` geram `Categories` com pai massivo e hierarquia original para regras novas.

- [x] **Step 1: Escrever testes de integração com fixtures reais**
  - Usar `csv_examples/produtos_10.csv` para validar mapeamento individual e uma origem selecionada.
  - Usar `csv_examples/Download_de_produtos_em_CSV (26).csv` para selecionar duas categorias reais na mesma regra e comparar o número de linhas capturadas com a contagem do CSV.
  - Verificar que a coluna `Categories` contém a categoria pai e os caminhos originais.
  - Adicionar teste de linha não correspondente que mantém categorias originais.

- [x] **Step 2: Executar os testes para confirmar a falha**

Run: `pytest tests/test_massive_categories.py -q`

Expected: FAIL na integração com múltiplas origens.

- [x] **Step 3: Implementar a integração**
  - Passar as três categorias da linha ao motor novo.
  - Manter a lógica atual de limite de quatro níveis e a ordem pai → categoria → subcategoria → sub-subcategoria.
  - Garantir que `merge_update()` use `convert_row()` e, portanto, a mesma aplicação.

- [x] **Step 4: Executar os testes para confirmar a passagem**

Run: `pytest tests/test_massive_categories.py -q`

Expected: todos os testes passam e as contagens dos CSVs reais coincidem.

- [x] **Step 5: Commit**

```bash
git add gui/csv_converter_gui.py tests/test_massive_categories.py
git commit -m "test: validar regras massivas com CSVs reais"
```

### Task 3: Interface CATEGORIAS M com regras selecionáveis e múltiplas origens

**Files:**
- Modify: `gui/csv_converter_gui.py:1763-1991`
- Test: `tests/test_massive_categories.py` ou teste de UI existente, se disponível

**Interfaces:**
- Consumes: `get_massive_category_rules()`, `set_massive_category_rules()`, categorias carregadas em `_unique_categories` e categorias pai em `category_mapping.new_categories`.
- Produces: seleção de uma regra descritiva, seleção múltipla de categorias de origem, seleção de categoria pai e persistência da associação.

- [x] **Step 1: Escrever teste da estrutura persistida**
  - Verificar que salvar uma regra mantém `description`, todas as `source_categories`, `parent_category` e `priority`.
  - Verificar que alterar a associação da mesma regra não cria duplicata.

- [x] **Step 2: Executar o teste para confirmar a falha**

Run: `pytest tests/test_massive_categories.py -q`

Expected: FAIL porque a implementação atual guarda apenas uma categoria literal em `category_group`.

- [x] **Step 3: Implementar a UI**
  - Substituir o campo único “Grupo/origem” por uma lista selecionável de categorias reais carregadas do CSV, com seleção múltipla.
  - Usar as oito descrições padrão do cliente como opções de regra, preservando textos configurados.
  - Manter o dropdown de categoria pai com as categorias criadas pelo usuário.
  - Ao adicionar, guardar a descrição da regra, as origens selecionadas e o pai.
  - Exibir na lista a descrição, as origens e o destino.
  - Remover a regra pela posição persistida, sem depender de uma ordenação ambígua.

- [x] **Step 4: Executar os testes e a compilação**

Run: `pytest tests/test_massive_categories.py -q` e `python -m compileall -q core gui tests`

Expected: testes passam e compilação termina sem saída de erro.

- [x] **Step 5: Commit**

```bash
git add gui/csv_converter_gui.py tests/test_massive_categories.py
git commit -m “feat: permitir varias origens nas regras massivas”
```

### Task 4: Verificação final e build de teste

**Files:**
- Verify: `core/field_mapping.py`, `gui/csv_converter_gui.py`, `tests/test_massive_categories.py`, `CsvFastFileConverter.spec`

- [x] **Step 1: Executar a suíte disponível**

Run: `pytest -q`

Expected: todos os testes passam; se `pytest` não estiver instalado, registrar explicitamente a limitação e executar as regressões com o Python do `.venv`.

> **Resultado:** `pytest` não está instalado no ambiente `.venv`. A suíte `unittest` foi executada com o Python do `.venv` (22 testes aprovados). Os 16 testes de `tests/test_massive_categories.py` foram executados com um runner compatível com pytest e passaram.

- [x] **Step 2: Compilar todos os módulos alterados**

Run: `.venv/Scripts/python.exe -m compileall -q core/field_mapping.py gui/csv_converter_gui.py tests/test_massive_categories.py`

Expected: exit code 0.

> **Resultado:** compilação concluída sem erros.

- [x] **Step 3: Gerar build sem release**

Run: `.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm CsvFastFileConverter.spec`

Expected: `Build complete!`; não executar `build_release.py`, não fazer upload e não publicar release.

> **Resultado:** `Build complete!` executado com sucesso.

- [x] **Step 4: Verificar artefato**

Run: verificar a existência, tamanho e SHA-256 de `dist/CsvFast-FileConverter-v0.3.80-x64.exe`.

Expected: executável presente e identificável pelo hash.

> **Resultado:** `dist/CsvFast-FileConverter-v0.3.80-x64.exe` gerado com 13.859.518 bytes e SHA-256 `8D3C3AD8A0BD83F331ACB2518A4EE88477CF0B87348A75BFFFB2B5B7D04A6EE9`.
