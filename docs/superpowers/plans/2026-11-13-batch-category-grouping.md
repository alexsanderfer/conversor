# Batch Category Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the "CATEGORIAS M" tab to allow batch grouping of categories via pasted lists into a single parent category, persisting them as individual rules.

**Architecture:** Replace the existing `Listbox` and modal dialog-based rule selection with a bulk input mechanism (Textarea + Entry). The logic will iterate over the input list, creating individual mapping rules using `add_massive_category_rule`, and update the view to reflect the generated `Parent/Item` formulas.

**Tech Stack:** Python 3.14, Tkinter.

**Spec:** `CLAUDE.md`

## Global Constraints

- Persist in `field_mapping_config.json`.
- Reuse `add_massive_category_rule`.
- Maintain PT-PT language for UI.

## Review Focus

1.  **Empty Input:** Handle empty list or empty parent category (show warning).
2.  **Performance:** Batch addition speed (should be negligible for reasonable sizes).
3.  **Conflict/Overwrite:** Ensure bulk addition doesn't unintentionally break existing rules.
4.  **UI Layout:** Ensure input text area and result preview area are appropriately sized.
5.  **Data Consistency:** Ensure generated formulas in preview match the actual rule structure.

---

### Task 1: Update UI Structure in `gui/csv_converter_gui.py`

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Produces: `self._massive_input_textarea` (Tk.Text), `self._massive_parent_entry` (Ttk.Entry), `self._massive_result_preview` (Tk.Text).

- [ ] **Step 1: Replace old massive category UI components with bulk input fields**

Modify `_build_tab_categorias_massivas` to remove the old listbox/dialog button and add a `tk.Text` for the list and `ttk.Entry` for the parent category.

- [ ] **Step 2: Initialize new variables and components**

Set up the new UI widgets within the existing tab frame structure.

- [ ] **Step 3: Commit**

```bash
git add gui/csv_converter_gui.py
git commit -m "feat: replace manual selection with bulk input in CATEGORIAS M"
```

### Task 2: Implement Batch Rule Creation Logic

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: `self._massive_input_textarea`, `self._massive_parent_entry`.
- Produces: `add_massive_category_rule` calls for each item in the list.

- [ ] **Step 1: Implement `_add_massive_list_rules`**

Parse the content of the text area (split by comma/newline), validate the parent category, and iterate through the list calling `add_massive_category_rule` for each valid item.

- [ ] **Step 2: Update Rule Persistence**

Ensure `add_massive_category_rule` is correctly called and configuration is saved (reusing the existing persistence mechanism).

- [ ] **Step 3: Commit**

```bash
git add gui/csv_converter_gui.py
git commit -m "feat: implement bulk rule creation in CATEGORIAS M"
```

### Task 3: Visual Confirmation Update

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: Rule generation result.
- Produces: Updated `_massive_result_preview` with generated formulas.

- [ ] **Step 1: Implement result display logic**

Update `_massive_result_preview` to show the formulas (`Parent / Item`) for the newly added rules.

- [ ] **Step 2: Commit**

```bash
git add gui/csv_converter_gui.py
git commit -m "feat: update visual confirmation for batch rules in CATEGORIAS M"
```

### Task 4: Verification

**Files:**
- Test: Manual verification in the application.

- [ ] **Step 1: Verify batch grouping**

Open the application, go to CATEGORIAS M, paste a list of categories, define a parent, and click "ADICIONAR LISTA". Verify that formulas are generated and rules appear in the configuration.

- [ ] **Step 2: Verify existing functionality**

Verify that existing conversion logic (`apply_massive_category_rules`) still correctly applies these newly added batch rules.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: verify batch category grouping functionality"
```
