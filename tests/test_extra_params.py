"""Extra-param semantics layer (spec §11): row defs, typed get/set on
WidgetNode.extra, auto-height detection incl. legacy disk forms."""
from __future__ import annotations

from app.core.widget_node import WidgetNode
from app.widgets import extra_params as ep


def _widget(widget_type, parent=None, height=None, **props):
    node = WidgetNode(widget_type, properties=dict(props))
    if height is not None:
        node.properties["height"] = height
    if parent is not None:
        node.parent = parent
        parent.children.append(node)
    return node


def _frame_parent(layout="vbox", height=200):
    parent = WidgetNode("CTkFrame", properties={
        "layout_type": layout, "height": height, "width": 200,
    })
    return parent


def test_ui_name_roundtrip():
    assert ep.ui_name("height_mode") == "x.height_mode"
    assert ep.extra_key("x.height_mode") == "height_mode"
    assert ep.extra_key("height_mode") is None


def test_ctkframe_rows_include_height_mode_only():
    frame = _widget("CTkFrame", height=150)
    names = [r["name"] for r in ep.extra_rows_for(frame)]
    assert "x.height_mode" in names
    assert "x.main_axis" not in names


def test_vbox_child_gets_main_axis_rows():
    parent = _frame_parent("vbox")
    child = _widget("CTkFrame", parent=parent, height=40)
    names = [r["name"] for r in ep.extra_rows_for(child)]
    assert "x.height_mode" in names          # still a CTkFrame
    assert "x.main_axis" in names
    assert "x.main_axis.percent" in names


def test_place_child_gets_no_main_axis():
    parent = WidgetNode("CTkFrame", properties={"layout_type": "place"})
    child = _widget("CTkButton", parent=parent)
    names = [r["name"] for r in ep.extra_rows_for(child)]
    assert names == []


def test_param_set_get_roundtrip():
    node = _widget("CTkFrame", height=150)
    assert ep.param_set(node, "x.height_mode", ep.H_AUTO) is True
    assert ep.param_get(node, "x.height_mode") == ep.H_AUTO
    assert node.extra == {"height_mode": "auto"}
    # Setting the same value again reports no change.
    assert ep.param_set(node, "x.height_mode", ep.H_AUTO) is False


def test_nested_percent_param():
    parent = _frame_parent("vbox")
    child = _widget("CTkFrame", parent=parent, height=40)
    assert ep.param_set(child, "x.main_axis", ep.M_PERCENT) is True
    assert ep.param_set(child, "x.main_axis.percent", 40) is True
    assert ep.param_get(child, "x.main_axis.percent") == 40
    assert child.extra == {"main_axis": {"mode": "percent", "percent": 40}}
    assert ep.param_get(child, "x.main_axis.percent", default=10) == 40


def test_is_auto_height_first_class():
    node = _widget("CTkFrame", height=150)
    assert ep.is_auto_height(node) is False
    ep.param_set(node, "x.height_mode", ep.H_AUTO)
    assert ep.is_auto_height(node) is True
    ep.param_set(node, "x.height_mode", ep.H_FIXED)
    assert ep.is_auto_height(node) is False


def test_is_auto_height_legacy_forms():
    # Pre-height_mode: height == 0 and top-level disk marker.
    zero = _widget("CTkFrame", height=0)
    assert ep.is_auto_height(zero) is True
    marker = _widget("CTkFrame", height=200)
    marker._ctkmaker_auto_height = True
    assert ep.is_auto_height(marker) is True
    # Non-CTkFrame with height 0 is NOT auto.
    label = _widget("CTkLabel", height=0)
    assert ep.is_auto_height(label) is False


# ---------------------------------------------------------------------
# main_axis — percent / remainder resolution
# ---------------------------------------------------------------------
def test_main_axis_mode_default_and_override():
    parent = _frame_parent("vbox")
    child = _widget("CTkButton", parent=parent)
    assert ep.main_axis_mode(child) == ep.M_CONTENT
    ep.param_set(child, "x.main_axis", ep.M_PERCENT)
    assert ep.main_axis_mode(child) == ep.M_PERCENT
    ep.param_set(child, "x.main_axis.percent", 40)
    assert ep.main_axis_percent(child) == 40


