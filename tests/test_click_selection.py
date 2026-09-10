"""Canvas click-selection preference (Settings → Selection).

Stock behaviour picks the outermost unlocked ancestor on a fresh click
(Unity-style drill-down); the "direct pick" preference lands on the
widget under the cursor instead.
"""
from __future__ import annotations

from app.core.settings import (
    SELECTION_DIRECT_PICK_KEY,
    load_selection_direct_pick,
)
from app.ui.workspace.drag_select import (
    fresh_click_target,
    selected_in_chain,
)


class _N:
    def __init__(self, nid):
        self.id = nid


def test_stock_picks_outermost_ancestor():
    chain = [_N("outer"), _N("mid"), _N("leaf")]
    assert fresh_click_target(chain, False).id == "outer"


def test_direct_pick_picks_the_clicked_widget():
    chain = [_N("outer"), _N("mid"), _N("leaf")]
    assert fresh_click_target(chain, True).id == "leaf"


def test_single_element_chain_matches_in_both_modes():
    chain = [_N("only")]
    assert fresh_click_target(chain, False).id == "only"
    assert fresh_click_target(chain, True).id == "only"


def test_empty_chain_is_safe():
    assert fresh_click_target([], False) is None
    assert fresh_click_target([], True) is None


def test_preference_key_name_is_stable():
    assert SELECTION_DIRECT_PICK_KEY == "selection_direct_pick"


def test_preference_defaults_to_off_without_settings_file(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        "app.core.settings.SETTINGS_PATH", tmp_path / "settings.json",
    )
    assert load_selection_direct_pick() is False


def test_preference_reads_stored_value(monkeypatch, tmp_path):
    import json
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({SELECTION_DIRECT_PICK_KEY: True}), encoding="utf-8",
    )
    monkeypatch.setattr("app.core.settings.SETTINGS_PATH", path)
    assert load_selection_direct_pick() is True


def test_selected_in_chain_detects_press_inside_selection():
    """Keep-the-selection rule: a press on the selected widget itself or
    on any of its ancestors counts as "inside the selection"."""
    chain = [_N("outer"), _N("mid"), _N("leaf")]
    assert selected_in_chain(chain, "leaf") is True    # clicked widget
    assert selected_in_chain(chain, "mid") is True     # ancestor
    assert selected_in_chain(chain, "outer") is True   # outermost
    assert selected_in_chain(chain, "elsewhere") is False
    assert selected_in_chain(chain, None) is False
    assert selected_in_chain([], "leaf") is False


def test_container_extract_is_skipped_for_kept_selection():
    """A press inside the current selection must not run the container
    extract-only shortcut — that hops the widget to the document root
    and reads as it disappearing after the drop."""
    from app.ui.workspace.drag_release import uses_container_extract
    assert uses_container_extract(True, False) is True     # stock
    assert uses_container_extract(True, True) is False     # keep-selection
    assert uses_container_extract(False, False) is False
    assert uses_container_extract(False, True) is False
