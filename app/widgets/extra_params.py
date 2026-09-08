"""First-class 02 enhancement params — semantics layer (spec §11).

02 lets layout authors express things stock CTkMaker can't: auto-height
containers, percent / remainder main-axis distribution, … These are
first-class parameters (``WidgetNode.extra``), NOT re-encoded onto
stock fields like ``height=0``. UI row names carry the ``x.`` prefix so
they can never collide with real ``properties`` keys (stock 00 forwards
every property key to the CTk constructor — unknown ones crash).

This module is the single semantic source: row definitions, per-node
applicability, typed get/set on ``node.extra``, and the stock-field
snapshot sync used at save / export time.
"""
from __future__ import annotations

from app.core.widget_node import WidgetNode

# --- UI property-name prefix (never a real properties key) -----------
UI_PREFIX = "x."

# --- height_mode (CTkFrame containers) --------------------------------
H_AUTO = "auto"
H_FIXED = "fixed"
HEIGHT_MODE = "height_mode"

# --- main_axis (vbox / hbox children) ---------------------------------
M_CONTENT = "content"   # natural size (stock "fixed" semantics)
M_PERCENT = "percent"   # share of the parent's fixed main-axis size
M_REMAIN = "remain"     # take the leftover, evenly split when several
MAIN_AXIS = "main_axis"
MAIN_PERCENT = "percent"

# Height given to an auto container when the disk form needs a visible
# stock height (00 renders 0-height frames as invisible).
AUTO_HEIGHT_SNAPSHOT = 200


def ui_name(extra_key: str) -> str:
    """Panel-row property name for an extra param — namespaced so it
    never collides with a real ``properties`` key."""
    return f"{UI_PREFIX}{extra_key}"


def extra_key(ui_name: str) -> str | None:
    if ui_name.startswith(UI_PREFIX):
        return ui_name[len(UI_PREFIX):]
    return None


def extra_rows_for(node) -> list[dict]:
    """Row defs (schema-row shape) for the enhancement params that
    apply to ``node``. 02-only — stock 00 never renders these."""
    rows: list[dict] = []
    if node is None:
        return rows
    if node.widget_type == "CTkFrame":
        rows.append({
            "name": ui_name(HEIGHT_MODE),
            "type": "enum",
            "label": "",
            "group": "Layout",
            "row_label": "Height Mode",
            "extra_options": (H_FIXED, H_AUTO),
        })
    parent = node.parent
    parent_layout = None
    if parent is not None:
        lt = parent.properties.get("layout_type")
        parent_layout = lt if lt in ("vbox", "hbox") else None
    if parent_layout is not None:
        rows.append({
            "name": ui_name(MAIN_AXIS),
            "type": "enum",
            "label": "",
            "group": "Layout",
            "row_label": "Main Axis",
            "extra_options": (M_CONTENT, M_PERCENT, M_REMAIN),
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
    return rows


def param_get(node, ui_name: str, default=None):
    """Read a typed extra param by its UI row name."""
    key = extra_key(ui_name)
    if key is None or node is None:
        return default
    extra = node.extra or {}
    if key == MAIN_AXIS or key.startswith(f"{MAIN_AXIS}."):
        bucket = extra.get(MAIN_AXIS)
        if not isinstance(bucket, dict):
            return default
        sub = "mode" if key == MAIN_AXIS else key.split(".", 1)[1]
        return bucket.get(sub, default)
    return extra.get(key, default)


def param_set(node, ui_name: str, value) -> bool:
    """Write a typed extra param; returns True when the value changed."""
    key = extra_key(ui_name)
    if key is None or node is None:
        return False
    extra = dict(node.extra or {})
    if key == MAIN_AXIS or key.startswith(f"{MAIN_AXIS}."):
        bucket = dict(extra.get(MAIN_AXIS) or {})
        sub = "mode" if key == MAIN_AXIS else key.split(".", 1)[1]
        if bucket.get(sub) == value:
            return False
        bucket[sub] = value
        extra[MAIN_AXIS] = bucket
    else:
        if extra.get(key) == value:
            return False
        extra[key] = value
    node.extra = extra
    return True


def is_auto_height(node) -> bool:
    """True when the container is in auto-height mode — either via the
    first-class ``height_mode`` param or legacy ``height == 0`` /
    top-level ``_ctkmaker_auto_height`` disk markers from earlier 02."""
    if node is None:
        return False
    extra = node.extra or {}
    mode = extra.get(HEIGHT_MODE)
    if mode is not None:
        return mode == H_AUTO
    if node.widget_type != "CTkFrame":
        return False
    # Legacy forms (pre-height_mode). Top-level marker may still sit on
    # a node loaded from an old file; height==0 is the pre-mapping form.
    try:
        return bool(
            int(node.properties.get("height", 0) or 0) == 0
            or getattr(node, "_ctkmaker_auto_height", False)
        )
    except (TypeError, ValueError):
        return False
