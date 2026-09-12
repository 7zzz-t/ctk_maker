"""Top-down cascade of axis-derived sizes.

``sync_sizes`` only bakes the rows of the node it is handed, but a
child's derived px is computed from its parent's *current* size — so a
change high in the tree has to ripple down. ``sync_sizes_cascade`` does
that, per node, idempotently.
"""

from app.core.widget_node import WidgetNode
from app.widgets.extra_params import (
    CROSS_AXIS,
    C_PERCENT,
    MAIN_AXIS,
    MAIN_PERCENT,
    M_FIXED,
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


class _FakeProject:
    """Just enough Project for a command round-trip."""

    def __init__(self, nodes):
        self._nodes = {n.id: n for n in nodes}

    def get_widget(self, widget_id):
        return self._nodes.get(widget_id)

    def update_property(self, widget_id, name, value):
        node = self._nodes.get(widget_id)
        if node is not None:
            node.properties[name] = value

    def select_widget(self, _widget_id):
        pass


def test_multi_node_property_command_round_trip():
    from app.core.commands import MultiNodePropertyCommand

    a = _frame({"height": 150})
    b = _frame({"height": 75})
    project = _FakeProject([a, b])
    cmd = MultiNodePropertyCommand([
        (a.id, {"height": (100, 150)}),
        (b.id, {"height": (50, 75)}),
    ])
    cmd.undo(project)
    assert (a.properties["height"], b.properties["height"]) == (100, 50)
    cmd.redo(project)
    assert (a.properties["height"], b.properties["height"]) == (150, 75)


def test_axis_mode_replaces_stretch_for_locked_rows():
    """A container left at `stretch: fill` by an older file used to keep
    its width/height rows read-only — the size could not be typed, so the
    cascade never saw a change. The axis mode now owns that decision."""
    from app.widgets.layout_schema import managed_geometry_disabled

    root = _frame({"layout_type": "vbox", "width": 400, "height": 300})
    a = _frame({"width": 400, "height": 100, "stretch": "fill"})
    _attach(root, a)

    # No axis params yet -> legacy stretch rules still apply.
    assert "width" in managed_geometry_disabled(a)

    _half_of_parent(a)                       # main axis -> percent
    assert "height" in managed_geometry_disabled(a)      # derived
    assert "width" not in managed_geometry_disabled(a)   # cross axis fixed

    param_set(a, ui_name(CROSS_AXIS), C_PERCENT)
    assert "width" in managed_geometry_disabled(a)       # now derived too


def test_fixed_axes_keep_both_size_rows_editable():
    from app.widgets.layout_schema import managed_geometry_disabled

    root = _frame({"layout_type": "vbox", "width": 400, "height": 300})
    a = _frame({"width": 400, "height": 100, "stretch": "grow"})
    _attach(root, a)
    assert "height" in managed_geometry_disabled(a)      # grow + fixed parent

    param_set(a, ui_name(MAIN_AXIS), M_FIXED)
    disabled = managed_geometry_disabled(a)
    assert disabled == frozenset({"x", "y"})             # both rows editable
