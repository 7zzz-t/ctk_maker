"""First-class 02 layout params — semantics layer (spec §11).

02 lets a layout author drive a child's **size** parametrically instead
of hand-computing pixels into the child's own H/W rows. It is the same
knob as the stock ``stretch``/size rows — just parameterised so the
number is derived for you.

Axes are relative to the parent pack container::

    vbox → main axis = height, cross axis = width
    hbox → main axis = width,  cross axis = height

Main-axis modes::

    fixed    use the child's own H/W row (no derivation, no extra input)
    percent  parent main-axis size × N% → written back to the child's row
    remain   even split of whatever fixed + percent leave over

Cross-axis modes::

    fixed    use the child's own W/H row
    percent  parent cross-axis size × N%; 100% == fill the parent

Key invariant — **the result is just a number**. A derived px lands in
the child's own ``height`` / ``width`` property, exactly as if it had
been typed by hand. ``stretch`` is never written by this layer: it stays
the user's own choice (default ``fixed``), so stock 00 opens the same
document and behaves identically.

This module is the single semantic source: row definitions, typed
get/set on ``node.extra``, the axis resolver and the container-level
distribution shared by the canvas, the disk writer and the exporter.
"""
from __future__ import annotations

from app.core.widget_node import WidgetNode  # noqa: F401  (type reference)

# --- UI row prefix (never a real ``properties`` key) -----------------
UI_PREFIX = "x."

# --- axis ids --------------------------------------------------------
MAIN = "main"
CROSS = "cross"

# --- main axis -------------------------------------------------------
MAIN_AXIS = "main_axis"
M_FIXED = "fixed"        # own H/W row, no derivation
M_PERCENT = "percent"    # share of the parent's fixed main-axis size
M_REMAIN = "remain"      # even split of the leftover
M_CONTENT = M_FIXED      # legacy alias: older files stored "content"
MAIN_PERCENT = "percent"

# --- cross axis ------------------------------------------------------
CROSS_AXIS = "cross_axis"
C_FIXED = "fixed"        # own W/H row
C_PERCENT = "percent"    # share of the parent's fixed cross-axis size
CROSS_PERCENT = "percent"

AXIS_KEY = {MAIN: MAIN_AXIS, CROSS: CROSS_AXIS}
_MAIN_MODES = (M_FIXED, M_PERCENT, M_REMAIN)
_CROSS_MODES = (C_FIXED, C_PERCENT)


def _clamp_pct(value, default: int = 50) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(100, n))


def ui_name(extra_name: str) -> str:
    """Panel-row property name for an extra param — namespaced so it
    never collides with a real ``properties`` key."""
    return f"{UI_PREFIX}{extra_name}"


def extra_key(ui_name_value: str) -> str | None:
    if ui_name_value.startswith(UI_PREFIX):
        return ui_name_value[len(UI_PREFIX):]
    return None


def axis_of_key(key: str) -> str | None:
    """Which axis a UI row key belongs to (``"main"`` / ``"cross"``),
    or None when it isn't an axis row."""
    for axis, axis_key in AXIS_KEY.items():
        if key == axis_key or key.startswith(f"{axis_key}."):
            return axis
    return None


# internal alias (call sites inside this module)
_axis_of_key = axis_of_key


def param_get(node, ui_name_value: str, default=None):
    """Read a typed extra param by its UI row name."""
    key = extra_key(ui_name_value)
    if key is None or node is None:
        return default
    axis = _axis_of_key(key)
    if axis is None:
        return (node.extra or {}).get(key, default)
    bucket = (node.extra or {}).get(AXIS_KEY[axis])
    if not isinstance(bucket, dict):
        return default
    sub = "mode" if key == AXIS_KEY[axis] else key.split(".", 1)[1]
    return bucket.get(sub, default)


def param_set(node, ui_name_value: str, value) -> bool:
    """Write a typed extra param; returns True when the value changed."""
    key = extra_key(ui_name_value)
    if key is None or node is None:
        return False
    extra = dict(node.extra or {})
    axis = _axis_of_key(key)
    if axis is not None:
        axis_key = AXIS_KEY[axis]
        bucket = dict(extra.get(axis_key) or {})
        sub = "mode" if key == axis_key else key.split(".", 1)[1]
        if bucket.get(sub) == value:
            return False
        bucket[sub] = value
        extra[axis_key] = bucket
    else:
        if extra.get(key) == value:
            return False
        extra[key] = value
    node.extra = extra
    return True


