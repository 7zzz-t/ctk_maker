"""Lightweight internationalization (i18n) for CTkMaker.

Design goals
------------
* **JSON language packs** — one ``<lang>.json`` file per language in
  ``app/assets/locales/``. Flat key/value dictionary. No gettext, no
  ``.po``/``.mo`` compilation step. Matches the project's existing
  JSON-based settings convention.
* **Zero-config fallback** — if a key is missing from the active pack
  (or the pack file is absent), ``tr()`` returns the supplied default
  or the key itself. The app never crashes on a missing translation.
* **Runtime switchable** — language is read from
  ``~/.ctk_visual_builder/settings.json`` under the ``language`` key
  and can be changed via the Preferences dialog. Callbacks registered
  with ``on_language_change`` fire so UIs can rebuild themselves.

Usage
-----
>>> from app.core.i18n import tr, set_language
>>> tr("menu.file", "File")
'File'
>>> set_language("zh")
>>> tr("menu.file", "File")
'文件'
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

# Language pack directory — sibling of the ``icons/`` and ``lucide/``
# asset folders so it ships with the app bundle.
LOCALES_DIR = Path(__file__).resolve().parents[1] / "assets" / "locales"

DEFAULT_LANGUAGE = "en"
SETTINGS_KEY = "language"

# Module-level state. ``_current_lang`` is the two-letter code;
# ``_catalog`` is the loaded dict for that language; ``_fallback`` is
# the English pack used when a key is absent in the active language.
_current_lang: str = DEFAULT_LANGUAGE
_catalog: dict[str, str] = {}
_fallback: dict[str, str] = {}
_callbacks: list[Callable[[str], None]] = []


def _load_pack(lang: str) -> dict[str, str]:
    """Load a single language pack. Returns ``{}`` if the file is
    missing or unreadable so the caller can fall back gracefully."""
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def _resolve_initial_language() -> str:
    """Pick the startup language from settings, defaulting to English.
    Kept in a helper so ``main.py`` can call it before any Tk root
    exists (``load_settings`` is pure JSON, no Tk dependency)."""
    try:
        from app.core.settings import load_settings
        lang = load_settings().get(SETTINGS_KEY)
        if isinstance(lang, str) and lang.strip():
            return lang.strip()
    except Exception:
        pass
    return DEFAULT_LANGUAGE


def init() -> None:
    """Load the fallback (English) pack and the user's chosen pack.
    Safe to call multiple times — later calls just reload."""
    global _fallback, _catalog, _current_lang
    _fallback = _load_pack(DEFAULT_LANGUAGE)
    _current_lang = _resolve_initial_language()
    _catalog = _load_pack(_current_lang)


def get_language() -> str:
    """Return the active two-letter language code."""
    return _current_lang


def set_language(lang: str) -> None:
    """Switch the active language and persist it to settings.

    Fires every registered callback with the new code so windows can
    rebuild their localized strings. If ``lang`` has no pack file the
    catalog stays empty and every lookup falls back to English / the
    key itself — the app keeps running.
    """
    global _catalog, _current_lang
    lang = (lang or DEFAULT_LANGUAGE).strip()
    if not lang:
        lang = DEFAULT_LANGUAGE
    _current_lang = lang
    _catalog = _load_pack(lang)
    try:
        from app.core.settings import save_setting
        save_setting(SETTINGS_KEY, lang)
    except Exception:
        pass
    for cb in list(_callbacks):
        try:
            cb(lang)
        except Exception:
            # A buggy callback must not break the language switch.
            pass


def tr(key: str, default: str | None = None) -> str:
    """Translate ``key`` into the active language.

    Resolution order:
    1. Active language pack.
    2. English fallback pack.
    3. ``default`` if supplied.
    4. The key itself.
    """
    value = _catalog.get(key)
    if value is not None:
        return value
    value = _fallback.get(key)
    if value is not None:
        return value
    if default is not None:
        return default
    return key


def get_available_languages() -> list[tuple[str, str]]:
    """Return ``[(code, display_name), ...]`` for every pack file.

    The display name comes from a special ``_meta.name`` key inside
    each pack; missing meta falls back to the code. Sorted by code.
    """
    if not LOCALES_DIR.exists():
        return [(DEFAULT_LANGUAGE, "English")]
    langs: list[tuple[str, str]] = []
    for path in sorted(LOCALES_DIR.glob("*.json")):
        code = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("_meta", {}).get("name", code) if isinstance(data, dict) else code
        except (OSError, json.JSONDecodeError):
            name = code
        langs.append((code, name))
    if not langs:
        langs.append((DEFAULT_LANGUAGE, "English"))
    return langs


def on_language_change(callback: Callable[[str], None]) -> Callable[[], None]:
    """Register ``callback(lang)`` to run on every language switch.
    Returns an unsubscribe function."""
    _callbacks.append(callback)

    def _unsubscribe() -> None:
        try:
            _callbacks.remove(callback)
        except ValueError:
            pass

    return _unsubscribe


# Eager-load at import time so ``tr()`` works immediately after the
# first ``from app.core import i18n``. The import is cheap — two
# small JSON files.
init()
