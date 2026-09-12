"""Top-down cascade of axis-derived sizes.

``sync_sizes`` only bakes the rows of the node it is handed, but a
child's derived px is computed from its parent's *current* size — so a
change high in the tree has to ripple down. ``sync_sizes_cascade`` does
that, per node, idempotently.
"""

from app.core.widget_node import WidgetNode
from app.widgets.extra_params import (
    MAIN_AXIS,
    MAIN_PERCENT,
    M_PERCENT,
    param_set,
    sync_sizes,
    sync_sizes_cascade,
    ui_name,
)


def _frame(properties: dict) -> WidgetNode:
    return WidgetNode(widget_type="CTkFrame", properties=dict(properties))


def _attach(parent: WidgetNode, child: WidgetNode) -> None:
    child.parent = parent
    parent.children.append(child)


def _half_of_parent(node: WidgetNode) -> None:
    assert param_set(node, ui_name(MAIN_AXIS), M_PERCENT)
    assert param_set(node, ui_name(f"{MAIN_AXIS}.{MAIN_PERCENT}"), 50)


def _tree():
    root = _frame({"layout_type": "vbox", "width": 400, "height": 300})
    a = _frame({"layout_type": "vbox", "width": 400, "height": 100})
    b = _frame({"width": 400, "height": 50})
    _attach(root, a)
    _attach(a, b)
    _half_of_parent(a)
    _half_of_parent(b)
    return root, a, b


def test_one_level_leaves_the_grandchild_stale():
    _root, a, b = _tree()
    sync_sizes(a)
    assert a.properties["height"] == 150      # 50% of the 300 container
    assert b.properties["height"] == 50       # still the old value


def test_cascade_refreshes_descendants_top_down():
    _root, a, b = _tree()
    sync_sizes_cascade(a)
    assert a.properties["height"] == 150
    assert b.properties["height"] == 75       # 50% of a's new 150


def test_cascade_is_idempotent():
    _root, a, b = _tree()
    first = sync_sizes_cascade(a)
    assert set(first) == {a.id, b.id}
    assert sync_sizes_cascade(a) == {}        # nothing left to move
    assert a.properties["height"] == 150
    assert b.properties["height"] == 75


def test_cascade_leaves_stretch_alone():
    root = _frame({"layout_type": "vbox", "width": 400, "height": 300})
    a = _frame({"width": 400, "height": 100, "stretch": "fill"})
    _attach(root, a)
    _half_of_parent(a)
    sync_sizes_cascade(a)
    assert a.properties["height"] == 150
    assert a.properties["stretch"] == "fill"
