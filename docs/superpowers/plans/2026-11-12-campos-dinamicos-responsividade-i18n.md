# Campos Dinâmicos, Responsividade e Correções de Tradução — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir os 10 campos fixos por listas dinâmicas (adicionar/remover) nas abas Categorias I, Categorias M, Destaques e Marcas; fazer a janela memorizar o tamanho usado pelo utilizador; corrigir traduções para português europeu; diagnosticar a falha do verificador de atualizações.

**Architecture:** O corte de 10 itens vive em dois lugares: `core/field_mapping.py` (`[:10]` em `set_category_settings` e `set_highlights_brands_settings`) e `gui/csv_converter_gui.py` (loops `for i in range(10)` que criam campos fixos). A Task 1 remove o corte no backend e prova com teste que listas arbitrárias sobrevivem. As Tasks 2–5 substituem os loops fixos por um padrão de lista dinâmica partilhado (`_build_dynamic_list_row`) usado pelas quatro abas. A Task 6 adiciona persistência de geometria. A Task 7 corrige o catálogo pt-PT. A Task 8 diagnostica o updater.

**Tech Stack:** Python 3.14, Tkinter/ttk, JSON de configuração, PyInstaller.

## Global Constraints

- Manter compatibilidade retroativa: configurações antigas com 10 campos fixos devem continuar a funcionar (a lista dinâmica carrega os valores existentes).
- Usar português europeu em todos os textos visíveis da interface.
- Não introduzir dependências novas.
- O limite de 10 regras/categorias é removido; a lista deve ser ilimitada.
- A janela deve abrir com um tamanho padrão razoável (1280x800) e restaurar o tamanho anterior se existir.
- Não alterar o `pyproject.toml` nem instalar pacotes novos.

## Review Focus

- Listas dinâmicas: adicionar, remover e editar itens; garantir que a ordem é preservada e que itens vazios não são gravados.
- Persistência: ao fechar e reabrir, os itens salvos devem aparecer na lista.
- Compatibilidade: configurações antigas com 10 campos fixos devem ser lidas corretamente (sem perder os 10 valores).
- Traduções: todos os textos visíveis devem estar em português europeu (ex: "Definições", "Guardado", "Eliminar").
- Responsividade: a janela deve restaurar o tamanho correto e não cortar textos ao abrir.
- Regras massivas: o limite de 10 regras deve ser removido sem quebrar a prioridade.

---

### Task 1: Remover o corte de 10 itens no backend

**Files:**
- Modify: `core/field_mapping.py:498, 526, 528`
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: `set_category_settings(new_categories=...)`, `set_highlights_brands_settings(new_categories=...)`
- Produces: as funções passam a guardar listas de tamanho arbitrário.

- [ ] **Step 1: Escrever teste que falha**

```python
def test_category_settings_supports_more_than_ten(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    values = [f"Categoria {i}" for i in range(15)]
    assert field_mapping.set_category_settings(new_categories=values)
    assert field_mapping.get_category_settings()["new_categories"] == values


def test_highlights_brands_settings_supports_more_than_ten(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    values = [f"Destaque {i}" for i in range(15)]
    assert field_mapping.set_highlights_brands_settings(new_categories=values)
    assert field_mapping.get_highlights_brands_settings()["new_categories"] == values
```

- [ ] **Step 2: Executar teste para confirmar a falha**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: FAIL — os testes esperam 15 itens mas a função corta em 10.

- [ ] **Step 3: Remover o corte**

Em `core/field_mapping.py`, substituir `list(new_categories)[:10]` por `list(new_categories)` nas linhas 498 e 526, e `list(cat_keywords)[:10]` por `list(cat_keywords)` na linha 528.

