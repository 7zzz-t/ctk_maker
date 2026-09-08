"""Disk bake (spec §11.5): percent / remainder children serialize as
stock 00 parameters — stretch=fill + exact main-axis px — so stock 00
renders the layout pixel-identical to the 02 canvas. In-memory extra
keeps the responsive semantics.

Acceptance:
- single remainder on a 300px vbox with fixed(50)+percent40%(120) →
  stretch=fill, height=130
- three remainders on 300px → each 100, fill
- hbox bakes width
- scroll-content and auto-height parents are NOT baked
- to_dict is idempotent across a from_dict round-trip
- in-memory nodes keep their own height / stretch (no mutation)
"""
from __future__ import annotations

from app.core.widget_node import WidgetNode


def _child(height=40, extra=None, **props):
    node = WidgetNode("CTkFrame", properties={
        "width": 100, "height": height, **props,
    })
    if extra is not None:
        node.extra = dict(extra)
    return node


def _vbox(children, height=300, spacing=0):
    parent = WidgetNode("CTkFrame", properties={
        "width": 300, "height": height,
        "layout_type": "vbox", "layout_spacing": spacing,
    })
    for c in children:
        c.parent = parent
        parent.children.append(c)
    return parent


def _remain():
    return _child(extra={"main_axis": {"mode": "remain"}})


def _percent(pct):
    return _child(extra={"main_axis": {"mode": "percent", "percent": pct}})


def test_remain_bakes_to_fill_with_leftover_px():
    parent = _vbox([
        _child(height=50),          # fixed
        _percent(40),               # 120 px
        _remain(),
    ], height=300)
    disk = parent.to_dict()
    remain_disk = next(c for c in disk["children"]
                       if "remain" in str(c.get("_ctkmaker_meta")))
    # avail = 300 - 50 - 120 = 130 → the single remainder row.
    assert remain_disk["properties"]["height"] == 130
    assert remain_disk["properties"]["stretch"] == "fill"
    pct_disk = next(c for c in disk["children"]
                    if "percent" in str(c.get("_ctkmaker_meta")))
    assert pct_disk["properties"]["height"] == 120
    assert pct_disk["properties"]["stretch"] == "fill"
    # In-memory nodes untouched.
    remain_node = next(c for c in parent.children
                       if c.extra.get("main_axis", {}).get("mode") == "remain")
    assert remain_node.properties["height"] == 40
    assert remain_node.properties.get("stretch") is None


def test_multiple_remainders_split_the_leftover():
    parent = _vbox([_remain(), _remain(), _remain()], height=300)
    disk = parent.to_dict()
    remains = [c for c in disk["children"] if c.get("_ctkmaker_meta")]
    assert len(remains) == 3
    for rd in remains:
        assert rd["properties"]["height"] == 100
        assert rd["properties"]["stretch"] == "fill"


def test_hbox_bakes_width():
    parent = WidgetNode("CTkFrame", properties={
        "width": 400, "height": 100,
        "layout_type": "hbox", "layout_spacing": 0,
    })
    pct = _percent(25)
    pct.parent = parent
    parent.children.append(pct)
    disk = parent.to_dict()
    child_disk = disk["children"][0]
    assert child_disk["properties"]["width"] == 100
    assert child_disk["properties"]["stretch"] == "fill"


def test_no_bake_for_scroll_parent():
    # Scroll content has no fixed baseline.
    sf = WidgetNode("CTkScrollableFrame", properties={
        "layout_type": "vbox", "width": 300, "height": 520,
    })
    remain = _remain()
    remain.parent = sf
    sf.children.append(remain)
    disk = sf.to_dict()
    child_disk = disk["children"][0]
    assert child_disk["properties"].get("height") == 40
    assert child_disk["properties"].get("stretch") is None


def test_bake_is_idempotent_across_roundtrip():
    parent = _vbox([_child(height=50), _percent(40), _remain()], height=300)
    first = parent.to_dict()
    # from_dict → to_dict reproduces the same disk form.
    restored = WidgetNode.from_dict(first)
    second = restored.to_dict()
    assert first == second
