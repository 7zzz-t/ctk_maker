"""Exporter: first-class percent children ship exact main-axis px.

A percent child (extra main_axis percent, spec §11) on a FIXED-axis
parent exports its computed px as the constructor height/width and packs
fill-cross only (no expand — the runtime must not stretch it). Free-axis
parents (scroll content / auto) degrade to content: the stored size is
kept. Remain children keep the grow path.
"""
from __future__ import annotations

from app.core.document import Document
from app.core.project import Project
from app.core.widget_node import WidgetNode
from app.io.code_exporter import generate_code


def _frame(widget_type="CTkFrame", **props):
    from app.widgets.registry import get_descriptor
    desc = get_descriptor(widget_type)
    merged = dict(desc.default_properties)
    merged.update(props)
    return WidgetNode(widget_type, properties=merged)


def _project_with(parent, children):
    project = Project()
    doc = Document(name="MainWindow")
    doc.window_properties["width"] = 600
    doc.window_properties["height"] = 400
    project.documents = [doc]
    project.active_document_id = doc.id
    project.add_widget(parent, document_id=doc.id)
    for child in children:
        child.parent = parent
        parent.children.append(child)
    return generate_code(project)


def _percent_child(mode="percent", percent=40, axis_size=30):
    child = _frame(width=100, height=axis_size)
    child.properties["stretch"] = "grow"  # what the stock snapshot syncs
    child.extra = {"main_axis": {"mode": mode, "percent": percent}}
    return child


def test_vbox_percent_emits_exact_px_without_expand():
    parent = _frame(layout_type="vbox", width=300, height=300)
    code = _project_with(parent, [_percent_child(percent=40)])
    # 40% of parent height 300 → 120, shipped as the constructor px.
    assert "height=120" in code
    # No main-axis expand — the child must keep its exact height.
    assert "expand=True" not in code


def test_hbox_percent_emits_width_px():
    parent = _frame(layout_type="hbox", width=300, height=300)
    code = _project_with(parent, [_percent_child(percent=40)])
    assert "width=120" in code


def test_scroll_content_percent_degrades_to_stored_size():
    # Free-axis parent (scrollable content): percent has no fixed
    # baseline — the stored height is kept, no px override.
    parent = _frame(widget_type="CTkScrollableFrame",
                    layout_type="vbox", width=300, height=200)
    code = _project_with(parent, [_percent_child(percent=40, axis_size=30)])
    assert "height=120" not in code
    assert "height=30" in code


def test_remain_child_keeps_grow_path():
    parent = _frame(layout_type="vbox", width=300, height=300)
    code = _project_with(parent, [_percent_child(mode="remain")])
    assert "expand=True" in code
