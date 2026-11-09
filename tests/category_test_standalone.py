#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programa standalone para testar extração e organização de categorias.

Objetivo: validar lógica de extração/montagem da árvore e a UI (incluindo
carregador visual na área da árvore) antes de aplicar no UI do conversor.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Permitir imports do projeto ao executar a partir desta pasta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.csv_converter_gui import _read_csv_any_delimiter, get_mapped_value  # noqa: E402
from core.field_mapping import load_field_mapping  # noqa: E402

try:
    from theme import (
        apply_theme,
        BG_WINDOW,
        GRAY_100,
        GRAY_600,
        GRAY_800,
        GREEN_100,
        WHITE,
    )
except Exception:  # fallback simples se o tema não estiver disponível
    BG_WINDOW = WHITE = "#FFFFFF"
    GRAY_100 = "#F5F5F5"
    GRAY_600 = "#555555"
    GRAY_800 = "#333333"
    GREEN_100 = "#E8F5E9"

    def apply_theme(root):
        return ttk.Style(root)


def _build_category_tree(rows, mapping, max_rows=10000):
    """Extrai categorias das linhas e devolve (tree, found_count)."""
    tree = {"": set()}
    found = 0

    for row in rows[:max_rows]:
        try:
            f1 = get_mapped_value(row, "familia_principal", mapping).strip()
            f2 = get_mapped_value(row, "sub_familia", mapping).strip()
            f3 = get_mapped_value(row, "sub_sub_familia", mapping).strip()

            # Ficheiros com estrutura familia/faminome/sub_familia
            if "faminome" in row and str(row.get("faminome")).strip():
                val = str(row["faminome"]).strip()
                if val and not val.isdigit() and val.lower() not in ("null", "none"):
                    f1 = val
            if not f1 or f1.isdigit():
                for k in ("faminome", "familia_nome", "nome_familia"):
                    if k in row and str(row.get(k, "")).strip():
                        val = str(row[k]).strip()
                        if val and not val.isdigit() and val.lower() not in ("null", "none"):
                            f1 = val
                            break
            if not f1:
                for key in (
                    "categoria",
                    "category",
                    "grupo",
                    "departamento",
                    "familia",
                    "família",
                    "categoria_principal",
                ):
                    for k, v in row.items():
                        kl = str(k).lower().strip()
                        if k and (key == kl or (key in kl and len(kl) < 25)):
                            val = str(v).strip()
                            if val and not val.isdigit() and val.lower() not in (
                                "categoria",
                                "categorias",
                                "null",
                                "none",
                            ):
                                f1 = val
                                break
                    if f1:
                        break

            if "sub_familia" in row and str(row.get("sub_familia")).strip():
                f2 = str(row["sub_familia"]).strip()
            if not f2:
                for key in ("subcategoria", "sub_categoria", "subfamilia", "sub-familia"):
                    for k, v in row.items():
                        kl = str(k).lower().strip()
                        if k and (key == kl or key in kl):
                            val = str(v).strip()
                            if val and val.lower() not in ("null", "none"):
                                f2 = val
                                break
                    if f2:
                        break

            if "sub_sub_familia" in row and str(row.get("sub_sub_familia")).strip():
                f3 = str(row["sub_sub_familia"]).strip()
            if not f3:
                for key in ("subsubcategoria", "sub_sub_categoria", "subsubfamilia"):
                    for k, v in row.items():
                        kl = str(k).lower().strip()
                        if k and (key == kl or key in kl):
                            val = str(v).strip()
                            if val and val.lower() not in ("null", "none"):
                                f3 = val
                                break
                    if f3:
                        break

            if f1:
                found += 1
                tree[""].add(f1)
                tree.setdefault(f1, set())
                if f2:
                    tree[f1].add(f2)
                    tree.setdefault(f2, set())
                    if f3:
                        tree[f2].add(f3)
                        tree.setdefault(f3, set())
        except Exception:
            continue

    # Normalizar: garantir que chaves órfãs apareçam na raiz
    all_children = set()
    for children in tree.values():
        for c in children:
            if c:
                all_children.add(c)
    for k in list(tree.keys()):
        if k and k not in all_children:
            tree[""].add(k)

    # Quebrar ciclos simples
    for _ in range(30):
        fixed = False
        for parent, children in list(tree.items()):
            for child in list(children):
                if not child or child == parent:
                    children.discard(child)
                    fixed = True
                    continue
                if child in tree and parent in tree.get(child, set()):
                    children.discard(child)
                    fixed = True
        if not fixed:
            break

    return tree, found


class CategoryOrganizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Testador de Categorias — Standalone")
        self.root.geometry("1100x720")
        self.root.minsize(860, 560)
        self.root.configure(bg=BG_WINDOW)

        apply_theme(self.root)

        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Selecione um CSV para carregar as categorias.")
        self._category_tree = {"": set()}
        self._category_items = {}
        self._drag_data = {"item": None, "x": 0, "y": 0, "category": None, "parent": None}
        self._loading = False

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        try:
            title_lbl = ttk.Label(main, text="Testador de Categorias (Organizador)", style="TLabel.Title")
        except Exception:
            title_lbl = ttk.Label(main, text="Testador de Categorias (Organizador)")
        try:
            title_lbl.configure(font=("Segoe UI", 15, "bold"))
        except Exception:
            pass
        title_lbl.pack(anchor="w", pady=(0, 2))

        try:
            sub_lbl = ttk.Label(
                main,
                text="Carrega um CSV, extrai categorias e mostra a árvore. Use este teste antes de aplicar no UI do conversor.",
                style="TLabel.Secondary",
            )
        except Exception:
            sub_lbl = ttk.Label(
                main,
                text="Carrega um CSV, extrai categorias e mostra a árvore. Use este teste antes de aplicar no UI do conversor.",
            )
        try:
            sub_lbl.configure(foreground=GRAY_600)
        except Exception:
            pass
        sub_lbl.pack(anchor="w", pady=(0, 10))

        file_frame = ttk.Frame(main)
        file_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(file_frame, text="Ficheiro CSV:").pack(side="left")
        ttk.Entry(file_frame, textvariable=self.path_var).pack(
            side="left", fill="x", expand=True, padx=(6, 6)
        )
        try:
            browse_btn = ttk.Button(file_frame, text="Procurar...", style="TButton.Tonal", command=self.browse)
        except Exception:
            browse_btn = ttk.Button(file_frame, text="Procurar...", command=self.browse)
        browse_btn.pack(side="left", padx=(0, 4))
        self._load_btn = ttk.Button(file_frame, text="Carregar Categorias", command=self.load_categories)
        self._load_btn.pack(side="left")
        self._save_btn = ttk.Button(file_frame, text="Guardar Organização", command=self.save_organization)
        self._save_btn.pack(side="left", padx=(4, 0))

        info_frame = ttk.Frame(main)
        info_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(info_frame, textvariable=self.status_var, foreground=GRAY_600).pack(side="left")
        self._stats_var = tk.StringVar(value="")
        ttk.Label(info_frame, textvariable=self._stats_var, foreground=GRAY_800).pack(side="right")

        # Área da árvore com overlay de carregamento
        self._tree_container = ttk.Frame(main)
        self._tree_container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(
            self._tree_container, bg=GRAY_100, highlightthickness=1, highlightbackground=GRAY_600
        )
        scrollbar = ttk.Scrollbar(self._tree_container, orient="vertical", command=self.canvas.yview)
        self._org_frame = tk.Frame(self.canvas, bg=GRAY_100)
        self._org_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self._org_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Overlay de carregamento (cobre a área da árvore)
        self._loading_overlay = tk.Frame(self._tree_container, bg=GRAY_100)
        self._loading_label = tk.Label(
            self._loading_overlay,
            text="A carregar categorias...",
            bg=GRAY_100,
            fg=GRAY_800,
            font=("Segoe UI", 11, "bold"),
        )
        self._loading_label.pack(pady=(28, 8))
        self._loading_bar = ttk.Progressbar(self._loading_overlay, mode="indeterminate", length=240)
        self._loading_bar.pack(pady=(0, 28))

        # Soltar no vazio = mover para raiz
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

        # Estado inicial
        self._render_empty_state("Nenhuma categoria carregada. Selecione um CSV e clique em «Carregar Categorias».")

    def browse(self):
        path = filedialog.askopenfilename(
            filetypes=[("CSV / texto", "*.csv *.txt"), ("Todos os ficheiros", "*.*")],
            parent=self.root,
        )
        if path:
            self.path_var.set(path)
            self.status_var.set(f"Ficheiro selecionado: {os.path.basename(path)}")

    def _show_loading(self, text="A carregar categorias..."):
        self._loading = True
        try:
            self._loading_label.config(text=text)
            self._loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._loading_overlay.lift()
            self._loading_bar.start(10)
            self._load_btn.config(state="disabled")
            self.status_var.set(text)
            self.root.update_idletasks()
        except Exception:
            pass

    def _hide_loading(self):
        self._loading = False
        try:
            self._loading_bar.stop()
            self._loading_overlay.place_forget()
            self._load_btn.config(state="normal")
        except Exception:
            pass

    def _get_category_org_path(self):
        """Mesmo local usado pelo conversor (frozen → LOCALAPPDATA; dev → pasta do projeto)."""
        try:
            if getattr(sys, "frozen", False):
                base_dir = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "ConversorJumpseller"
                base_dir.mkdir(parents=True, exist_ok=True)
                return base_dir / "category_organization.json"
        except Exception:
            pass
        return Path(__file__).parent / "category_organization.json"

    def _load_saved_category_organization(self):
        try:
            import json
            path = self._get_category_org_path()
            if not path.is_file():
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            tree = {}
            for k, v in data.items():
                if isinstance(v, list):
                    tree[k] = set(v)
                elif isinstance(v, set):
                    tree[k] = set(v)
                else:
                    tree[k] = set()
            if "" not in tree:
                tree[""] = set()
            # Remover ciclos simples
            for _ in range(30):
                fixed = False
                for parent, children in list(tree.items()):
                    for child in list(children):
                        if child == parent or child == "":
                            children.discard(child)
                            fixed = True
                            continue
                        if child in tree and parent in tree.get(child, set()):
                            children.discard(child)
                            fixed = True
                if not fixed:
                    break
            return tree
        except Exception:
            return None

    def save_organization(self):
        try:
            import json
            tree_data = {}
            for parent, children in (self._category_tree or {}).items():
                if isinstance(children, set):
                    tree_data[parent] = sorted([c for c in children if c])
                elif isinstance(children, list):
                    tree_data[parent] = sorted([c for c in children if c])
                else:
                    tree_data[parent] = []
            path = self._get_category_org_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tree_data, f, ensure_ascii=False, indent=2)
            self.status_var.set(f"Organização guardada em: {path}")
            messagebox.showinfo("Guardado", f"Organização de categorias guardada com sucesso.\n\n{path}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao guardar: {e}", parent=self.root)

    def _render_empty_state(self, text):
        for w in self._org_frame.winfo_children():
            w.destroy()
        tk.Label(
            self._org_frame,
            text=text,
            bg=GRAY_100,
            fg=GRAY_600,
            font=("Segoe UI", 10),
            justify="left",
            wraplength=760,
            padx=16,
            pady=16,
        ).pack(anchor="nw")

    def load_categories(self):
        if self._loading:
            return
        selected_file = self.path_var.get().strip().strip('"').strip("'")
        if not selected_file or not os.path.isfile(selected_file):
            messagebox.showwarning("Atenção", "Selecione um ficheiro CSV válido.", parent=self.root)
            return

        self._show_loading("A carregar categorias...")

        def worker():
            result = {"ok": False, "error": None, "tree": None, "found": 0, "rows": 0, "source": "file"}
            try:
                saved = self._load_saved_category_organization()
                if saved is not None and (saved.get("") or len(saved) > 1):
                    result.update({"ok": True, "tree": saved, "found": 0, "rows": 0, "source": "saved"})
                    return

                headers, rows = _read_csv_any_delimiter(selected_file)
                result["rows"] = len(rows or [])
                if not rows:
                    result["error"] = "Ficheiro vazio ou não foi possível ler."
                    return
                mapping = load_field_mapping()
                tree, found = _build_category_tree(rows, mapping)
                result.update({"ok": True, "tree": tree, "found": found, "source": "file"})
            except Exception as e:
                result["error"] = str(e)
            self.root.after(0, lambda: self._on_loaded(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, result):
        self._hide_loading()
        if not result.get("ok"):
            self.status_var.set("Erro ao carregar categorias.")
            self._stats_var.set("")
            self._render_empty_state(f"Falha ao carregar.\n\n{result.get('error') or 'Erro desconhecido.'}")
            messagebox.showerror("Erro", result.get("error") or "Erro ao carregar categorias.", parent=self.root)
            return

        self._category_tree = result.get("tree") or {"": set()}
        found = result.get("found", 0)
        rows = result.get("rows", 0)
        source = result.get("source") or "file"
        roots = len(self._category_tree.get("", set()))
        total_nodes = sum(len(v) for v in self._category_tree.values())
        if source == "saved":
            self.status_var.set("Organização guardada carregada. Pode arrastar categorias e guardar novamente.")
            self._stats_var.set(f"Origem: organização guardada | Raízes: {roots} | Nós: {total_nodes}")
        else:
            self.status_var.set("Categorias carregadas com sucesso.")
            self._stats_var.set(
                f"Linhas lidas: {rows} | Ocorrências: {found} | Raízes: {roots} | Nós: {total_nodes}"
            )
        self.rebuild_tree()

    def rebuild_tree(self):
        for widget in self._org_frame.winfo_children():
            widget.destroy()
        self._category_items = {}
        y = 10

        tree = self._category_tree or {"": set()}
        # Garantir raízes visíveis
        if not tree.get(""):
            all_children = set()
            for children in tree.values():
                for c in children:
                    if c:
                        all_children.add(c)
            roots = [k for k in tree if k and k not in all_children]
            if not roots:
                roots = [k for k in tree if k]
            tree[""] = set(roots)

        if not tree.get(""):
            self._render_empty_state("Nenhuma categoria encontrada no ficheiro.")
            return

        def render(parent, level, indent, visited=None):
            nonlocal y
            if visited is None:
                visited = set()
            if level > 12:
                return
            children = sorted([c for c in tree.get(parent, set()) if c])
            for child in children:
                if child in visited or child == parent:
                    continue
                if level == 0:
                    bg = WHITE
                    prefix = "📁 "
                elif level == 1:
                    bg = GREEN_100
                    prefix = "  └─ "
                else:
                    bg = "#E8EEF5"
                    prefix = "    └─ "
                lbl = tk.Label(
                    self._org_frame,
                    text=f"{prefix}{child}",
                    bg=bg,
                    fg=GRAY_800,
                    padx=8,
                    pady=4,
                    relief="solid",
                    borderwidth=1,
                    anchor="w",
                    font=("Segoe UI", 10 if level == 0 else 9),
                )
                lbl.place(x=12 + indent, y=y, width=980 - indent)

                lbl.bind("<Button-1>", lambda e, c=child, p=parent, w=lbl, lv=level: self._on_drag_start(e, c, p, w, lv))
                lbl.bind("<B1-Motion>", self._on_drag_motion)
                lbl.bind("<ButtonRelease-1>", self._on_drag_end)

                self._category_items[lbl] = {"name": child, "parent": parent, "level": level}
                y += 34
                nv = set(visited)
                nv.add(child)
                render(child, level + 1, indent + 26, nv)

        render("", 0, 0)
        content_height = max(y + 40, 200)
        content_width = 1020
        try:
            self._org_frame.configure(width=content_width, height=content_height)
            self.canvas.itemconfigure("all", width=content_width)
        except Exception:
            pass
        self._org_frame.update_idletasks()
        self.canvas.configure(scrollregion=(0, 0, content_width, content_height))

    def _is_descendant(self, potential_parent, target_cat, _seen=None):
        """True se potential_parent está na subárvore de target_cat (evita ciclos)."""
        if not potential_parent or not target_cat:
            return False
        if _seen is None:
            _seen = set()
        if target_cat in _seen:
            return False
        _seen.add(target_cat)
        children = self._category_tree.get(target_cat, set()) or set()
        if potential_parent in children:
            return True
        for child in children:
            if self._is_descendant(potential_parent, child, _seen):
                return True
        return False

    def _level_bg(self, level):
        if level == 0:
            return WHITE
        if level == 1:
            return GREEN_100
        return "#E8EEF5"

    def _reset_widget_style(self, widget):
        info = self._category_items.get(widget)
        if not info:
            return
        try:
            widget.configure(relief="solid", borderwidth=1, bg=self._level_bg(info.get("level", 0)))
        except Exception:
            pass

    def _clear_drag_highlight(self):
        target = self._drag_data.get("hover_target")
        if target and target in self._category_items:
            self._reset_widget_style(target)
        self._drag_data["hover_target"] = None

    def _on_drag_start(self, event, category, parent, widget, level):
        # Guardar posição original para restaurar sem reconstruir tudo (evita "congelar" em listas grandes)
        try:
            orig = widget.place_info()
        except Exception:
            orig = {}
        self._drag_data = {
            "item": widget,
            "category": category,
            "parent": parent,
            "level": level,
            "hover_target": None,
            "orig_place": orig,
            "last_motion_ts": 0.0,
        }
        try:
            widget.configure(relief="raised", borderwidth=2)
            widget.lift()
        except Exception:
            pass
        self.status_var.set(
            f"A arrastar: {category}  — solte sobre outra categoria para mover para dentro dela, ou no fundo para mover para a raiz."
        )

    # _widget_under_pointer removido (hit-test feito inline com place_forget/place_configure)

    def _on_drag_motion(self, event):
        import time

        item = self._drag_data.get("item")
        if not item:
            return

        # Throttle para evitar inundar o loop de eventos (causa de "travamento")
        now = time.monotonic()
        if now - float(self._drag_data.get("last_motion_ts") or 0.0) < 0.03:
            return
        self._drag_data["last_motion_ts"] = now

        # Mover visualmente o item
        try:
            x = event.x_root - self._org_frame.winfo_rootx() - 10
            y = event.y_root - self._org_frame.winfo_rooty() - 10
            item.place_configure(x=x, y=y)
        except Exception:
            return

        # Encontrar alvo sob o ponteiro sem o item arrastado "a tapar"
        target = None
        try:
            item.place_forget()
            self._org_frame.update_idletasks()
            widget_under = self.root.winfo_containing(event.x_root, event.y_root)
            if widget_under in self._category_items and widget_under is not item:
                target = widget_under
        except Exception:
            target = None
        finally:
            try:
                x = event.x_root - self._org_frame.winfo_rootx() - 10
                y = event.y_root - self._org_frame.winfo_rooty() - 10
                item.place_configure(x=x, y=y)
                item.lift()
            except Exception:
                pass

        if target is not self._drag_data.get("hover_target"):
            self._clear_drag_highlight()
            if target:
                try:
                    target.configure(relief="solid", borderwidth=2, bg="#FFF3CD")
                except Exception:
                    pass
                self._drag_data["hover_target"] = target

    def _restore_dragged_item(self):
        item = self._drag_data.get("item")
        orig = self._drag_data.get("orig_place") or {}
        if not item:
            return
        try:
            if orig:
                item.place(**orig)
            else:
                self.rebuild_tree()
        except Exception:
            try:
                self.rebuild_tree()
            except Exception:
                pass
        self._reset_widget_style(item)

    def _on_canvas_release(self, event):
        # Só trata releases no canvas/fundo; releases em labels são tratados por _on_drag_end
        if self._drag_data.get("item"):
            self._on_drag_end(event)

    def _on_drag_end(self, event):
        item = self._drag_data.get("item")
        cat = self._drag_data.get("category")
        old_parent = self._drag_data.get("parent")
        if not item or not cat:
            self._drag_data = {"item": None, "x": 0, "y": 0, "category": None, "parent": None, "hover_target": None}
            return

        self._clear_drag_highlight()

        # Detetar alvo real ignorando o item arrastado
        target_widget = None
        try:
            item.place_forget()
            self._org_frame.update_idletasks()
            target_widget = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            target_widget = getattr(event, "widget", None)
        finally:
            # Se não houver movimento válido, restauramos depois; manter fora do layout evita flicker
            pass

        moved = False
        move_msg = None

        # Soltar sobre outra categoria => mover para dentro dela (vira filha)
        if target_widget in self._category_items and target_widget is not item:
            new_parent = self._category_items[target_widget]["name"]
            if new_parent == cat:
                pass
            elif self._is_descendant(new_parent, cat):
                self._restore_dragged_item()
                messagebox.showwarning(
                    "Aviso",
                    "Não pode mover uma categoria para dentro do seu próprio filho/subcategoria.",
                    parent=self.root,
                )
                self._drag_data = {"item": None, "x": 0, "y": 0, "category": None, "parent": None, "hover_target": None}
                return
            elif old_parent == new_parent:
                pass
            else:
                if cat in (self._category_tree.get(old_parent) or set()):
                    self._category_tree[old_parent].discard(cat)
                self._category_tree.setdefault(new_parent, set()).add(cat)
                moved = True
                move_msg = f"Movido: '{cat}' para dentro de '{new_parent}'."

        # Soltar no fundo/canvas/frame => mover para a raiz
        elif target_widget in (self.canvas, self._org_frame, self._loading_overlay):
            if old_parent != "":
                if cat in (self._category_tree.get(old_parent) or set()):
                    self._category_tree[old_parent].discard(cat)
                self._category_tree.setdefault("", set()).add(cat)
                moved = True
                move_msg = f"Movido: '{cat}' para a raiz."

        orig_place = self._drag_data.get("orig_place") or {}
        self._drag_data = {"item": None, "x": 0, "y": 0, "category": None, "parent": None, "hover_target": None, "orig_place": None}

        if moved:
            roots = len(self._category_tree.get("", set()))
            total_nodes = sum(len(v) for v in self._category_tree.values())
            parts = [p.strip() for p in (self._stats_var.get() or "").split("|") if p.strip()]
            base = parts[0] if parts else ""
            stats = f"{base} | Raízes: {roots} | Nós: {total_nodes}" if base else f"Raízes: {roots} | Nós: {total_nodes}"
            self._stats_var.set(stats)
            if move_msg:
                self.status_var.set(move_msg + " (a atualizar árvore...)")
            # Adiar reconstrução pesada para o próximo ciclo do loop de eventos (evita UI "congelar" ao soltar)
            self.root.after_idle(self.rebuild_tree)
            if move_msg:
                self.root.after(50, lambda m=move_msg: self.status_var.set(m))
        else:
            # Restaurar posição sem reconstruir 1000+ widgets
            restored = False
            try:
                if orig_place and item and str(item) in [str(w) for w in self._org_frame.winfo_children()]:
                    item.place(**orig_place)
                    self._reset_widget_style(item)
                    restored = True
            except Exception:
                restored = False
            if not restored:
                self.root.after_idle(self.rebuild_tree)
            self.status_var.set(
                "Categorias carregadas. Arraste uma categoria para outra (mover para dentro) ou para o fundo (mover para a raiz)."
            )


if __name__ == "__main__":
    root = tk.Tk()
    app = CategoryOrganizerApp(root)
    root.mainloop()
