# Implementação dos Novos Mapeamentos de Categoria

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar três modos de mapeamento de categorias, botão para apagar regras e visualização em mapa.

**Architecture:** 
1. Atualizar o esquema de `category_mapping` em `field_mapping_config.json` para incluir `mapping_mode` (1, 2, 3).
2. Atualizar `core/field_mapping.py` para processar os novos modos na lógica de `build_categories`.
3. Atualizar a `gui/csv_converter_gui.py` para oferecer a seleção de modo, botão "Apagar Tudo" e a janela de visualização "Mapa".

**Tech Stack:** Python 3.14, Tkinter.

**Spec:** Baseado no feedback do cliente recebido em 2026-11-23.

## Global Constraints

- O ficheiro de configuração continua a ser `field_mapping_config.json`.
- A compatibilidade retroativa com configurações anteriores deve ser mantida (assumir modo 2 como padrão para regras existentes).
- A interface deve manter o português europeu.

## Review Focus

1. **Configuração**: Regras antigas sem `mapping_mode` não devem quebrar a aplicação.
2. **Modo 1 vs 3**: Verificar se a lógica de substituição/extração está a gerar a hierarquia esperada na Jumpseller.
3. **Limpeza**: O botão "Apagar Tudo" deve pedir confirmação antes de apagar.
4. **Visualização**: O mapa não deve listar subcategorias, apenas `Pai -> Categoria`.
5. **Persistência**: Testar se as novas opções são guardadas no `field_mapping_config.json` e carregadas corretamente ao reiniciar.

---

### Task 1: Atualização do modelo de dados e lógica central

**Files:**
- Modify: `core/field_mapping.py`
- Test: `tests/test_field_mapping.py` (adicionar testes para os 3 modos)

**Interfaces:**
- Consumes: Estrutura atual de `category_mapping` no JSON.
- Produces: Lógica `apply_mapping(row, mode)` que trata os três modos.

- [ ] **Step 1: Criar testes unitários para os 3 novos modos de mapeamento em `tests/test_field_mapping.py`**
- [ ] **Step 2: Implementar a lógica de mapeamento em `core/field_mapping.py` para suportar os 3 modos**
- [ ] **Step 3: Verificar testes**

### Task 2: Atualização da interface gráfica (GUI)

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: Lógica atualizada em `core/field_mapping.py`.
- Produces: UI com seletores de modo, botão de limpar e mapa.

- [ ] **Step 1: Adicionar seletores de modo (radio buttons) na aba Categorias**
- [ ] **Step 2: Implementar o botão "Apagar Tudo" com confirmação `messagebox`**
- [ ] **Step 3: Implementar o diálogo para o "Mapa de Categorias"**

### Task 3: Testes de Integração e Validação final

**Files:**
- Test: `tests/test_integration.py`

- [ ] **Step 1: Executar um fluxo de conversão completo com os 3 modos**
- [ ] **Step 2: Verificar a persistência do `field_mapping_config.json`**
