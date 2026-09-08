"""Auto-height disk mapping (02 → stock-00 compatible .ctkproj).

In memory, a CTkFrame ``height == 0`` is auto-height (content-sized).
Stock CTkMaker (00) renders 0-height frames as invisible, so the disk
form carries a visible snapshot height (200) plus a builder-only marker
key ``_ctkmaker_auto_height``.

The marker lives at the widget's TOP level, never inside ``properties``:
stock 00 forwards every ``properties`` key to the CTk constructor, so a
property-key marker crashes with "not supported arguments" (verified).
Top-level unknown keys are ignored by 00's loader; 00's saver drops
them (file degrades to the fixed snapshot height, per spec).

- ``to_dict``:  height 0  →  height=200 (properties) + top-level marker
- ``from_dict``: marker present → height restored to 0
- legacy bare ``height=0`` files (no marker) load as auto and upgrade
  to the snapshot form on the next save
"""
from __future__ import annotations

from app.core.widget_node import WidgetNode


def _frame(height: int, **extra) -> WidgetNode:
    props = {"x": 0, "y": 0, "width": 100, "height": height}
    props.update(extra)
    return WidgetNode("CTkFrame", properties=props)


def test_auto_frame_disk_form_carries_snapshot_and_top_level_marker():
    node = _frame(0)
    disk = node.to_dict()
    assert disk["properties"]["height"] == 200
    assert disk["_ctkmaker_auto_height"] is True
    # properties must stay CTk-constructor-safe (stock 00 forwards every
    # key) — the marker is NOT inside properties.
    assert "_ctkmaker_auto_height" not in disk["properties"]
    # In-memory node is untouched (still auto).
    assert node.properties["height"] == 0
    assert "_ctkmaker_auto_height" not in node.properties


def test_roundtrip_restores_auto_height_in_memory():
    node = _frame(0)
    restored = WidgetNode.from_dict(node.to_dict())
    assert restored.properties["height"] == 0
    assert not hasattr(restored, "_ctkmaker_auto_height")


def test_non_zero_height_frame_is_untouched():
    node = _frame(150)
    disk = node.to_dict()
    assert disk["properties"]["height"] == 150
    assert "_ctkmaker_auto_height" not in disk


def test_only_ctkframe_gets_mapped():
    # A CTkLabel (or any non-CTkFrame) with height 0 is left as-is —
    # the auto-height semantics are CTkFrame-only.
    label = WidgetNode("CTkLabel", properties={"height": 0})
    disk = label.to_dict()
    assert disk["properties"]["height"] == 0
    assert "_ctkmaker_auto_height" not in disk


def test_legacy_bare_zero_loads_as_auto_and_upgrades_on_save():
    # Pre-mapping 02 files stored height=0 with no marker.
    legacy = WidgetNode.from_dict({
        "id": "legacy-1", "name": "f", "widget_type": "CTkFrame",
        "properties": {"height": 0},
    })
    assert legacy.properties["height"] == 0
    disk = legacy.to_dict()
    assert disk["properties"]["height"] == 200
    assert disk["_ctkmaker_auto_height"] is True


def test_nested_auto_frame_is_mapped_recursively():
    parent = _frame(150)
    auto = _frame(0)
    auto.parent = parent
    parent.children.append(auto)
    disk = parent.to_dict()
    assert len(disk["children"]) == 1
    child_disk = disk["children"][0]
    assert child_disk["properties"]["height"] == 200
    assert child_disk["_ctkmaker_auto_height"] is True
    restored = WidgetNode.from_dict(disk)
    assert restored.children[0].properties["height"] == 0
