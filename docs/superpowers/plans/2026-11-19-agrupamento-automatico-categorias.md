# Agrupamento Automático de Categorias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an automatic category grouping feature in the CATEGORIAS M tab to suggest category groupings based on keyword similarity using the existing `core/category_classifier.py` engine.

**Architecture:** Add a new module `core/category_grouping.py` that utilizes the existing `category_classifier` logic to suggest groupings. Integrate with the `CATEGORIAS M` tab in `gui/csv_converter_gui.py` to allow users to approve/reject suggestions.

**Tech Stack:** Python 3.14, Tkinter for UI components.

**Spec:** `CLAUDE.md`

## Global Constraints

- Python 3.14
- Tkinter/ttk for UI components
- Reuse existing `core/category_classifier.py` for keyword analysis.
- Maintain backward compatibility with existing category mapping functionality
- All new functionality must be properly documented in the codebase
- No new heavy ML dependencies (e.g., scikit-learn, numpy)

## Review Focus

1. **Empty category lists:** Should handle gracefully without crashing.
2. **UI responsiveness:** The analysis should run in a thread to not freeze the GUI.
3. **Accuracy:** Suggestions should be meaningful based on keyword rules.
4. **Data Consistency:** Ensure generated formulas in preview match the actual rule structure.
5. **No Regression:** Existing mapping functionality must remain fully operational.

---

### Task 1: Create Category Grouping Engine

**Files:**
- Create: `core/category_grouping.py`
- Test: `tests/test_category_grouping.py`

**Interfaces:**
- Consumes: List of unique categories from the loaded CSV.
- Produces: Dictionary of `{suggested_parent: [list_of_categories]}`.

- [ ] **Step 1: Implement `suggest_groupings(unique_categories: List[str]) -> Dict[str, List[str]]`**

Use `core/category_classifier.py`'s `DEFAULT_RULES` to identify potential parent categories for each unique category. Group the categories by their suggested parent category.

- [ ] **Step 2: Write test for the engine**

Test that it correctly groups categories based on keywords.

- [ ] **Step 3: Commit**

```bash
git add core/category_grouping.py tests/test_category_grouping.py
git commit -m "feat: add category grouping engine"
```

### Task 2: UI Integration in CATEGORIAS M Tab

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: Results from `core/category_grouping.py`.
- Produces: New UI controls (buttons, result display).

- [ ] **Step 1: Add "Analisar Sugestões" button to the CATEGORIAS M tab.**

- [ ] **Step 2: Implement UI to display suggestions.**

Use a `Toplevel` dialog or a new frame in the tab to show suggested groupings with checkboxes for approval.

- [ ] **Step 3: Commit**

```bash
git add gui/csv_converter_gui.py
git commit -m "feat: add UI for category suggestions"
```

### Task 3: Integration with Existing Massive Rules

**Files:**
- Modify: `gui/csv_converter_gui.py`

**Interfaces:**
- Consumes: Approved suggestions from the UI.
- Produces: Calls to `save_massive_category_rule`.

- [ ] **Step 1: Implement rule creation from approved suggestions.**

Iterate over approved suggestions and call the existing `save_massive_category_rule` function for each.

- [ ] **Step 2: Commit**

```bash
git add gui/csv_converter_gui.py
git commit -m "feat: integrate suggestions with massive rules"
```

---