def extra_rows_for(node) -> list[dict]:
    """Row defs (schema-row shape) for the enhancement params that
    apply to ``node``. 02-only — stock 00 never renders these. Both
    axes are offered for vbox/hbox children; place/grid add nothing."""
    rows: list[dict] = []
    if node is None or node.parent is None:
        return rows
    if node.parent.properties.get("layout_type") not in ("vbox", "hbox"):
        return rows
    rows.append({
        "name": ui_name(MAIN_AXIS),
        "type": "enum",
        "label": "",
        "group": "Layout",
        "row_label": "Main Axis",
        "extra_options": _MAIN_MODES,
    })
    rows.append({
        "name": ui_name(f"{MAIN_AXIS}.{MAIN_PERCENT}"),
        "type": "number",
        "label": "%",
        "group": "Layout",
        "row_label": "Percent",
        "min": 1,
        "max": 100,
        "extra_visible_when": {MAIN_AXIS: M_PERCENT},
    })
    rows.append({
        "name": ui_name(CROSS_AXIS),
        "type": "enum",
        "label": "",
        "group": "Layout",
        "row_label": "Cross Axis",
        "extra_options": _CROSS_MODES,
    })
    rows.append({
        "name": ui_name(f"{CROSS_AXIS}.{CROSS_PERCENT}"),
        "type": "number",
        "label": "%",
        "group": "Layout",
        "row_label": "Percent",
        "min": 1,
        "max": 100,
        "extra_visible_when": {CROSS_AXIS: C_PERCENT},
    })
    return rows


# ---------------------------------------------------------------------
# axis modes / values
# ---------------------------------------------------------------------
def axis_mode(node, axis: str, default: str | None = None) -> str:
    """Distribution mode of a vbox/hbox child on ``axis``."""
    fallback = default if default is not None else (
        M_FIXED if axis == MAIN else C_FIXED)
    if node is None:
        return fallback
    bucket = (node.extra or {}).get(AXIS_KEY.get(axis, ""))
    mode = bucket.get("mode") if isinstance(bucket, dict) else None
    if axis == MAIN:
        if mode == "content":       # legacy spelling → fixed
            return M_FIXED
        return mode if mode in _MAIN_MODES else fallback
    return mode if mode in _CROSS_MODES else fallback


def axis_percent(node, axis: str, default: int = 50) -> int:
    """Percent value for a ``percent`` child (1–100)."""
    if node is None:
        return default
    bucket = (node.extra or {}).get(AXIS_KEY.get(axis, ""))
    if not isinstance(bucket, dict):
        return default
    return _clamp_pct(bucket.get("percent", default), default)


# ---------------------------------------------------------------------
# parent / axis geometry
# ---------------------------------------------------------------------
def parent_axis_key(parent_layout, axis: str) -> str | None:
    """Property key on a child carrying ``axis``' size for the given
    parent layout: vbox → (main height, cross width), hbox → (main
    width, cross height). None when the parent isn't a pack container."""
    if parent_layout == "vbox":
        return "height" if axis == MAIN else "width"
    if parent_layout == "hbox":
        return "width" if axis == MAIN else "height"
    return None


def parent_layout_of(node) -> str | None:
    if node is None or node.parent is None:
        return None
    return node.parent.properties.get("layout_type")


def parent_axis_px(node, axis: str) -> int | None:
    """The parent's FIXED size on ``axis`` in doc units, or None when
    the axis is free (content-sized) — percent/remain then degrade to
    ``fixed`` (the child's own row). Free cases: scrollable-frame
    content (the parent IS a CTkScrollableFrame) and any non-positive
    size."""
    if node is None or node.parent is None:
        return None
    parent = node.parent
    if getattr(parent, "widget_type", "") == "CTkScrollableFrame":
        return None
    key = parent_axis_key(parent.properties.get("layout_type"), axis)
    if key is None:
        return None
    try:
        size = int(parent.properties.get(key, 0) or 0)
    except (TypeError, ValueError):
        return None
    return size if size > 0 else None


