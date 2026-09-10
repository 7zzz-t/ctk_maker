"""Stock-00 compatibility normalization (spec §9.4).

Stock 00's canvas places a *composite* child — one whose
``canvas_anchor`` is not the widget itself, currently only
``CTkScrollableFrame`` — with ``place(x=…, y=…, width=…, height=…)``.
ctkmaker-core's ``CTk.place`` rejects ``width``/``height``, so **stock 00
crashes on load** for any document that holds a composite child under a
``place`` (or unset) parent.

02 renders that structure fine (``ac2177e``), and stock 00's *exporter*
is unaffected (its place branch only emits ``x``/``y``). But we no longer
want 02 to *produce* documents stock 00 cannot open, so right before a
project is serialised every offending parent is rewritten to a managed
layout (``vbox``) — the saved ``.ctkproj`` then opens in stock 00.

The rewrite is silent and idempotent: a parent already on a managed
layout (``vbox`` / ``hbox`` / ``grid``), or without a composite child, is
left untouched.
"""
from __future__ import annotations

from app.widgets.layout_schema import (
    MANAGED_LAYOUT_TYPES,
    normalise_layout_type,
)

# Widget types whose canvas anchor is not the widget itself. Stock 00
# passes ``(width, height)`` to ``place()`` for exactly these — derived
# from the descriptors that override ``canvas_anchor`` (see
# ``app/widgets/ctk_scrollable_frame.py``).
COMPOSITE_WIDGET_TYPES = frozenset({"CTkScrollableFrame"})

# Layout a place-like parent is rewritten to when it holds a composite
# child. ``vbox`` is the managed analogue that keeps every child packed
# and visible.
SAFE_FALLBACK_LAYOUT = "vbox"


def _is_place_like(layout) -> bool:
    """True for ``place`` / unset / unknown layouts — anything stock 00
    would route to the crashing place branch."""
    return normalise_layout_type(layout) not in MANAGED_LAYOUT_TYPES


def _is_composite(node) -> bool:
    return getattr(node, "widget_type", "") in COMPOSITE_WIDGET_TYPES


def _has_composite_child(container) -> bool:
    return any(
        _is_composite(child)
        for child in (getattr(container, "children", None) or [])
    )


def normalize_project_for_stock(project) -> list[tuple[str, str, str]]:
    """Rewrite every place-like parent holding a composite child to
    :data:`SAFE_FALLBACK_LAYOUT`.

    Returns ``[(owner, before, after), …]`` for the rewrites applied —
    empty when the project is already stock-compatible.
    """
    fixes: list[tuple[str, str, str]] = []
    if project is None:
        return fixes
    for doc in getattr(project, "documents", None) or []:
        fixes.extend(normalize_document_for_stock(doc))
    return fixes


def normalize_document_for_stock(doc) -> list[tuple[str, str, str]]:
    """Same as :func:`normalize_project_for_stock` for a single document
    (window-level layout included)."""
    fixes: list[tuple[str, str, str]] = []
    if doc is None:
        return fixes
    roots = list(getattr(doc, "root_widgets", None) or [])
    window_props = getattr(doc, "window_properties", None)
    if (
        isinstance(window_props, dict)
        and roots
        and _is_place_like(window_props.get("layout_type"))
        and any(_is_composite(r) for r in roots)
    ):
        before = window_props.get("layout_type", "place")
        window_props["layout_type"] = SAFE_FALLBACK_LAYOUT
        fixes.append((
            f"window:{getattr(doc, 'name', '')}",
            str(before), SAFE_FALLBACK_LAYOUT,
        ))
    stack = list(roots)
    while stack:
        node = stack.pop()
        props = getattr(node, "properties", None)
        if (
            isinstance(props, dict)
            and _has_composite_child(node)
            and _is_place_like(props.get("layout_type"))
        ):
            before = props.get("layout_type", "place")
            props["layout_type"] = SAFE_FALLBACK_LAYOUT
            fixes.append((
                str(getattr(node, "id", "")
                    or getattr(node, "widget_type", "node")),
                str(before), SAFE_FALLBACK_LAYOUT,
            ))
        stack.extend(getattr(node, "children", None) or [])
    return fixes
