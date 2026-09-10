"""Persistent user settings (theme, future preferences).

Stored at `~/.ctk_visual_builder/settings.json`. Loader is tolerant —
a missing or corrupt file is treated as an empty dict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path.home() / ".ctk_visual_builder" / "settings.json"


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_setting(key: str, value: Any) -> None:
    data = load_settings()
    data[key] = value
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def load_description_hints() -> list[str]:
    raw = load_settings().get("description_hints", [])
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str) and x.strip()]


def save_description_hints(hints: list[str]) -> None:
    cleaned = [h for h in hints if isinstance(h, str) and h.strip()]
    save_setting("description_hints", cleaned)


# --- Canvas interaction preferences ----------------------------------
SELECTION_DIRECT_PICK_KEY = "selection_direct_pick"


def load_selection_direct_pick() -> bool:
    """True when a canvas click should select the widget *under the
    cursor* instead of the outermost unlocked ancestor.

    Default ``False`` keeps the stock Unity-style drill-down: the first
    click selects the outermost container and a fast follow-up click
    (within the drill window) descends one level. ``True`` makes a plain
    click land on the innermost clicked widget.
    """
    return bool(load_settings().get(SELECTION_DIRECT_PICK_KEY, False))


DRAG_NO_REPARENT_KEY = "drag_no_reparent"


def load_drag_no_reparent() -> bool:
    """True when the drag patch is on: dragging a widget only changes its
    x/y and never reparents it, so the object tree keeps its structure.
    Default False = stock behaviour, where dropping inside another
    container moves the widget into that container."""
    return bool(load_settings().get(DRAG_NO_REPARENT_KEY, False))


STOCK_COMPAT_ENABLED_KEY = "stock_compat_enabled"


def load_stock_compat_enabled() -> bool:
    """True (default) when saving may rewrite a place parent that holds a
    composite child to a managed layout, so stock 00 can open the file."""
    return bool(load_settings().get(STOCK_COMPAT_ENABLED_KEY, True))