def test_parent_main_axis_depends_on_layout():
    vbox_parent = _frame_parent("vbox")
    vchild = _widget("CTkButton", parent=vbox_parent)
    assert ep.parent_main_axis(vchild) == "height"
    hbox_parent = _frame_parent("hbox")
    hchild = _widget("CTkButton", parent=hbox_parent)
    assert ep.parent_main_axis(hchild) == "width"
    free = _widget("CTkButton")   # no parent
    assert ep.parent_main_axis(free) is None


def test_parent_main_px_fixed_vs_free():
    vbox_parent = _frame_parent("vbox", height=200)
    child = _widget("CTkButton", parent=vbox_parent)
    assert ep.parent_main_px(child) == 200
    # Scrollable-frame content axis is free.
    sf = WidgetNode("CTkScrollableFrame", properties={
        "layout_type": "vbox", "height": 520,
    })
    sf_child = _widget("CTkButton", parent=sf)
    assert ep.parent_main_px(sf_child) is None
    # Auto-height parent (extra) is free.
    auto_parent = _frame_parent("vbox", height=200)
    auto_parent.extra = {"height_mode": "auto"}
    auto_child = _widget("CTkButton", parent=auto_parent)
    assert ep.parent_main_px(auto_child) is None
    # Height 0 parent is free.
    zero_parent = _frame_parent("vbox", height=0)
    zero_child = _widget("CTkButton", parent=zero_parent)
    assert ep.parent_main_px(zero_child) is None


def test_percent_px_rounds_against_fixed_parent():
    parent = _frame_parent("vbox", height=200)
    child = _widget("CTkButton", parent=parent)
    ep.param_set(child, "x.main_axis", ep.M_PERCENT)
    ep.param_set(child, "x.main_axis.percent", 40)
    assert ep.percent_px(child, 200) == 80
    assert ep.percent_px(child, None) is None
    content = _widget("CTkButton", parent=parent)
    assert ep.percent_px(content, 200) is None


def test_stock_stretch_snapshot_rules():
    parent = _frame_parent("vbox", height=200)
    percent_child = _widget("CTkButton", parent=parent)
    ep.param_set(percent_child, "x.main_axis", ep.M_PERCENT)
    assert ep.stock_stretch_snapshot(percent_child) == "grow"
    remain_child = _widget("CTkButton", parent=parent)
    ep.param_set(remain_child, "x.main_axis", ep.M_REMAIN)
    assert ep.stock_stretch_snapshot(remain_child) == "grow"
    # Free-axis parent → no snapshot override (child keeps its stretch).
    sf = WidgetNode("CTkScrollableFrame", properties={
        "layout_type": "vbox", "height": 520,
    })
    sf_child = _widget("CTkButton", parent=sf)
    ep.param_set(sf_child, "x.main_axis", ep.M_PERCENT)
    assert ep.stock_stretch_snapshot(sf_child) is None
    content_child = _widget("CTkButton", parent=parent)
    assert ep.stock_stretch_snapshot(content_child) is None


def test_sync_stock_snapshot_writes_grow_and_reports_changes():
    parent = _frame_parent("vbox", height=200)
    child = _widget("CTkButton", parent=parent)
    ep.param_set(child, "x.main_axis", ep.M_PERCENT)
    changes = ep.sync_stock_snapshot(child)
    assert changes == {"stretch": (None, "grow")}
    assert child.properties["stretch"] == "grow"
    # Idempotent — second sync reports no change.
    assert ep.sync_stock_snapshot(child) == {}


def test_sync_remain_on_fixed_parent_and_content_preserves_stretch():
    parent = _frame_parent("vbox", height=200)
    remain = _widget("CTkButton", parent=parent)
    ep.param_set(remain, "x.main_axis", ep.M_REMAIN)
    assert ep.sync_stock_snapshot(remain)["stretch"][1] == "grow"
    # content mode never overrides a user-chosen stretch.
    fixed = _widget("CTkButton", parent=parent, stretch="fixed")
    ep.param_set(fixed, "x.main_axis", ep.M_CONTENT)
    assert ep.sync_stock_snapshot(fixed) == {}
    assert fixed.properties["stretch"] == "fixed"


def test_sync_free_parent_leaves_stretch_untouched():
    sf = WidgetNode("CTkScrollableFrame", properties={
        "layout_type": "vbox", "height": 520,
    })
    child = _widget("CTkButton", parent=sf, stretch="fixed")
    ep.param_set(child, "x.main_axis", ep.M_PERCENT)
    assert ep.sync_stock_snapshot(child) == {}
    assert child.properties["stretch"] == "fixed"
