"""Pure formatting and coercion helpers for the Properties panel v2.

These functions depend only on the schema dict and current property
values — no references to `self`, the Treeview, or any Tk state.
Kept in a separate module so the panel module stays focused on
Tkinter glue and per-row overlay management.
"""

from __future__ import annotations

import re

from app.core.i18n import tr
from app.widgets.layout_schema import (
    GRID_STICKY_OPTIONS,
    LAYOUT_DISPLAY_NAMES,
    LAYOUT_TYPE_OPTIONS,
    STRETCH_OPTIONS,
)

from .constants import (
    COMPOUND_OPTIONS,
    CURSOR_OPTIONS,
    JUSTIFY_OPTIONS,
    ORIENTATION_OPTIONS,
    TAB_BAR_ALIGN_OPTIONS,
    TAB_BAR_POSITION_OPTIONS,
    TEXT_POSITION_OPTIONS,
    UNIT_SUFFIX_OPTIONS,
    WRAP_OPTIONS,
    anchor_dropdown_order,
    anchor_label,
)

GRID_STYLE_OPTIONS = ("none", "dots", "lines")
LAYOUT_ENUM_TYPES = frozenset({
    "layout_type", "stretch", "grid_sticky",
})

_LABEL_SLUG_RE = re.compile(r"[^a-z0-9]+")


def prop_row_label(text: str) -> str:
    """Localized display label for a property row.

    ``text`` is the raw ``label`` / ``row_label`` / property-name
    fallback from the schema entry. The pack key is derived from the
    English label so entries like ``"Corner Radius"`` map to
    ``props.label.corner_radius``; unknown labels pass through
    unchanged.
    """
    if not text:
        return text
    slug = _LABEL_SLUG_RE.sub("_", text.lower()).strip("_")
    return tr(f"props.label.{slug}", text)


def prop_group_label(text: str) -> str:
    """Localized title for a schema group header (e.g. ``"Main
    Colors"`` → ``props.group.main_colors``). Unknown groups pass
    through unchanged.
    """
    if not text:
        return text
    slug = _LABEL_SLUG_RE.sub("_", text.lower()).strip("_")
    return tr(f"props.group.{slug}", text)


def prop_subgroup_label(text: str) -> str:
    """Localized title for a schema subgroup header (e.g.
    ``"Border"`` → ``props.subgroup.border``). Unknown subgroups pass
    through unchanged.
    """
    if not text:
        return text
    slug = _LABEL_SLUG_RE.sub("_", text.lower()).strip("_")
    return tr(f"props.subgroup.{slug}", text)


def format_value(ptype: str, value, prop: dict) -> str:
    """Render a schema value as the string shown in the tree cell."""
    if ptype == "color":
        # Leading spaces reserve room for the swatch overlay.
        # None and "transparent" both surface as "none" so a cleared
        # clearable field reads clearly instead of staying blank.
        if value is None or str(value) == "transparent":
            # Leading spaces reserve room for the swatch overlay;
            # "none" is the only user-visible word (cleared colour).
            return "              " + tr("props.format.color_none", "none")
        if not value:
            return ""
        return f"              {str(value)}"
    if ptype == "boolean":
        return "☑" if value else "☐"
    if ptype == "anchor":
        return anchor_label(str(value)) if value else ""
    if ptype in (
        "compound", "justify", "orientation", "grid_style",
        "tab_bar_align", "tab_bar_position", "cursor",
    ):
        # Empty cursor string maps to "(default)" so the cell isn't
        # blank when the user picks "inherit" — keeps the row legible.
        if ptype == "cursor" and value == "":
            return tr("props.value_default", "(default)")
        return str(value) if value is not None else ""
    if ptype == "layout_type":
        # layout_type stores the internal key (``place`` / ``vbox`` /
        # …); show the friendly Qt-style label in the tree cell.
        return LAYOUT_DISPLAY_NAMES.get(str(value), str(value or "—"))
    if ptype in LAYOUT_ENUM_TYPES:
        return str(value) if value not in (None, "") else "—"
    if ptype == "unit":
        return str(value) if value is not None else ""
    if ptype in ("multiline", "image", "segment_values"):
        # Shown via overlay label / button, not the tree cell.
        return ""
    if ptype == "segment_initial":
        # Render the picked segment text in the cell; the dropdown
        # popup is the actual editor.
        return str(value) if value not in (None, "") else "—"
    if value is None:
        return ""
    return str(value)


def format_numeric_pair_preview(items: list[dict], properties: dict) -> str:
    parts = []
    for item in items:
        label = prop_row_label(item.get("label") or item["name"].upper()[:1])
        val = properties.get(item["name"])
        parts.append(f"{label} {val}")
    return "  ".join(parts)


def compute_subgroup_preview(
    descriptor, group: str, subgroup: str, properties: dict,
) -> str:
    """Preview string shown next to a subgroup header row.

    - Rectangle › Corners → the `corner_radius` value.
    - Rectangle › Border → "active" / "not active" based on
      `border_enabled`.
    - Everything else → empty.
    """
    name = subgroup.lower()
    if name == "corners":
        for p in descriptor.property_schema:
            if p.get("group") == group and \
                    p.get("subgroup") == subgroup and \
                    p["name"] == "corner_radius":
                return str(properties.get("corner_radius", ""))
    if name == "border":
        return (
            tr("props.format.active", "active")
            if properties.get("border_enabled")
            else tr("props.format.not_active", "not active")
        )
    return ""


def enum_options_for(ptype: str):
    if ptype == "anchor":
        return anchor_dropdown_order()
    if ptype == "compound":
        return COMPOUND_OPTIONS
    if ptype == "cursor":
        return CURSOR_OPTIONS
    if ptype == "justify":
        return JUSTIFY_OPTIONS
    if ptype == "tab_bar_align":
        return TAB_BAR_ALIGN_OPTIONS
    if ptype == "tab_bar_position":
        return TAB_BAR_POSITION_OPTIONS
    if ptype == "orientation":
        return ORIENTATION_OPTIONS
    if ptype == "unit":
        return UNIT_SUFFIX_OPTIONS
    if ptype == "wrap":
        return WRAP_OPTIONS
    if ptype == "text_position":
        return TEXT_POSITION_OPTIONS
    if ptype == "grid_style":
        return GRID_STYLE_OPTIONS
    if ptype == "layout_type":
        return LAYOUT_TYPE_OPTIONS
    if ptype == "stretch":
        return STRETCH_OPTIONS
    if ptype == "grid_sticky":
        return GRID_STICKY_OPTIONS
    return []


def coerce_value(ptype: str | None, raw: str):
    if ptype == "number":
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                return None
    return raw
