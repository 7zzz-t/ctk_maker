"""WidgetNode.extra serialisation — builder-only enhancement params
(_ctkmaker_meta), the mechanism that survives the auto-height removal.

Acceptance: extra round-trips through the top-level _ctkmaker_meta key,
properties stays CTk-constructor-safe, empty extra emits no key,
nested children restore recursively. Old files that carry the removed
_ctkmaker_auto_height marker simply ignore it (loaded height is kept).
"""
from __future__ import annotations

from app.core.widget_node import WidgetNode


def _frame(height=150, **props):
    return WidgetNode("CTkFrame", properties={
        "x": 0, "y": 0, "width": 100, "height": height, **props,
    })


def test_extra_roundtrips_through_top_level_meta():
    node = _frame()
    node.extra = {"main_axis": {"mode": "percent", "percent": 40}}
    disk = node.to_dict()
    assert disk["_ctkmaker_meta"] == {
        "main_axis": {"mode": "percent", "percent": 40},
    }
    # properties stays CTk-safe — no meta leakage.
    assert "_ctkmaker_meta" not in disk["properties"]
    restored = WidgetNode.from_dict(disk)
    assert restored.extra == node.extra
    assert "_ctkmaker_meta" not in restored.properties


def test_empty_extra_emits_no_meta_key():
    node = _frame()
    disk = node.to_dict()
    assert "_ctkmaker_meta" not in disk
    restored = WidgetNode.from_dict(disk)
    assert restored.extra == {}


def test_nested_extra_is_restored_recursively():
    parent = _frame()
    child = _frame()
    child.extra = {"main_axis": {"mode": "remain"}}
    child.parent = parent
    parent.children.append(child)
    disk = parent.to_dict()
    assert disk["children"][0]["_ctkmaker_meta"] == {
        "main_axis": {"mode": "remain"},
    }
    restored = WidgetNode.from_dict(disk)
    assert restored.children[0].extra == {"main_axis": {"mode": "remain"}}


def test_removed_auto_marker_is_ignored_on_load():
    # Files written while the height_mode feature existed carry a
    # top-level _ctkmaker_auto_height marker + snapshot height (200).
    # After the removal those load as a plain fixed frame (marker is
    # ignored, height kept) — no crash, no auto semantics.
    data = {
        "id": "old-1", "name": "f", "widget_type": "CTkFrame",
        "properties": {"height": 200, "width": 100},
        "_ctkmaker_auto_height": True,
    }
    node = WidgetNode.from_dict(data)
    assert node.properties["height"] == 200
    assert node.extra == {}
