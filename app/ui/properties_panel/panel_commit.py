"""Commit path + editor lifecycle mixin for PropertiesPanel.

Split out of the monolithic ``panel.py`` (v0.0.15.11 refactor round).
Covers every user-interaction path that turns a value into a
``ChangePropertyCommand``:

- Enum popup (layout_type / anchor / compound dropdown)
- Inline `tk.Entry` overlay for single-line text
- Inline multiline edit (via ``_edit_text_inline``)
- Click routing (dispatch to editor's on_single_click / on_double_click)
- Color / image / text pickers
- ``_commit_prop`` — the commit bottleneck with container-bound clamp

The mixin relies on attributes set up by ``PropertiesPanel.__init__``
(``self.tree``, ``self.project``, ``self.current_id``, ``self.overlays``,
``self._active_editor`` family, ``self._disabled_states``,
``self._prop_iids``, ``self._suspend_history``) plus the schema helpers
(``_find_prop``, ``_current_descriptor``, etc.).
"""

from __future__ import annotations

import tkinter as tk

from app.ui.tint_color_picker import ColorPickerDialog

from app.core.commands import (
    ChangePropertyCommand,
    ChangeVariableDefaultCommand,
    ExtraParamCommand,
    MultiChangePropertyCommand,
    MultiExtraParamCommand,
    MultiWidgetPropertyCommand,
)
from app.core.i18n import tr
from app.ui.system_fonts import ui_font
from app.core.variables import is_var_token, parse_var_token
from app.ui.dialog_utils import safe_grab_set
from app.ui.dialogs.message import ask_ok_cancel, show_error
from app.ui.icons import load_tk_icon
from app.widgets.layout_schema import (
    LAYOUT_DISPLAY_NAMES,
    LAYOUT_ICON_NAMES,
    managed_geometry_disabled,
    plan_grid_shrink_relocation,
)
from tools.text_editor_dialog import TextEditorDialog

from .constants import (
    CURSOR_ADVANCED_SENTINEL,
    VALUE_BG,
    anchor_code,
    menu_style,
)
from .editors import get_editor
from .format_utils import coerce_value, enum_options_for, prop_row_label
from .overlays import SLOT_TEXT_VALUE


def apply_batch_prop_entries(
    project,
    node_ids,
    widget_type: str | None,
    pname: str,
    value,
    *,
    clamp=None,
    grid_guard=None,
) -> list:
    """Apply one property edit to every target widget, returning the
    ``[(widget_id, {prop: (before, after)})]`` entries for a single
    ``MultiWidgetPropertyCommand`` undo step.

    Multi-select batch edit — the Properties panel keeps rendering the
    primary selection while every same-type widget in ``node_ids`` gets
    the change:

    - widgets of another ``widget_type`` (when given) are skipped;
    - widgets whose parent's layout manager owns the field
      (``managed_geometry_disabled``) are skipped — those rows are
      frozen per-node even if the primary's row looked editable;
    - ``clamp(node, pname, value)`` (when given) bounds the value per
      container, e.g. the workspace's container-bounds clamp;
    - ``grid_guard(node, pname, value)`` (when given) returns False for
      widgets the caller decided to leave out — used for the
      grid_rows/grid_cols shrink check, where an orphaned child cannot
      be silently dropped. No auto-repair here: each container either
      shrinks cleanly or is skipped.

    Applies the change through ``project.update_property`` (so the
    usual ``property_changed`` refresh + ``compute_derived`` side
    effects fire) and snapshots before/after per widget; a widget whose
    properties didn't actually change contributes no entry.
    """
    entries: list[tuple] = []
    for widget_id in node_ids:
        node = project.get_widget(widget_id)
        if node is None:
            continue
        if widget_type is not None and node.widget_type != widget_type:
            continue
        if pname in managed_geometry_disabled(node):
            continue
        new_value = clamp(node, pname, value) if clamp is not None else value
        if grid_guard is not None and not grid_guard(
            node, pname, new_value,
        ):
            continue
        before = dict(node.properties)
        project.update_property(widget_id, pname, new_value)
        after = dict(node.properties)
        changed = {
            k: (before.get(k), after.get(k))
            for k in set(before) | set(after)
            if before.get(k) != after.get(k)
        }
        if changed:
            entries.append((widget_id, changed))
    return entries