- [ ] **Step 4: Executar teste para confirmar a passagem**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/field_mapping.py tests/test_massive_categories.py
git commit -m "fix: remover limite de 10 categorias no backend"
```

---

### Task 2: Campos dinâmicos — Aba Categorias I

**Files:**
- Modify: `gui/csv_converter_gui.py:1679-1698`
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: `get_category_settings()`, `set_category_settings(new_categories=...)`
- Produces: `self._cat_new_listbox`, `self._cat_new_entry_var`, `_add_cat_new_item()`, `_remove_cat_new_item()`, `_save_category_settings()` atualizado.

- [ ] **Step 1: Escrever teste que falha**

```python
def test_dynamic_category_list_roundtrip(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    values = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]
    assert field_mapping.set_category_settings(new_categories=values)
    assert len(field_mapping.get_category_settings()["new_categories"]) == 11
```

- [ ] **Step 2: Executar teste para confirmar a falha**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS (backend já suporta; este teste valida a integração).

- [ ] **Step 3: Implementar a lista dinâmica**

Substituir o bloco `for i in range(10):` (linhas 1689-1697) por:
- Um `Listbox` com as categorias salvas.
- Um `Entry` + botão "Adicionar" que insere o texto na lista.
- Um botão "Remover" que apaga o item selecionado.
- A função `_save_category_settings` deve ler todos os itens da lista e gravar em `new_categories`.

- [ ] **Step 4: Executar teste para confirmar a passagem**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/csv_converter_gui.py tests/test_massive_categories.py
git commit -m "feat: lista dinamica de categorias pai na aba Categorias I"
```

---

### Task 3: Campos dinâmicos — Aba Categorias M

**Files:**
- Modify: `gui/csv_converter_gui.py:1815-1857, 1955, 1977, 2075`
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: `get_massive_category_rules()`, `save_massive_category_rule(...)`, `remove_massive_category_rule(...)`
- Produces: lista dinâmica de categorias pai e remoção do limite de 10 regras.

- [ ] **Step 1: Escrever teste que falha**

```python
def test_massive_rules_support_unlimited_entries(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    for i in range(15):
        assert field_mapping.add_massive_category_rule(f"Cat {i}", f"Pai {i}")
    assert len(field_mapping.get_massive_category_rules()) == 15
```

- [ ] **Step 2: Executar teste para confirmar a falha**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS (backend já suporta; valida integração).

- [ ] **Step 3: Implementar a lista dinâmica**

- Substituir os 10 campos fixos de "Categoria pai" (linhas 1818-1828) por lista dinâmica.
- Remover o limite de 10 regras em `_add_massive_rule` (linha 2074-2076).
- Atualizar `_refresh_massive_description_combo` para ler da lista dinâmica.

