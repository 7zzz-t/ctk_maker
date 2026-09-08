"""Grid-shrink auto-repair: plan + atomic multi-widget undo.

Shrinking ``grid_rows`` / ``grid_cols`` below the highest row/column a
child occupies used to block every attempt with an error dialog until
the user manually moved/deleted the widget. The repair instead parks
out-of-bounds children into free cells of the smaller grid and commits
the whole shrink as ONE undo step.

Covers:
  - ``plan_grid_shrink_relocation`` (pure plan, no mutation)
  - ``MultiWidgetPropertyCommand`` (undo/redo replay across widgets)
"""
from __future__ import annotations

from app.core.commands import MultiWidgetPropertyCommand
from app.core.widget_node import WidgetNode
from app.widgets.layout_schema import plan_grid_shrink_relocation


def _make_grid(rows: int, cols: int, *cells: tuple[int, int]):
    """Build a grid container with one CTkLabel child per ``(r, c)``."""
    parent = WidgetNode("CTkFrame", {
        "layout_type": "grid",
        "grid_rows": rows,
        "grid_cols": cols,
    })
    for r, c in cells:
        child = WidgetNode("CTkLabel", {
            "grid_row": r,
            "grid_column": c,
        })
        child.parent = parent
        parent.children.append(child)
    return parent


# ---------------------------------------------------------------------
# plan_grid_shrink_relocation
# ---------------------------------------------------------------------
def test_no_out_of_bounds_shrink_is_plain():
    parent = _make_grid(4, 4, (0, 0), (0, 1), (1, 0))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 3)
    assert ok is True
    assert relocations == []


def test_out_of_bounds_child_gets_first_free_cell():
    parent = _make_grid(4, 4, (0, 0), (0, 1), (3, 0))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 3)
    assert ok is True
    assert len(relocations) == 1
    child, row, col = relocations[0]
    assert child is parent.children[2]
    # (0,0)+(0,1) stay; row-major first free cell in a 3x4 grid is (0,2).
    assert (row, col) == (0, 2)


def test_in_bounds_children_keep_cells_and_tree_is_not_mutated():
    parent = _make_grid(5, 5, (0, 0), (1, 0), (4, 0), (4, 1))
    before = {
        c.id: (c.properties["grid_row"], c.properties["grid_column"])
        for c in parent.children
    }
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 3)
    assert ok is True
    # Only the two row-4 children need a new home.
    moved_ids = {c.id for c, _r, _col in relocations}
    assert moved_ids == {parent.children[2].id, parent.children[3].id}
    # Plan is pure — nothing on the model changed.
    for c in parent.children:
        r, col = before[c.id]
        assert c.properties["grid_row"] == r
        assert c.properties["grid_column"] == col
    # Relocations never overlap the kept cells (0,0)/(1,0) and are
    # distinct from each other.
    kept = {(0, 0), (1, 0)}
    targets = {(r, col) for _c, r, col in relocations}
    assert targets.isdisjoint(kept)
    assert len(targets) == 2


def test_shrink_columns_is_symmetric():
    parent = _make_grid(3, 3, (0, 0), (0, 2))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_cols", 2)
    assert ok is True
    assert len(relocations) == 1
    child, row, col = relocations[0]
    assert child is parent.children[1]
    assert (row, col) == (0, 1)


def test_multiple_out_of_bounds_fill_row_major_in_z_order():
    parent = _make_grid(5, 4, (0, 0), (1, 0), (4, 3), (4, 2))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 3)
    assert ok is True
    # children[2] (4,3) and children[3] (4,2) — z-order preserved.
    assert [(c is parent.children[2], c is parent.children[3])
            for c, _r, _col in relocations] == [(True, False), (False, True)]
    # First free cells after occupied (0,0)/(1,0): (0,1) then (0,2).
    assert [(r, col) for _c, r, col in relocations] == [(0, 1), (0, 2)]


def test_impossible_shrink_when_no_free_cell():
    parent = _make_grid(3, 1, (0, 0), (1, 0), (2, 0))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 2)
    assert ok is False
    assert relocations is None


def test_missing_cell_props_default_to_zero():
    # Child without grid_row/grid_column sits at (0, 0) → always in bounds.
    parent = WidgetNode("CTkFrame", {
        "layout_type": "grid", "grid_rows": 3, "grid_cols": 3,
    })
    child = WidgetNode("CTkLabel", {})
    child.parent = parent
    parent.children.append(child)
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 1)
    assert ok is True
    assert relocations == []


def test_unknown_axis_is_a_noop_plan():
    parent = _make_grid(3, 3, (2, 2))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_spacing", 1)
    assert ok is True
    assert relocations == []


def test_new_val_clamped_to_at_least_one():
    parent = _make_grid(3, 3, (0, 0), (2, 2))
    ok, relocations = plan_grid_shrink_relocation(parent, "grid_rows", 0)
    # Effective rows = 1; child (0,0) stays, (2,2) moves to (0,1).
    assert ok is True
    assert len(relocations) == 1
    child, row, col = relocations[0]
    assert child is parent.children[1]
    assert (row, col) == (0, 1)


# ---------------------------------------------------------------------
# MultiWidgetPropertyCommand
# ---------------------------------------------------------------------
class _FakeProject:
    def __init__(self):
        self.calls = []
        self.selected = None

    def update_property(self, widget_id, name, value):
        self.calls.append((widget_id, name, value))

    def select_widget(self, widget_id):
        self.selected = widget_id


def _shrink_entries():
    return [
        ("cont", {"grid_rows": (4, 2)}),
        ("k1", {"grid_row": (3, 0), "grid_column": (0, 2)}),
        ("k2", {"grid_row": (3, 1), "grid_column": (0, 3)}),
    ]


def test_redo_applies_after_values_in_order():
    project = _FakeProject()
    cmd = MultiWidgetPropertyCommand(_shrink_entries())
    cmd.redo(project)
    assert project.calls == [
        ("cont", "grid_rows", 2),
        ("k1", "grid_row", 0),
        ("k1", "grid_column", 2),
        ("k2", "grid_row", 1),
        ("k2", "grid_column", 3),
    ]
    assert project.selected == "cont"


def test_undo_restores_before_values_in_order():
    project = _FakeProject()
    cmd = MultiWidgetPropertyCommand(_shrink_entries())
    cmd.undo(project)
    assert project.calls == [
        ("cont", "grid_rows", 4),
        ("k1", "grid_row", 3),
        ("k1", "grid_column", 0),
        ("k2", "grid_row", 3),
        ("k2", "grid_column", 0),
    ]
    assert project.selected == "cont"


def test_undo_redo_round_trip_restores_state():
    project = _FakeProject()
    cmd = MultiWidgetPropertyCommand(_shrink_entries())
    cmd.redo(project)
    cmd.undo(project)
    project.calls.clear()
    cmd.redo(project)
    assert project.calls == [
        ("cont", "grid_rows", 2),
        ("k1", "grid_row", 0),
        ("k1", "grid_column", 2),
        ("k2", "grid_row", 1),
        ("k2", "grid_column", 3),
    ]


def test_description_counts_props_and_widgets():
    cmd = MultiWidgetPropertyCommand(_shrink_entries())
    assert "5 properties" in cmd.description
    assert "3 widgets" in cmd.description
