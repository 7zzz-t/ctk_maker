"""Multi-select batch property editing.

The Properties panel keeps rendering the primary selection while 2+
same-type widgets are selected; every commit fans out to the whole set
via ``apply_batch_prop_entries`` and lands as ONE undo step
(``MultiWidgetPropertyCommand``).

Covers the pure application helper:
  - same-type fan-out with per-widget before/after snapshots
  - widget_type filtering
  - layout-managed field skipping (managed_geometry_disabled)
  - per-widget clamp hook
  - per-widget grid guard hook (shrink blocked -> skipped)
"""
from __future__ import annotations

from app.core.document import Document
from app.core.project import Project
from app.core.widget_node import WidgetNode
from app.ui.properties_panel.panel_commit import apply_batch_prop_entries


def _make_project():
    project = Project()
    doc = Document(name="MainWindow")
    doc.window_properties["width"] = 600
    doc.window_properties["height"] = 400
    project.documents = [doc]
    project.active_document_id = doc.id
    return project, doc


def _add_button(project, doc, parent_id=None, **extra):
    from app.widgets.registry import get_descriptor
    desc = get_descriptor("CTkButton")
    props = dict(desc.default_properties)
    props.update(extra)
    btn = WidgetNode(widget_type="CTkButton", properties=props)
    project.add_widget(btn, parent_id=parent_id, document_id=doc.id)
    return btn


def test_batch_text_update_produces_entries_and_updates_model():
    project, doc = _make_project()
    b1 = _add_button(project, doc, text="One")
    b2 = _add_button(project, doc, text="Two")
    b3 = _add_button(project, doc, text="Three")
    entries = apply_batch_prop_entries(
        project, [b1.id, b2.id, b3.id], "CTkButton", "text", "Renamed",
    )
    assert len(entries) == 3
    assert entries[0] == (b1.id, {"text": ("One", "Renamed")})
    # Model already updated through project.update_property.
    assert b1.properties["text"] == "Renamed"
    assert b2.properties["text"] == "Renamed"
    assert b3.properties["text"] == "Renamed"


def test_widget_type_filter_skips_other_kinds():
    project, doc = _make_project()
    b1 = _add_button(project, doc, text="One")
    from app.widgets.registry import get_descriptor
    lbl = WidgetNode(
        widget_type="CTkLabel",
        properties=dict(get_descriptor("CTkLabel").default_properties),
    )
    project.add_widget(lbl, document_id=doc.id)
    entries = apply_batch_prop_entries(
        project, [b1.id, lbl.id], "CTkButton", "text", "X",
    )
    assert len(entries) == 1
    assert entries[0][0] == b1.id
    assert lbl.properties["text"] != "X"


def test_layout_managed_fields_are_skipped():
    # Two buttons inside a vbox frame: width is owned by the parent
    # (fill/grow cross-axis), height stays user-editable.
    project, doc = _make_project()
    from app.widgets.registry import get_descriptor
    frame = WidgetNode(
        widget_type="CTkFrame",
        properties=dict(get_descriptor("CTkFrame").default_properties),
    )
    frame.properties["layout_type"] = "vbox"
    frame.properties["width"] = 200
    frame.properties["height"] = 200
    project.add_widget(frame, document_id=doc.id)
    b1 = _add_button(project, doc, parent_id=frame.id,
                     text="A", width=80, height=30, stretch="fill")
    b2 = _add_button(project, doc, parent_id=frame.id,
                     text="B", width=80, height=30, stretch="fill")
    # width -> managed (parent vbox owns cross-axis) -> no entries.
    entries_w = apply_batch_prop_entries(
        project, [b1.id, b2.id], "CTkButton", "width", 300,
    )
    assert entries_w == []
    assert b1.properties["width"] == 80
    # height -> user-owned on a vbox fill child -> applied.
    entries_h = apply_batch_prop_entries(
        project, [b1.id, b2.id], "CTkButton", "height", 45,
    )
    assert len(entries_h) == 2
    assert b1.properties["height"] == 45
    assert b2.properties["height"] == 45


def test_clamp_hook_bounds_value_per_widget():
    project, doc = _make_project()
    b1 = _add_button(project, doc, text="A", width=80)
    b2 = _add_button(project, doc, text="B", width=90)
    entries = apply_batch_prop_entries(
        project, [b1.id, b2.id], "CTkButton", "width", 999,
        clamp=lambda node, pname, value: min(value, 100),
    )
    assert len(entries) == 2
    assert b1.properties["width"] == 100
    assert b2.properties["width"] == 100
    # Clamped value is what lands in the undo snapshot too.
    assert entries[0][1]["width"] == (80, 100)


def test_grid_guard_skips_blocked_widget_silently():
    project, doc = _make_project()
    b1 = _add_button(project, doc, text="A")
    b2 = _add_button(project, doc, text="B")
    entries = apply_batch_prop_entries(
        project, [b1.id, b2.id], "CTkButton", "text", "X",
        grid_guard=lambda node, pname, value: node.id != b1.id,
    )
    assert len(entries) == 1
    assert entries[0][0] == b2.id
    assert b1.properties["text"] != "X"
    assert b2.properties["text"] == "X"


def test_unchanged_value_contributes_no_entry():
    project, doc = _make_project()
    b1 = _add_button(project, doc, text="Same")
    b2 = _add_button(project, doc, text="Same")
    entries = apply_batch_prop_entries(
        project, [b1.id, b2.id], "CTkButton", "text", "Same",
    )
    assert entries == []