class CommitMixin:
    """Editor lifecycle + commit bottleneck. See module docstring."""

    # ------------------------------------------------------------------
    # Enum popup
    # ------------------------------------------------------------------
    def _popup_enum_menu_at(
        self, pname: str, ptype: str, x_root: int, y_root: int,
    ) -> None:
        node = self.project.get_widget(self.current_id)
        # Dynamic enums — options computed from the current widget's
        # data, not a static list. ``segment_initial`` reads the
        # sibling ``values`` prop so the dropdown reflects whatever
        # segments the user just typed in the table editor.
        if ptype == "segment_initial":
            options = self._segment_initial_options(node)
            if not options:
                # Empty values → show a single disabled hint instead
                # of an empty menu the user can't interact with.
                menu = tk.Menu(self, tearoff=0, **menu_style())
                menu.add_command(
                    label=tr("prop_commit.no_segments", "(no segments)"),
                    foreground="#555555",
                )
                try:
                    menu.tk_popup(x_root, y_root)
                finally:
                    menu.grab_release()
                return
        else:
            options = enum_options_for(ptype)
        if not options:
            return
        current = node.properties.get(pname) if node else None
        menu = tk.Menu(self, tearoff=0, **menu_style())
        # tk.Menu drops PhotoImage refs as soon as the caller scope
        # returns — stash them on the menu itself so the icons
        # actually render.
        icon_refs: list = []
        for opt in options:
            stored = (
                anchor_code(opt) or opt
                if ptype == "anchor" else opt
            )
            prefix = "• " if stored == current else "   "
            if ptype == "anchor":
                commit_val = anchor_code(opt) or "center"
            else:
                commit_val = opt
            label_text = opt
            icon_image = None
            if ptype == "layout_type":
                label_text = LAYOUT_DISPLAY_NAMES.get(opt, opt)
                icon_name = LAYOUT_ICON_NAMES.get(opt)
                if icon_name:
                    icon_image = load_tk_icon(icon_name, size=14)
                    if icon_image is not None:
                        icon_refs.append(icon_image)
            if ptype == "cursor" and opt == CURSOR_ADVANCED_SENTINEL:
                # The sentinel is an internal marker — show its
                # localized label but keep intercepting the English
                # option value below.
                label_text = tr("props.cursor.advanced", "Advanced…")
                cmd = lambda p=pname: self._open_cursor_advanced(p)
            else:
                cmd = lambda v=commit_val, p=pname: self._commit_prop(p, v)
            kwargs = {
                "label": f"{prefix}{label_text}",
                "command": cmd,
            }
            if icon_image is not None:
                kwargs["image"] = icon_image
                kwargs["compound"] = "left"
            menu.add_command(**kwargs)
        menu._layout_icon_refs = icon_refs  # keep refs alive
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _open_cursor_advanced(self, pname: str) -> None:
        from app.ui.dialogs.cursor_advanced import CursorAdvancedDialog
        dialog = CursorAdvancedDialog(self.winfo_toplevel())
        self.wait_window(dialog)
        if dialog.result:
            self._commit_prop(pname, dialog.result)

    # ------------------------------------------------------------------
    # Text inline edit (fast single-line)
    # ------------------------------------------------------------------
    def _edit_text_inline(self, pname: str) -> None:
        iid = self._prop_iids.get(pname)
        if iid is None or self.overlays is None:
            return
        overlay = self.overlays.get(iid, SLOT_TEXT_VALUE)
        if overlay is None:
            return
        self._commit_active_editor()
        self.tree.update_idletasks()
        x = overlay.winfo_x()
        y = overlay.winfo_y()
        w = overlay.winfo_width()
        h = overlay.winfo_height()

        node = self.project.get_widget(self.current_id)
        current = node.properties.get(pname, "") if node else ""
        entry = tk.Entry(
            self.tree, font=ui_font(11),
            bg=VALUE_BG, fg="#cccccc", insertbackground="#cccccc",
            bd=1, relief="flat",
            highlightthickness=1, highlightbackground="#3a3a3a",
            highlightcolor="#3b8ed0",
        )
        entry.insert(0, str(current))
        entry.place(x=x, y=y, width=w, height=h)
        entry.select_range(0, tk.END)
        entry.focus_set()
        self._active_editor = entry
        self._active_prop = pname
        self._active_prop_type = "multiline"
        entry.bind("<Return>", lambda _e: self._commit_active_editor())
        entry.bind("<FocusOut>", lambda _e: self._commit_active_editor())
        entry.bind("<Escape>", lambda _e: self._cancel_active_editor())
        self._attach_inline_context_menu(entry, prop=None)

    # ------------------------------------------------------------------
    # Click routing
    # ------------------------------------------------------------------
    def _on_single_click(self, event) -> None:
        self._tooltip.cancel()
        region = self.tree.identify_region(event.x, event.y)
        if region == "nothing":
            self.tree.selection_remove(*self.tree.selection())
            try:
                self.tree.focus("")
            except tk.TclError:
                pass
            self.winfo_toplevel().focus_set()
            return
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        # Events group — single click on a ``<param>:`` value cell
        # starts an inline edit. Function-row picking uses the ``▾``
        # button overlay (same affordance as Cursor / Anchor enum
        # editors), not single-click on the value cell.
        meta_entry = self._event_row_meta.get(iid)
        if meta_entry is not None:
            kind = meta_entry[0]
            if (
                kind == "param"
                and len(meta_entry) == 4
                and self.current_id is not None
            ):
                _, event_key, m_idx, p_idx = meta_entry
                self._begin_param_edit(
                    self.current_id, event_key, m_idx, p_idx, iid,
                )
                return
        if not iid.startswith("p:"):
            return
        pname = iid[2:]
        if self._disabled_states.get(pname):
            return
        prop = self._find_prop_by_name(pname)
        if prop is None:
            # Axis rows (``x.Main Axis.percent``) live in ``node.extra``
            # rather than the descriptor, so the editor registry cannot
            # find them — they still get the same inline cell editor as
            # x/y/w/h instead of the old pop-up prompt.
            if self._is_extra_number_row(pname):
                self._open_extra_number_overlay(pname, iid)
                return "break"
            return
        get_editor(prop["type"]).on_single_click(self, pname, prop)

    def _on_double_click(self, event) -> str | None:
        iid = self.tree.identify_row(event.y)
        if iid and iid.startswith("localvar:") and iid != "localvar:empty":
            doc_id = (
                self.project.active_document_id if self.project else None
            )
            self.project.event_bus.publish(
                "request_open_variables_window", "local", doc_id,
            )
            return "break"
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return None
        col = self.tree.identify_column(event.x)
        if col != "#1":
            return None
        if not iid or not iid.startswith("p:"):
            return None
        pname = iid[2:]
        if self._disabled_states.get(pname):
            return "break"
        # Variable-bound row → jump to the Variables window with the
        # bound entry pre-selected. Fires before per-editor dispatch
        # so colour / number / string editors don't see a var token
        # and try to seed a literal-value picker with it.
        node = (
            self.project.get_widget(self.current_id)
            if self.current_id else None
        )
        value = node.properties.get(pname) if node is not None else None
        if is_var_token(value):
            var_id = parse_var_token(value)
            scope = (
                self.project.get_variable_scope(var_id)
                if var_id else None
            ) or "global"
            doc_id = self.project.active_document_id
            self.project.event_bus.publish(
                "request_open_variables_window", scope, doc_id, var_id,
            )
            return "break"
        prop = self._find_prop_by_name(pname)
        if prop is None:
            return None
        if get_editor(prop["type"]).on_double_click(self, pname, prop, event):
            return "break"
        return None

    def _find_prop_by_name(self, pname: str):
        descriptor = self._current_descriptor()
        if descriptor is None:
            return None
        return self._find_prop(descriptor, pname)

    # ------------------------------------------------------------------
    # Editors — inline Entry
    # ------------------------------------------------------------------
    def _is_extra_number_row(self, pname: str) -> bool:
        """True when ``pname`` names an axis number row (percent) for the
        current node — those are backed by ``node.extra``, not by the
        descriptor's properties."""
        if not str(pname).startswith("x."):
            return False
        node = (
            self.project.get_widget(self.current_id)
            if self.current_id else None
        )
        if node is None:
            return False
        from app.widgets.extra_params import extra_rows_for
        return any(
            prop.get("name") == pname and prop.get("type") == "number"
            for prop in extra_rows_for(node)
        )

    def _open_extra_number_overlay(
        self, pname: str, iid: str | None = None,
    ) -> None:
        """Inline Entry for an axis number row — same widget, same commit
        path and same feel as the x/y/w/h editor (the value is clamped to
        the 1-100 range the row advertises)."""
        if self.current_id is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        if iid is None:
            iid = self._prop_iids.get(pname, f"p:{pname}")
        try:
            bbox = self.tree.bbox(iid, "#1")
        except tk.TclError:
            bbox = None
        if not bbox:
            return
        from app.widgets.extra_params import param_get
        current = param_get(node, pname, default=50)
        entry = tk.Entry(
            self.tree,
            font=ui_font(11),
            bg=VALUE_BG, fg="#cccccc", insertbackground="#cccccc",
            bd=1, relief="flat",
            highlightthickness=1, highlightbackground="#3a3a3a",
            highlightcolor="#3b8ed0",
        )
        entry.insert(0, "" if current is None else str(current))
        entry.place(
            x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3],
        )
        entry.select_range(0, tk.END)
        entry.focus_set()
        self._active_editor = entry
        self._active_prop = pname
        self._active_prop_type = "number"

        def _commit(_event=None) -> None:
            if self._active_editor is not entry:
                return
            try:
                raw = entry.get()
            except tk.TclError:
                raw = ""
            self._cancel_active_editor()
            raw = raw.strip()
            if not raw:
                return
            try:
                parsed = int(float(raw))
            except (TypeError, ValueError):
                return
            self._commit_prop(pname, max(1, min(100, parsed)))

        entry.bind("<Return>", lambda _e: _commit())
        entry.bind("<FocusOut>", lambda _e: _commit())
        entry.bind("<Escape>", lambda _e: self._cancel_active_editor())


    def _open_entry_overlay(
        self, iid: str, pname: str, prop: dict, bbox,
    ) -> None:
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        current = node.properties.get(pname, "")
        entry = tk.Entry(
            self.tree,
            font=ui_font(11),
            bg=VALUE_BG, fg="#cccccc", insertbackground="#cccccc",
            bd=1, relief="flat",
            highlightthickness=1, highlightbackground="#3a3a3a",
            highlightcolor="#3b8ed0",
        )
        entry.insert(0, str(current) if current is not None else "")
        entry.place(
            x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3],
        )
        entry.select_range(0, tk.END)
        entry.focus_set()
        self._active_editor = entry
        self._active_prop = pname
        self._active_prop_type = prop["type"]

        entry.bind("<Return>", lambda _e: self._commit_active_editor())
        entry.bind("<FocusOut>", lambda _e: self._commit_active_editor())
        entry.bind("<Escape>", lambda _e: self._cancel_active_editor())
        self._attach_inline_context_menu(entry, prop=prop)

    def _commit_active_editor(self) -> None:
        if self._active_editor is None or self._active_prop is None:
            return
        pname = self._active_prop
        ptype = getattr(self, "_active_prop_type", None)
        try:
            raw = self._active_editor.get()
        except tk.TclError:
            raw = ""
        new_value = coerce_value(ptype, raw)
        try:
            self._active_editor.destroy()
        except tk.TclError:
            pass
        self._active_editor = None
        self._active_prop = None
        self._active_prop_type = None
        if new_value is not None:
            self._commit_prop(pname, new_value)

    def _cancel_active_editor(self) -> None:
        if self._active_editor is None:
            return
        try:
            self._active_editor.destroy()
        except tk.TclError:
            pass
        self._active_editor = None
        self._active_prop = None
        self._active_prop_type = None

    # ------------------------------------------------------------------
    # Pickers
    # ------------------------------------------------------------------
    def _pick_color(self, pname: str) -> None:
        if self.current_id is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        value = node.properties.get(pname)
        var_id = parse_var_token(value)
        entry = (
            self.project.get_variable(var_id) if var_id is not None else None
        )
        if entry is not None:
            self._pick_color_for_variable(entry)
            return
        initial = value or "#6366f1"
        dialog = ColorPickerDialog(
            self.winfo_toplevel(), initial_color=initial,
        )
        dialog.wait_window()
        hex_value = getattr(dialog, "result", None)
        if hex_value:
            self._commit_prop(pname, hex_value)

    def _pick_color_for_variable(self, entry) -> None:
        # Bound row: picker rewrites the variable's default, so every
        # widget bound to it repaints in lock-step. Falls back to
        # #000000 when the stored default isn't valid hex (loose-policy
        # mirror of the literal flow's "" → #6366f1 default).
        from app.core.variables import COLOR_DEFAULT, is_valid_hex
        initial = entry.default if is_valid_hex(entry.default) else COLOR_DEFAULT
        dialog = ColorPickerDialog(
            self.winfo_toplevel(), initial_color=initial,
        )
        try:
            uses = sum(1 for _ in self.project.iter_bindings_for(entry.id))
            suffix = (
                tr("prop_commit.used_by_n_widgets", " — used by {n} widget{s}").format(
                    n=uses, s=("s" if uses != 1 else ""),
                )
                if uses else ""
            )
            dialog.title(
                tr("prop_commit.editing_variable", "Editing variable: {name}{suffix}").format(
                    name=entry.name, suffix=suffix,
                ),
            )
        except tk.TclError:
            pass
        dialog.wait_window()
        hex_value = getattr(dialog, "result", None)
        if not hex_value or hex_value == entry.default:
            return
        before = entry.default
        self.project.change_variable_default(entry.id, hex_value)
        # change_variable_default coerces invalid input — push the
        # coerced value so undo restores exactly what redo would land on.
        after = entry.default
        if after != before:
            self.project.history.push(
                ChangeVariableDefaultCommand(entry.id, before, after),
            )

    def _pick_image(self, pname: str) -> None:
        # Project-scoped picker — only shows images already in
        # ``<project>/assets/images/``, with an "Import..." button
        # that copies a file off-disk into the project's assets
        # folder before selecting it. Keeps every Image reference
        # inside the project so the .ctkproj stays portable.
        from app.ui.image_picker_dialog import ImagePickerDialog
        project_file = getattr(self.project, "path", None)
        if not project_file:
            return  # Untitled state shouldn't be reachable.
        dialog = ImagePickerDialog(
            self.winfo_toplevel(), project_file,
            event_bus=getattr(self.project, "event_bus", None),
        )
        dialog.wait_window()
        if dialog.result:
            self._commit_prop(pname, dialog.result)

    def _pick_font(self, pname: str) -> None:
        """Open the font picker for the focused widget. The picker
        carries a scope selector — "this widget" commits via the
        normal property path; "all [Type]" / "all in project" writes
        into ``project.font_defaults`` and triggers a workspace
        refresh so every text widget that doesn't have its own
        override updates immediately.
        """
        if self.current_id is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        descriptor = self._current_descriptor()
        type_name = (
            getattr(descriptor, "type_name", None) if descriptor else None
        )
        type_display = (
            getattr(descriptor, "display_name", None) if descriptor else None
        )
        from app.ui.font_picker_dialog import (
            FontPickerDialog, SCOPE_ALL, SCOPE_TYPE, SCOPE_WIDGET,
        )
        # Snapshot the system-fonts list so we can detect a "+ Add
        # system font" mutation inside the picker and mark the
        # project dirty accordingly — regardless of whether the user
        # ends up changing the widget's font_family on top of that.
        system_fonts_before = list(
            getattr(self.project, "system_fonts", []) or [],
        )
        dialog = FontPickerDialog(
            self.winfo_toplevel(), self.project,
            current=node.properties.get(pname),
            type_name=type_name,
            type_display=type_display,
        )
        dialog.wait_window()
        system_fonts_after = list(
            getattr(self.project, "system_fonts", []) or [],
        )
        if system_fonts_after != system_fonts_before:
            # The picker added a system font to the palette. That's a
            # project-state change in its own right — even if the user
            # cancels the font apply, the palette update should be
            # remembered on next save.
            self.project.event_bus.publish("dirty_changed", True)
        result = getattr(dialog, "result", None)
        if result is None:
            return
        family, scope = result
        if scope == SCOPE_WIDGET:
            self._commit_prop(pname, family)
            return
        # Scope = type / all-in-project — writes the cascade default
        # rather than a per-widget override. Using ``family is None``
        # as the "Use default" intent: drops the entry instead of
        # storing an empty string.
        from app.core.fonts import (
            ALL_DEFAULT_KEY, set_active_project_defaults,
        )
        # Pure cascade behaviour was confusing: the user picked "All
        # Buttons" expecting every button to change, but per-widget
        # overrides survived because cascade lookup hit them first.
        # Reinterpret scope literally — "all" means all. When the
        # user picks scope=type/all with a real family:
        #   • clear per-widget font_family on every affected widget
        #   • for scope=ALL also clear sibling per-type defaults
        #   • set the cascade entry for the chosen scope key
        # Show an informational confirmation only when overrides
        # actually exist — silent apply is faster when there's
        # nothing to lose.
        widget_overrides = self._widgets_with_font_override(
            scope, type_name,
        )
        type_overrides: list[str] = []
        if scope == SCOPE_ALL:
            type_overrides = [
                k for k in self.project.font_defaults
                if k != ALL_DEFAULT_KEY
            ]
        if family and (widget_overrides or type_overrides):
            scope_label = (
                tr("prop_commit.every_type", "every {type}").format(
                    type=(type_display or type_name),
                )
                if scope == SCOPE_TYPE else tr("prop_commit.every_text_widget", "every text widget")
            )
            lines = [
                tr("prop_commit.apply_font_confirm", "Apply {family!r} to {scope} in this project?").format(
                    family=family, scope=scope_label,
                ),
                "",
            ]
            if widget_overrides:
                lines.append(
                    tr("prop_commit.font_widget_overrides", "{n} widget(s) currently use a custom font. Their override will be cleared.").format(
                        n=len(widget_overrides),
                    ),
                )
            if type_overrides:
                lines.append(
                    tr("prop_commit.font_type_overrides", "{n} per-type default(s) will be removed ({types}).").format(
                        n=len(type_overrides), types=", ".join(type_overrides),
                    ),
                )
            if not ask_ok_cancel(
                tr("prop_commit.apply_font", "Apply font"),
                "\n".join(lines),
                parent=self.winfo_toplevel(),
            ):
                return
        defaults = dict(self.project.font_defaults)
        key = type_name if scope == SCOPE_TYPE else ALL_DEFAULT_KEY
        if key is None:
            return
        if family and scope == SCOPE_ALL:
            # Wipe sibling per-type defaults so the new "_all" entry
            # actually applies project-wide instead of being shadowed
            # by every existing per-type default.
            defaults = {}
        if family:
            defaults[key] = family
        else:
            defaults.pop(key, None)
        self.project.font_defaults = defaults
        set_active_project_defaults(defaults)
        if family:
            # Scope literalism — drop per-widget font_family on
            # every affected widget so the cascade default actually
            # wins. ``Use default`` (family is None) intentionally
            # leaves overrides alone; clearing the cascade slot is
            # never destructive on its own.
            for w in widget_overrides:
                self.project.update_property(w.id, "font_family", None)
        # Mark dirty so the new defaults make it into the next save.
        self.project.event_bus.publish("dirty_changed", True)
        self.project.event_bus.publish("font_defaults_changed", defaults)

    def _widgets_with_font_override(
        self, scope: str, type_name: str | None,
    ) -> list:
        """Return every widget the cascade scope would affect that
        carries its own ``font_family`` value. Used by ``_pick_font``
        to ask the user whether per-widget overrides should fall back
        to the new default too.
        """
        from app.ui.font_picker_dialog import SCOPE_TYPE
        out = []
        for node in self.project.iter_all_widgets():
            if not node.properties.get("font_family"):
                continue
            if scope == SCOPE_TYPE and node.widget_type != type_name:
                continue
            out.append(node)
        return out

    def _open_text_editor(self, pname: str, prop: dict) -> None:
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        current = node.properties.get(pname) or ""
        label = prop_row_label(
            prop.get("row_label") or prop.get("label") or pname,
        )
        is_rich = (
            (node.widget_type == "CTkRichLabel" and pname == "text")
            or (node.widget_type == "CTkTextbox"
                and pname == "initial_text")
        )
        dialog = TextEditorDialog(
            self.winfo_toplevel(),
            tr("prop_commit.edit_label", "Edit: {label}").format(label=label),
            str(current),
            rich_text=is_rich,
        )
        dialog.wait_window()
        if dialog.result is not None:
            self._commit_prop(pname, dialog.result)

    def _segment_initial_options(self, node) -> list[str]:
        """Read the current node's segment/tab names and split into
        dropdown options. Checks ``values`` (CTkSegmentedButton) and
        ``tab_names`` (CTkTabview) — whichever is present.
        """
        if node is None:
            return []
        raw = (
            node.properties.get("values")
            or node.properties.get("tab_names")
            or ""
        )
        return [
            line for line in str(raw).splitlines() if line.strip()
        ]

    def _open_segment_values_editor(self, pname: str) -> None:
        """Table-based +/- editor for ``CTkSegmentedButton.values``.
        Stored on the node as the same newline-separated string the
        old multiline editor produced — exporter / runtime are
        unchanged. Empty rows are dropped on save.
        """
        from tools.segment_values_dialog import SegmentValuesDialog
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        current = node.properties.get(pname) or ""
        values = [
            line for line in str(current).splitlines() if line.strip()
        ]
        is_tabview = pname == "tab_names"
        if is_tabview:
            title = tr("prop_commit.edit_tabs", "Edit Tabs")
        elif node.widget_type == "CTkSegmentedButton":
            title = tr("prop_commit.edit_segments", "Edit Segments")
        else:
            title = tr("prop_commit.edit_values", "Edit Values")
        dialog = SegmentValuesDialog(
            self.winfo_toplevel(), title, values,
        )
        dialog.wait_window()
        if dialog.result is None:
            return
        new_values = dialog.result
        if is_tabview and not self._confirm_tabview_change(
            node, values, new_values,
        ):
            return
        self._commit_prop(pname, "\n".join(new_values))

    def _confirm_tabview_change(
        self, node, old_names: list[str], new_names: list[str],
    ) -> bool:
        """Ask the user to confirm a tab-list edit that would affect
        nested children. Detects a single-tab rename (one removed, one
        added) and previews the auto-migration; any other delta that
        orphans children warns they'll be moved to the first tab.
        Returns True to proceed with the commit, False to cancel.
        """
        removed = [n for n in old_names if n not in new_names]
        if not removed:
            return True
        affected_slots = {
            getattr(c, "parent_slot", None) for c in node.children
        }
        affected_count = sum(
            1 for c in node.children
            if getattr(c, "parent_slot", None) in removed
        )
        if affected_count == 0:
            return True
        _ = affected_slots  # kept for future per-tab breakdown
        added = [n for n in new_names if n not in old_names]
        if len(removed) == 1 and len(added) == 1:
            msg = (
                tr("prop_commit.renaming_tab", "Renaming tab '{old}' to '{new}'.\n{n} widget(s) will move to the renamed tab.").format(
                    old=removed[0], new=added[0], n=affected_count,
                )
            )
        else:
            first = new_names[0] if new_names else tr("prop_commit.tab_1", "Tab 1")
            msg = (
                tr("prop_commit.tab_widgets_will_move", "{n} widget(s) are in tabs being deleted or renamed.\nThey will be moved to '{first}'.\n\nTip: rename tabs one at a time to keep widgets attached to the renamed tab.").format(
                    n=affected_count, first=first,
                )
            )
        return ask_ok_cancel(
            tr("prop_commit.tab_change", "Tab change"), msg,
            parent=self.winfo_toplevel(),
            ok_text=tr("prop_commit.continue", "Continue"),
            cancel_text=tr("prop_commit.back", "Back"),
        )

    # ------------------------------------------------------------------
    # Commit path
    # ------------------------------------------------------------------
    def _commit_prop(self, pname: str, value) -> None:
        if self.current_id is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        # First-class 02 enhancement params (spec §11): x.-prefixed rows
        # backed by WidgetNode.extra — never a real properties key.
        if str(pname).startswith("x."):
            self._commit_extra_param(pname, value)
            return
        # Multi-select batch mode: the panel renders the primary
        # selection, and every edit applies to the whole same-type set
        # (_batch_ids) as ONE undo step. Nested containers / layout
        # structure keys are still allowed — each widget updates
        # independently through its own guard (see _commit_prop_batch).
        if getattr(self, "_batch_ids", None):
            self._commit_prop_batch(pname, value)
            return
        # Grid shrink guard — block grid_rows/grid_cols going below the
        # max row/column index actually occupied by a child, otherwise
        # children silently disappear from the canvas (still in the
        # model, just out-of-bounds for the new grid). Instead of
        # erroring on every attempt, first try to auto-repair: park the
        # out-of-bounds children into free cells of the smaller grid
        # and commit the shrink as one undo step — no dialog. Only when
        # the smaller grid genuinely has no room does the error surface.
        if pname in ("grid_rows", "grid_cols"):
            ok, msg = self._validate_grid_shrink(node, pname, value)
            if not ok:
                planned, relocations = plan_grid_shrink_relocation(
                    node, pname, int(value),
                )
                if planned:
                    self._apply_grid_shrink_relocation(
                        node, pname, int(value), relocations,
                    )
                    return
                show_error(
                    tr("prop_commit.cannot_shrink_grid", "Cannot shrink grid"), msg,
                    parent=self.winfo_toplevel(),
                )
                self._refresh_row_after_reject(pname)
                return
        # Disabled-icon-colour advisory: the exported code has to run
        # a helper to swap the tinted image when the widget flips to
        # disabled state (CTk doesn't do it natively). Warn once per
        # pick, dismissable via ``~/.ctk_visual_builder/settings.json``
        # key ``advisory_image_color_disabled_dismissed``.
        if pname == "image_color_disabled" and value:
            self._maybe_show_disabled_icon_advisory()
        # Clamp geometry writes to the container's bounds — typed values
        # (Inspector entry, spinner, drag-scrub) used to accept anything,
        # so it was trivial to shove a widget outside the window via
        # Properties. Drag already snaps back at release; this closes
        # the same gap for keyboard-driven edits.
        value = self._clamp_to_container_bounds(node, pname, value)
        # Full-dict snapshot so `compute_derived` side-effect changes
        # (e.g. Image width→height recompute on preserve_aspect) end
        # up in the same undo entry as the primary commit. Without
        # this, the derived prop silently drifts during undo/redo.
        before_snapshot = dict(node.properties)
        self.project.update_property(self.current_id, pname, value)
        if getattr(self, "_suspend_history", False):
            return
        after_snapshot = dict(node.properties)
        changed = {
            k: (before_snapshot.get(k), after_snapshot.get(k))
            for k in set(before_snapshot) | set(after_snapshot)
            if before_snapshot.get(k) != after_snapshot.get(k)
        }
        if not changed:
            return
        if len(changed) == 1:
            (k, (b, a)), = changed.items()
            self.project.history.push(
                ChangePropertyCommand(self.current_id, k, b, a),
            )
            return
        self.project.history.push(
            MultiChangePropertyCommand(self.current_id, changed),
        )

    def _commit_extra_param(self, pname: str, value) -> None:
        """Commit an x.-prefixed enhancement param: write it onto
        ``WidgetNode.extra`` and record one undo step. Never touches
        ``properties`` directly as user intent — but stock-field
        SNAPSHOTS implied by the param (spec §11: percent/remain →
        stretch:grow on a fixed parent) are synced so the exported /
        saved representation stays 00-compatible and the canvas
        re-layouts immediately."""
        if self.current_id is None:
            return
        batch = getattr(self, "_batch_ids", None)
        if batch:
            self._commit_extra_param_batch(pname, value, batch)
            return
        from app.widgets.extra_params import (
            AXIS_KEY,
            axis_of_key,
            extra_key,
            param_set,
            sync_sizes,
        )
        key = extra_key(pname)
        if key is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        before = dict(node.extra or {})
        if not param_set(node, pname, value):
            return
        after = dict(node.extra or {})
        axis = axis_of_key(key)
        prop_changes: dict = {}
        if axis is not None:
            # Derived px is a plain number in the child's own size row;
            # sync it so the canvas / listeners see the new value.
            prop_changes = sync_sizes(node)
            for name, (_before, snap_value) in prop_changes.items():
                if snap_value is not None:
                    self.project.event_bus.publish(
                        "property_changed", self.current_id, name,
                        snap_value,
                    )
        if axis is not None and key == AXIS_KEY[axis]:
            # Mode switch changes which extra rows are visible (the
            # percent value row) — rebuild the whole panel.
            self._rebuild()
        else:
            self._refresh_extra_row(pname)
        if getattr(self, "_suspend_history", False):
            return
        self.project.history.push(
            ExtraParamCommand(
                self.current_id, before, after, prop_changes,
            ),
        )

    def _commit_extra_param_batch(self, pname: str, value, batch_ids) -> None:
        """Multi-select x. commit (spec §11): fan the param out to every
        widget in the batch (same widget_type), sync each widget's
        derived size rows, and record ONE undo step
        (MultiExtraParamCommand)."""
        from app.widgets.extra_params import (
            AXIS_KEY,
            axis_of_key,
            extra_key,
            param_set,
            sync_sizes,
        )
        key = extra_key(pname)
        if key is None:
            return
        axis = axis_of_key(key)
        entries: list = []
        for wid in batch_ids:
            node = self.project.get_widget(wid)
            if node is None:
                continue
            before = dict(node.extra or {})
            if not param_set(node, pname, value):
                continue
            after = dict(node.extra or {})
            prop_changes: dict = {}
            if axis is not None:
                prop_changes = sync_sizes(node)
                for name, (_before, snap_value) in prop_changes.items():
                    if snap_value is not None:
                        self.project.event_bus.publish(
                            "property_changed", wid, name, snap_value,
                        )
            entries.append((wid, before, after, prop_changes))
        if axis is not None and key == AXIS_KEY[axis]:
            # Mode switch changes which extra rows exist (percent value
            # row) — rebuild so the panel matches every batch node.
            self._rebuild()
        else:
            self._refresh_extra_row(pname)
        if not entries or getattr(self, "_suspend_history", False):
            return
        self.project.history.push(MultiExtraParamCommand(entries))

    def _prompt_extra_number(self, pname: str) -> None:
        """Inline prompt for an x. number row (main-axis percent)."""
        if self.current_id is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        from app.widgets.extra_params import param_get
        current = param_get(node, pname, default=50)
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(tr("props.label.percent", "Percent"))
        dialog.transient(self.winfo_toplevel())
        safe_grab_set(dialog)
        dialog.configure(bg="#2b2b2b")
        dialog.resizable(False, False)
        tk.Label(
            dialog, text=tr("props.label.percent", "Percent"),
            bg="#2b2b2b", fg="#cccccc", font=ui_font(10),
        ).pack(padx=14, pady=(12, 4), anchor="w")
        var = tk.StringVar(value=str(current))
        entry = tk.Entry(
            dialog, textvariable=var, width=10, bg="#1e1e1e",
            fg="#e8e8e8", insertbackground="#e8e8e8",
            relief="flat", highlightthickness=1,
            highlightbackground="#3a3a3a",
        )
        entry.pack(padx=14, pady=(0, 10), anchor="w")

        def _ok():
            raw = var.get().strip()
            try:
                parsed = int(raw)
            except (TypeError, ValueError):
                dialog.destroy()
                return
            parsed = max(1, min(100, parsed))
            dialog.destroy()
            self._commit_prop(pname, parsed)

        btn = tk.Button(
            dialog, text=tr("prop_commit.ok", "OK"), width=10,
            bg="#3b8ed0", fg="#ffffff", activebackground="#4f46e5",
            activeforeground="#ffffff", bd=0, relief="flat",
            font=ui_font(10, "bold"), command=_ok,
        )
        btn.pack(pady=(0, 12))
        dialog.bind("<Return>", lambda _e: _ok())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        entry.focus_set()

    def _popup_extra_enum_menu_at(
        self, pname: str, x_root: int, y_root: int,
    ) -> None:
        """Dropdown for an x.-prefixed enum row — options come from the
        param's row definition (``extra_options``), current value from
        ``WidgetNode.extra``."""
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        from app.widgets.extra_params import (
            extra_rows_for,
            param_get,
        )
        prop = next(
            (r for r in extra_rows_for(node) if r["name"] == pname), None,
        )
        if prop is None:
            return
        options = prop.get("extra_options") or ()
        if not options:
            return
        labels = prop.get("extra_display") or {}
        current = param_get(node, pname)
        menu = tk.Menu(self, tearoff=0, **menu_style())
        for opt in options:
            prefix = "• " if opt == current else "   "
            label_text = tr(f"props.extra.{opt}", labels.get(opt, opt))
            menu.add_command(
                label=f"{prefix}{label_text}",
                command=lambda v=opt, p=pname: self._commit_prop(p, v),
            )
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _commit_prop_batch(self, pname: str, value) -> None:
        """Multi-select commit: apply ``pname=value`` to every widget
        in ``_batch_ids`` (same widget_type as the primary) and push a
        single ``MultiWidgetPropertyCommand`` so one Ctrl+Z reverts the
        whole batch.

        Per-widget skips are silent and safe:
        - fields the widget's parent layout owns
          (``managed_geometry_disabled``) are never written;
        - grid_rows/grid_cols shrink is guard-checked per container
          (``_validate_grid_shrink``) — a container that would orphan a
          child is left untouched (no auto-repair across a batch);
        - geometry values pass through the container-bounds clamp.
        """
        primary = self.project.get_widget(self.current_id)
        if primary is None:
            return
        batch_ids = list(getattr(self, "_batch_ids", None) or ())
        if not batch_ids:
            return
        entries = apply_batch_prop_entries(
            self.project,
            batch_ids,
            primary.widget_type,
            pname,
            value,
            clamp=self._clamp_to_container_bounds,
            grid_guard=self._batch_grid_shrink_guard,
        )
        if not entries:
            return
        if getattr(self, "_suspend_history", False):
            return
        self.project.history.push(MultiWidgetPropertyCommand(entries))
        # Batch fan-out publishes property_changed per widget, so the
        # primary's cell may briefly re-render as mixed (empty) while
        # later siblings still carry their old values. Re-render the
        # affected row once every widget is settled — a shared value
        # then displays normally instead of leaving a stale blank.
        self._refresh_batch_row(pname)

    def _refresh_batch_row(self, pname: str) -> None:
        """Re-render one schema row after a batch commit so the cell
        reflects the post-batch aggregate (shared value or mixed-empty).
        """
        descriptor = self._current_descriptor()
        if descriptor is None:
            return
        prop = self._find_prop(descriptor, pname)
        iid = self._prop_iids.get(pname)
        if prop is None or iid is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        self._refresh_cell(iid, prop, node.properties.get(pname))

    def _batch_grid_shrink_guard(self, node, pname: str, value) -> bool:
        """Grid-shrink check used per widget during a batch commit.
        Unlike the single-selection path, a blocked container is simply
        skipped — we never auto-relocate children mid-batch and never
        pop an error for one widget of many.
        """
        if pname not in ("grid_rows", "grid_cols"):
            return True
        try:
            ok, _msg = self._validate_grid_shrink(node, pname, value)
        except (TypeError, ValueError):
            return True
        return ok

    # ------------------------------------------------------------------
    # Advisory dialog — disabled-icon tint requires runtime helper
    # ------------------------------------------------------------------
    _ADVISORY_KEY = "advisory_image_color_disabled_dismissed"

    def _maybe_show_disabled_icon_advisory(self) -> None:
        """Pop a one-shot warning when the user picks an
        ``image_color_disabled`` value. CTk has no native icon-tint-on-
        state-change mechanism, so the exported file can't just
        forward the builder's disabled colour — it needs a runtime
        helper to swap images. The exporter emits that helper + a
        comment per affected button; this dialog surfaces the same
        advisory at design time so the designer isn't surprised by
        the runtime behaviour.
        """
        from app.core.settings import load_settings, save_setting
        if load_settings().get(self._ADVISORY_KEY):
            return
        top = self.winfo_toplevel()
        dont_show = tk.BooleanVar(value=False)
        dialog = tk.Toplevel(top)
        dialog.title(tr("prop_commit.disabled_icon_colour", "Disabled icon colour"))
        dialog.transient(top)
        safe_grab_set(dialog)
        dialog.configure(bg="#2b2b2b")
        dialog.resizable(False, False)
        msg = tr(
            "prop_commit.disabled_icon_colour_msg",
            "Heads up — disabled-state icon colour isn't automatic.\n\n"
            "CTk swaps the button's text colour on state change, but\n"
            "images don't follow. The exporter adds a helper\n"
            "(_apply_icon_state) + a comment on every affected button\n"
            "so you can wire the swap from your own state-change code.\n",
        )
        lbl = tk.Label(
            dialog, text=msg, bg="#2b2b2b", fg="#cccccc",
            font=ui_font(10), justify="left", anchor="w",
            padx=20, pady=16,
        )
        lbl.pack(fill="x")
        chk = tk.Checkbutton(
            dialog, text=tr("prop_commit.dont_show_again", "Don't show this again"),
            variable=dont_show,
            bg="#2b2b2b", fg="#cccccc",
            activebackground="#2b2b2b", activeforeground="#ffffff",
            selectcolor="#2b2b2b", bd=0, padx=20,
            font=ui_font(10),
        )
        chk.pack(anchor="w", pady=(0, 12))

        def _on_ok():
            if dont_show.get():
                save_setting(self._ADVISORY_KEY, True)
            dialog.destroy()

        btn = tk.Button(
            dialog, text=tr("prop_commit.ok", "OK"), width=10,
            bg="#3b8ed0", fg="#ffffff",
            activebackground="#4f46e5", activeforeground="#ffffff",
            bd=0, font=ui_font(10, "bold"), relief="flat",
            command=_on_ok,
        )
        btn.pack(pady=(0, 16))
        dialog.bind("<Return>", lambda _e: _on_ok())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.update_idletasks()
        # Centre on parent.
        try:
            px = top.winfo_rootx()
            py = top.winfo_rooty()
            pw = top.winfo_width()
            ph = top.winfo_height()
            dw = dialog.winfo_width()
            dh = dialog.winfo_height()
            dialog.geometry(
                f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}",
            )
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Grid shrink validation
    # ------------------------------------------------------------------
    def _validate_grid_shrink(
        self, node, pname: str, value,
    ) -> tuple[bool, str]:
        """Block grid_rows/grid_cols changes that would orphan children.

        Returns ``(True, "")`` when the change is fine; otherwise
        ``(False, message)`` with a user-facing explanation listing the
        occupied row/column index.
        """
        try:
            new_val = int(value)
        except (TypeError, ValueError):
            return True, ""
        try:
            current = int(node.properties.get(pname, 1) or 1)
        except (TypeError, ValueError):
            current = 1
        if new_val >= current:
            return True, ""
        axis_key = "grid_row" if pname == "grid_rows" else "grid_column"
        max_used = -1
        for child in node.children:
            try:
                idx = int(child.properties.get(axis_key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if idx > max_used:
                max_used = idx
        if new_val <= max_used:
            unit_word = (
                tr("prop_commit.row", "row")
                if pname == "grid_rows"
                else tr("prop_commit.column", "column")
            )
            return False, (
                tr(
                    "prop_commit.grid_shrink_msg",
                    "Cannot shrink to {new_val} {unit}{plural} — "
                    "a child widget occupies {unit} {max_used}. "
                    "Move or delete that widget first.",
                ).format(
                    new_val=new_val,
                    unit=unit_word,
                    plural=("s" if new_val != 1 else ""),
                    max_used=max_used,
                )
            )
        return True, ""

    def _apply_grid_shrink_relocation(
        self, node, pname: str, new_val: int, relocations,
    ) -> None:
        """Commit a grid shrink together with its auto-repair moves.

        ``relocations`` comes from ``plan_grid_shrink_relocation`` —
        out-of-bounds children parked into free cells of the smaller
        grid. The container dimension change and every child's cell
        move are applied and bundled into ONE undo entry, so Ctrl+Z
        reverses the whole shrink in a single step (the same way the
        plain grid_rows/grid_cols edit is one step).
        """
        entries: list[tuple] = [(
            node.id,
            {pname: (node.properties.get(pname), new_val)},
        )]
        for child, row, col in relocations:
            changes = {}
            old_row = child.properties.get("grid_row")
            old_col = child.properties.get("grid_column")
            if old_row != row:
                changes["grid_row"] = (old_row, row)
            if old_col != col:
                changes["grid_column"] = (old_col, col)
            if changes:
                entries.append((child.id, changes))
        for widget_id, changes in entries:
            for name, (_before, after) in changes.items():
                self.project.update_property(widget_id, name, after)
        if getattr(self, "_suspend_history", False):
            return
        self.project.history.push(MultiWidgetPropertyCommand(entries))

    def _refresh_row_after_reject(self, pname: str) -> None:
        """Repaint the schema row for ``pname`` so the spinner / inline
        editor snaps back to the stored value when a commit is blocked.
        """
        if self.current_id is None:
            return
        descriptor = self._current_descriptor()
        if descriptor is None:
            return
        node = self.project.get_widget(self.current_id)
        if node is None:
            return
        prop = self._find_prop(descriptor, pname)
        iid = self._prop_iids.get(pname)
        if prop is not None and iid is not None:
            self._refresh_cell(iid, prop, node.properties.get(pname))

    # ------------------------------------------------------------------
    # Inline editor right-click menu
    # ------------------------------------------------------------------
    def _attach_inline_context_menu(self, entry, prop: dict | None) -> None:
        """Right-click on an inline tk.Entry overlay → Cut / Copy /
        Paste / Select All. For number rows, also offer two
        quick-fill commands that drop the schema's min / max value
        straight into the field. ``prop=None`` skips the min/max
        section (used for the multi-line text inline editor).
        """
        def _popup(event):
            menu = tk.Menu(entry, tearoff=0, **menu_style())
            has_selection = bool(entry.selection_present()) \
                if hasattr(entry, "selection_present") else False
            try:
                # ``selection_present`` may raise on stale widget — guard.
                has_selection = bool(entry.selection_present())
            except tk.TclError:
                has_selection = False
            _fg = menu_style().get("fg", "#cccccc")
            _dim = "#555555"
            menu.add_command(
                label=tr("prop_commit.cut", "Cut"),
                command=(
                    lambda: entry.event_generate("<<Cut>>")
                    if has_selection else None
                ),
                foreground=_fg if has_selection else _dim,
            )
            menu.add_command(
                label=tr("prop_commit.copy", "Copy"),
                command=(
                    lambda: entry.event_generate("<<Copy>>")
                    if has_selection else None
                ),
                foreground=_fg if has_selection else _dim,
            )
            menu.add_command(
                label=tr("prop_commit.paste", "Paste"),
                command=lambda: entry.event_generate("<<Paste>>"),
            )
            menu.add_separator()
            menu.add_command(
                label=tr("prop_commit.select_all", "Select All"),
                command=lambda: (
                    entry.select_range(0, tk.END),
                    entry.icursor(tk.END),
                ),
            )
            if prop is not None and prop.get("type") == "number":
                self._append_min_max_menu_items(menu, entry, prop)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind("<Button-3>", _popup, add="+")

    def _append_min_max_menu_items(self, menu, entry, prop) -> None:
        """Add ``Min: <value>`` / ``Max: <value>`` rows that, when
        clicked, replace the entry contents with the schema's
        clamp value. Lambdas in the schema are evaluated against the
        current widget's properties so context-sensitive bounds
        (e.g. corner_radius capped to half the widget height)
        resolve correctly.
        """
        node = (
            self.project.get_widget(self.current_id)
            if self.current_id else None
        )
        props = node.properties if node is not None else {}

        def _resolve(key):
            raw = prop.get(key)
            if callable(raw):
                try:
                    return raw(props)
                except Exception:
                    return None
            return raw

        lo = _resolve("min")
        hi = _resolve("max")
        if lo is None and hi is None:
            return

        def _replace(value):
            entry.delete(0, tk.END)
            entry.insert(0, str(value))
            entry.select_range(0, tk.END)
            entry.icursor(tk.END)
            entry.focus_set()

        menu.add_separator()
        if lo is not None:
            menu.add_command(
                label=tr("prop_commit.min", "Min: {val}").format(val=lo),
                command=lambda v=lo: _replace(v),
            )
        if hi is not None:
            menu.add_command(
                label=tr("prop_commit.max", "Max: {val}").format(val=hi),
                command=lambda v=hi: _replace(v),
            )

    # ------------------------------------------------------------------
    # Geometry bounds
    # ------------------------------------------------------------------
    def _clamp_to_container_bounds(self, node, pname: str, value):
        """Clamp x / y / width / height so the widget stays inside its
        container. Top-level widgets sit in the owning document's
        rectangle (the Main Window / Dialog); nested widgets in a
        ``place`` parent sit in that Frame's rectangle. Widgets under
        a managed layout (vbox / hbox / grid) skip the clamp — the
        layout manager owns their geometry and the x/y fields are
        either ignored (vbox/hbox) or paired with grid_row/column.
        """
        if pname not in ("x", "y", "width", "height", "corner_radius"):
            return value
        if pname == "corner_radius":
            try:
                v = int(value)
            except (TypeError, ValueError):
                return value
            try:
                w = int(node.properties.get("width", 0) or 0)
                h = int(node.properties.get("height", 0) or 0)
            except (TypeError, ValueError):
                w = h = 0
            cap = max(0, min(w, h)) if w > 0 and h > 0 else 0
            return max(0, min(v, cap) if cap > 0 else v)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return value
        from app.widgets.layout_schema import normalise_layout_type
        container_w, container_h = self._resolve_container_size(node)
        # If the node is under a managed-layout parent, skip — layout
        # manager controls placement/size.
        parent = node.parent
        if parent is not None:
            parent_layout = normalise_layout_type(
                parent.properties.get("layout_type", "place"),
            )
            if parent_layout != "place":
                return max(0, value) if pname in ("x", "y") else value
        if container_w <= 0 or container_h <= 0:
            return max(0, value) if pname in ("x", "y") else value
        try:
            node_w = int(node.properties.get("width", 0) or 0)
            node_h = int(node.properties.get("height", 0) or 0)
            node_x = int(node.properties.get("x", 0) or 0)
            node_y = int(node.properties.get("y", 0) or 0)
        except (TypeError, ValueError):
            node_w = node_h = node_x = node_y = 0
        if pname == "x":
            return max(0, min(value, max(0, container_w - node_w)))
        if pname == "y":
            return max(0, min(value, max(0, container_h - node_h)))
        if pname == "width":
            return max(1, min(value, max(1, container_w - node_x)))
        if pname == "height":
            return max(1, min(value, max(1, container_h - node_y)))
        return value

    def _resolve_container_size(self, node) -> tuple[int, int]:
        """Container dimensions for bound clamping. Top-level widgets
        → owning document (Main Window / Dialog); nested widgets →
        parent node's ``width``/``height`` properties.
        """
        parent = node.parent
        if parent is None:
            doc = self.project.find_document_for_widget(node.id)
            if doc is None:
                return 0, 0
            try:
                return int(getattr(doc, "width", 0) or 0), int(
                    getattr(doc, "height", 0) or 0,
                )
            except (TypeError, ValueError):
                return 0, 0
        try:
            return (
                int(parent.properties.get("width", 0) or 0),
                int(parent.properties.get("height", 0) or 0),
            )
        except (TypeError, ValueError):
            return 0, 0
