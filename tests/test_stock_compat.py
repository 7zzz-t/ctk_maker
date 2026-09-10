"""Stock-00 save-time normalization (spec §9.4).

A ``CTkScrollableFrame`` (the only composite widget) under a ``place``
/ unset parent makes stock 00 crash on load. Saving must rewrite that
parent to a managed layout so the file opens in stock 00.
"""
from __future__ import annotations

from app.core.document import Document
from app.core.project import Project
from app.core.widget_node import WidgetNode
from app.io.stock_compat import (
    COMPOSITE_WIDGET_TYPES,
    SAFE_FALLBACK_LAYOUT,
    normalize_document_for_stock,
    normalize_project_for_stock,
)


def _node(widget_type, **props):
    from app.widgets.registry import get_descriptor
    desc = get_descriptor(widget_type)
    merged = dict(desc.default_properties) if desc else {}
    merged.update(props)
    return WidgetNode(widget_type, properties=merged)


def _doc_with(roots, window_layout=None):
    project = Project()
    doc = Document(name="MainWindow")
    doc.window_properties["width"] = 600
    doc.window_properties["height"] = 400
    if window_layout is not None:
        doc.window_properties["layout_type"] = window_layout
    project.documents = [doc]
    project.active_document_id = doc.id
    for root in roots:
        project.add_widget(root, document_id=doc.id)
    return project, doc


def test_scrollableframe_is_the_composite_set():
    # Guards the detection constant: only descriptors overriding
    # ``canvas_anchor`` are composite.
    assert COMPOSITE_WIDGET_TYPES == frozenset({"CTkScrollableFrame"})


def test_place_window_holding_scrollableframe_is_rewritten():
    sf = _node("CTkScrollableFrame", x=10, y=10, width=580, height=580)
    project, doc = _doc_with([sf], window_layout="place")
    fixes = normalize_project_for_stock(project)
    assert doc.window_properties["layout_type"] == SAFE_FALLBACK_LAYOUT
    assert fixes and fixes[0][0].startswith("window:")


def test_unset_window_layout_is_treated_as_place():
    sf = _node("CTkScrollableFrame", x=0, y=0, width=300, height=300)
    project, doc = _doc_with([sf])          # no layout_type key at all
    normalize_project_for_stock(project)
    assert doc.window_properties["layout_type"] == SAFE_FALLBACK_LAYOUT


def test_place_container_holding_scrollableframe_is_rewritten():
    sf = _node("CTkScrollableFrame", x=5, y=5, width=550, height=520)
    holder = _node("CTkTabview", x=10, y=10)
    holder.properties.pop("layout_type", None)      # unset → place
    project, doc = _doc_with([holder], window_layout="vbox")
    holder.children.append(sf)
    sf.parent = holder
    fixes = normalize_project_for_stock(project)
    assert holder.properties["layout_type"] == SAFE_FALLBACK_LAYOUT
    assert any(owner == holder.id for owner, _b, _a in fixes)
    # The window itself was already managed — untouched.
    assert doc.window_properties["layout_type"] == "vbox"


def test_managed_parent_is_left_untouched():
    sf = _node("CTkScrollableFrame", width=300, height=300)
    parent = _node("CTkFrame", layout_type="vbox", width=300, height=300)
    project, doc = _doc_with([parent], window_layout="vbox")
    parent.children.append(sf)
    sf.parent = parent
    assert normalize_project_for_stock(project) == []
    assert parent.properties["layout_type"] == "vbox"
    assert doc.window_properties["layout_type"] == "vbox"


def test_place_parent_without_composite_is_left_untouched():
    plain = _node("CTkFrame", width=100, height=40)
    project, doc = _doc_with([plain], window_layout="place")
    assert normalize_project_for_stock(project) == []
    assert doc.window_properties["layout_type"] == "place"


def test_normalization_is_idempotent():
    sf = _node("CTkScrollableFrame", width=300, height=300)
    project, doc = _doc_with([sf], window_layout="place")
    assert normalize_project_for_stock(project)
    assert normalize_project_for_stock(project) == []
    assert doc.window_properties["layout_type"] == SAFE_FALLBACK_LAYOUT


def test_normalize_document_helper_matches_project_level():
    sf = _node("CTkScrollableFrame", width=300, height=300)
    _project, doc = _doc_with([sf], window_layout="place")
    fixes = normalize_document_for_stock(doc)
    assert fixes
    assert doc.window_properties["layout_type"] == SAFE_FALLBACK_LAYOUT