- [ ] **Step 4: Executar teste para confirmar a passagem**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/csv_converter_gui.py tests/test_massive_categories.py
git commit -m "feat: lista dinamica de categorias pai e regras na aba Categorias M"
```

---

### Task 4: Campos dinâmicos — Destaques e Marcas

**Files:**
- Modify: `gui/csv_converter_gui.py:2591-2604, 2703-2716, 3124-3137`
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: `get_highlights_brands_settings()`, `set_highlights_brands_settings(...)`
- Produces: listas dinâmicas para Destaques e Marcas.

- [ ] **Step 1: Escrever teste que falha**

```python
def test_highlights_brands_dynamic_list_roundtrip(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    values = [f"Destaque {i}" for i in range(15)]
    assert field_mapping.set_highlights_brands_settings(new_categories=values)
    assert len(field_mapping.get_highlights_brands_settings()["new_categories"]) == 15
```

- [ ] **Step 2: Executar teste para confirmar a falha**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS.

- [ ] **Step 3: Implementar as listas dinâmicas**

- Mesmo padrão da Task 2: lista + botão "Adicionar" + botão "Remover".
- Aplicar às duas abas (Destaques e Marcas).

- [ ] **Step 4: Executar teste para confirmar a passagem**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/csv_converter_gui.py tests/test_massive_categories.py
git commit -m "feat: listas dinamicas em Destaques e Marcas"
```

---

### Task 5: Responsividade — memorizar o tamanho da janela

**Files:**
- Modify: `core/field_mapping.py` (novas funções)
- Modify: `gui/csv_converter_gui.py` (inicialização e encerramento)
- Test: `tests/test_massive_categories.py`

**Interfaces:**
- Consumes: `field_mapping._read_config()`, `field_mapping._write_config()`
- Produces: `get_window_geometry() -> str`, `set_window_geometry(geometry: str) -> bool`

- [ ] **Step 1: Escrever teste que falha**

```python
def test_window_geometry_roundtrip(tmp_path, monkeypatch):
    config_path = tmp_path / "field_mapping_config.json"
    monkeypatch.setattr(field_mapping, "_config_path", lambda: config_path)
    assert field_mapping.set_window_geometry("1200x800+100+50")
    assert field_mapping.get_window_geometry() == "1200x800+100+50"
```

- [ ] **Step 2: Executar teste para confirmar a falha**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: FAIL.

- [ ] **Step 3: Implementar a persistência de geometria**

- Em `core/field_mapping.py`: adicionar `get_window_geometry()` e `set_window_geometry()`.
- Em `gui/csv_converter_gui.py`: no arranque, ler `get_window_geometry()` e aplicar; ao fechar, guardar `self.geometry()`.

- [ ] **Step 4: Executar teste para confirmar a passagem**

Run: `python -m pytest tests/test_massive_categories.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/field_mapping.py gui/csv_converter_gui.py tests/test_massive_categories.py
git commit -m "feat: memorizar tamanho da janela entre sessoes"
```

---

### Task 6: Correções de tradução para português europeu

**Files:**
- Modify: `core/i18n.py`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `translate(text, language)`
- Produces: catálogo atualizado com termos corretos em pt-PT

- [ ] **Step 1: Escrever teste que falha**

```python
def test_portuguese_european_terms():
    assert translate("Configurações", "pt-PT") == "Definições"
    assert translate("Salvar", "pt-PT") == "Guardar"
    assert translate("Excluir", "pt-PT") == "Eliminar"
```

- [ ] **Step 2: Executar teste para confirmar a falha**

Run: `python -m pytest tests/test_i18n.py -q`

Expected: FAIL.

- [ ] **Step 3: Atualizar o catálogo de traduções**

- Revisar todos os termos em `core/i18n.py` e substituir:
  - "Configurações" → "Definições"
  - "Salvar" → "Guardar"
  - "Excluir" → "Eliminar"
  - "Salvando" → "A guardar"
  - "Excluindo" → "A eliminar"
  - E outros termos que não estejam em português europeu.

- [ ] **Step 4: Executar teste para confirmar a passagem**

Run: `python -m pytest tests/test_i18n.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/i18n.py tests/test_i18n.py
git commit -m "fix: corrigir traducoes para portugues europeu"
```

---

### Task 7: Diagnóstico do verificador de atualizações

**Files:**
- Verify: `core/updater.py`

- [ ] **Step 1: Investigar a causa do erro**

Verificar:
- A URL consultada em `core/updater.py`.
- Se a API/SaaS está a responder.
- Se há exceções a ser silenciadas.

- [ ] **Step 2: Registar a causa e corrigir se necessário**

Se a URL estiver errada ou a API indisponível, atualizar para o endpoint correto.

- [ ] **Step 3: Commit (se houver correção)**

```bash
git add core/updater.py
git commit -m "fix: corrigir endpoint do verificador de atualizacoes"
```

---

### Task 8: Verificação final e build

**Files:**
- Verify: todos os anteriores

- [ ] **Step 1: Executar a suíte completa**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`

Expected: todos os testes passam.

- [ ] **Step 2: Compilar módulos**

Run: `.venv/Scripts/python.exe -m compileall -q core gui tests`

Expected: sem erros.

- [ ] **Step 3: Gerar build**

Run: `.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm CsvFastFileConverter.spec`

Expected: `Build complete!`.

- [ ] **Step 4: Verificar artefato**

Run: verificar `dist/CsvFast-FileConverter-v0.3.82-x64.exe`.

Expected: executável presente.

---

## Notas

- A versão deve ser incrementada para **v0.3.82** após a conclusão.
- O commit final deve incluir a atualização de `VERSION.txt`, `docs/version.txt`, `version_info.txt` e o changelog.