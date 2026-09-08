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
