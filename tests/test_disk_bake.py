"""Disk bake (spec §11.5): derived size params (main-axis percent /
remainder, cross-axis percent) serialize as a plain number in the
child's own ``height`` / ``width`` — exactly what a user would type by
hand. ``stretch`` is left as the user set it, so stock 00 renders the
layout identically.

Acceptance:
- single remainder on a 300px vbox with fixed(50)+percent40%(120) →
  height=130
- three remainders on 300px → each 100
- hbox bakes width
- cross-axis percent bakes the cross row
- scroll-content parents are NOT baked
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


def test_remain_bakes_leftover_px():
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
    # The bake writes a plain number — never ``stretch``.
    assert "stretch" not in remain_disk["properties"]
    pct_disk = next(c for c in disk["children"]
                    if "percent" in str(c.get("_ctkmaker_meta")))
    assert pct_disk["properties"]["height"] == 120
    assert "stretch" not in pct_disk["properties"]
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
        assert "stretch" not in rd["properties"]


def test_cross_axis_percent_bakes_cross_row():
    parent = WidgetNode("CTkFrame", properties={
        "width": 400, "height": 100,
        "layout_type": "vbox", "layout_spacing": 0,
    })
    child = _child(height=30, extra={
        "cross_axis": {"mode": "percent", "percent": 50},
    })
    child.parent = parent
    parent.children.append(child)
    child_disk = parent.to_dict()["children"][0]
    # vbox cross axis = width → 50% of 400.
    assert child_disk["properties"]["width"] == 200
    assert "stretch" not in child_disk["properties"]


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
    assert "stretch" not in child_disk["properties"]


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