# ---------------------------------------------------------------------
# container distribution (single source for canvas / disk / export)
# ---------------------------------------------------------------------
def container_axis_plan(container, axis: str) -> dict:
    """Derived px for every percent/remain child of ``container`` on
    ``axis``. Fixed children are absent — their own row already holds
    the value. Empty when the axis has no fixed baseline (degrade to
    the child's own row)."""
    plan: dict = {}
    if container is None:
        return plan
    if getattr(container, "widget_type", "") == "CTkScrollableFrame":
        return plan
    layout = container.properties.get("layout_type")
    key = parent_axis_key(layout, axis)
    if key is None:
        return plan
    try:
        base = int(container.properties.get(key, 0) or 0)
    except (TypeError, ValueError):
        return plan
    if base <= 0:
        return plan
    children = [c for c in (getattr(container, "children", None) or [])
                if c is not None]
    if not children:
        return plan
    try:
        spacing = int(container.properties.get("layout_spacing", 0) or 0)
    except (TypeError, ValueError):
        spacing = 0

    fixed_total = 0
    remain: list = []
    for child in children:
        mode = axis_mode(child, axis)
        if mode == M_PERCENT:
            px = max(1, round(base * axis_percent(child, axis) / 100))
            plan[child.id] = px
            fixed_total += px
        elif axis == MAIN and mode == M_REMAIN:
            remain.append(child)
        else:
            try:
                fixed_total += max(0, int(child.properties.get(key, 0) or 0))
            except (TypeError, ValueError):
                pass

    if remain:
        avail = max(
            0, base - fixed_total - spacing * max(0, len(children) - 1),
        )
        slot = max(1, avail // len(remain))
        for child in remain:
            plan[child.id] = slot
    return plan


def derived_axis_px(node, axis: str) -> int | None:
    """Derived px for ``node`` on ``axis`` (percent/remain only), or
    None when the child isn't derived / the parent axis is free."""
    if node is None or node.parent is None:
        return None
    return container_axis_plan(node.parent, axis).get(node.id)


def resolved_axis_px(node, axis: str) -> int | None:
    """Final px this child occupies on ``axis``: derived when
    percent/remain, otherwise its own row value."""
    derived = derived_axis_px(node, axis)
    if derived is not None:
        return derived
    if node is None or node.parent is None:
        return None
    key = parent_axis_key(node.parent.properties.get("layout_type"), axis)
    if key is None:
        return None
    try:
        return max(0, int(node.properties.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def sync_sizes(node) -> dict:
    """Bake the derived main/cross px into the child's own ``height`` /
    ``width`` rows so the saved file carries a plain number — the same
    value a user would have typed. Returns ``{prop: (before, after)}``
    for the changes actually applied (empty when nothing moved).
    ``stretch`` is deliberately left untouched."""
    changes: dict = {}
    if node is None or node.parent is None:
        return changes
    layout = node.parent.properties.get("layout_type")
    for axis in (MAIN, CROSS):
        px = derived_axis_px(node, axis)
        if px is None:
            continue
        key = parent_axis_key(layout, axis)
        if key is None:
            continue
        before = node.properties.get(key)
        if before != px:
            node.properties[key] = px
            changes[key] = (before, px)
    return changes


# ---------------------------------------------------------------------
def sync_sizes_cascade(node, out: dict | None = None) -> dict:
    """Bake derived sizes for ``node`` and every descendant, top-down.

    The derived px of a child is computed from its parent's *current*
    size, so a change high in the tree has to ripple down: refresh this
    node's own rows first, then let each child re-derive from the updated
    numbers, and so on. Returns ``{widget_id: {prop: (before, after)}}``
    (grouped per node — the same prop name recurs across siblings, so a
    flat dict would lose entries).

    Idempotent (rows already holding the right value are left alone) and
    it never writes ``stretch``.
    """
    result = {} if out is None else out
    if node is None:
        return result
    changes = sync_sizes(node)
    if changes:
        result[node.id] = changes
    for child in (getattr(node, "children", None) or []):
        sync_sizes_cascade(child, result)
    return result



# compatibility wrappers (older call sites / tests)
# ---------------------------------------------------------------------
def main_axis_mode(node, default: str = M_FIXED) -> str:
    return axis_mode(node, MAIN, default)


def main_axis_percent(node, default: int = 50) -> int:
    return axis_percent(node, MAIN, default)


def parent_main_axis(node) -> str | None:
    """Main axis of the child's parent layout: vbox → height, hbox →
    width. None when the parent isn't a pack container."""
    return parent_axis_key(parent_layout_of(node), MAIN)


def parent_main_px(node) -> int | None:
    return parent_axis_px(node, MAIN)


def percent_px(node, parent_px_value: int | None) -> int | None:
    """Computed main-axis px for a ``percent`` child, or None when the
    child isn't percent / the parent has no fixed axis."""
    if (parent_px_value is None or parent_px_value <= 0
            or axis_mode(node, MAIN) != M_PERCENT):
        return None
    return max(1, round(parent_px_value * axis_percent(node, MAIN) / 100))


def sync_stock_snapshot(node) -> dict:
    """Deprecated alias for :func:`sync_sizes` (kept for older call
    sites). No longer writes ``stretch`` — derived px go straight into
    the child's own size rows."""
    return sync_sizes(node)
