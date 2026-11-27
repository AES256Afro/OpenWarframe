"""Milestone 9: the app page and its data after the UI audit. No network, no browser."""

from __future__ import annotations

import re
from pathlib import Path

from openwarframe.app.data import build_app_data
from openwarframe.app.server import page_source
from openwarframe.codex import Codex
from openwarframe.codex.howto import SPECIAL_LABELS
from openwarframe.inventory import parse_inventory
from test_app import INVENTORY
from test_codex_build import RELIC, codex_path  # noqa: F401
from test_guide import _report

PAGE = page_source()
SCRIPT = re.search(r"<script>(.*?)</script>", PAGE, re.S).group(1)


# -- data.py ---------------------------------------------------------------------------------


def test_relics_to_crack_carry_their_drops_and_trade_name(codex_path: Path):  # noqa: F811
    d = build_app_data(_report(), Codex(codex_path), parse_inventory(INVENTORY))
    crack = next(r for r in d["farm"]["crack"] if r["id"] == RELIC)
    relic = next(r for r in d["relics"] if r["id"] == RELIC)
    assert crack["drops"] == relic["drops"] and crack["drops"]
    assert "slug" in crack and crack["slug"] == relic["slug"]


def test_item_rows_use_one_convention_for_blank_and_unknown(codex_path: Path):  # noqa: F811
    d = build_app_data(_report(), Codex(codex_path), None)
    owned = [i for i in d["items"] if i["access"] == "Leveled before"]
    missing = [i for i in d["items"] if i["mastery"] == "Never leveled"]
    assert owned and missing
    # owned: no "How to get" text (a dash) unless a Lich/Dojo rule names it, MR from the game data or None, never 0
    assert all(i["how"] is None or i["how"] in {label for _, label in SPECIAL_LABELS} for i in owned)
    assert all(i["mr"] is None or i["mr"] > 0 for i in owned)
    # never leveled: no rank 0 in the Rank column, MR 0 is blank
    assert all(i["rank"] is None for i in missing)
    assert all(i["mr"] is None or i["mr"] > 0 for i in missing)


def test_blueprints_and_foundry_rows_say_how_many_one_build_makes(codex_path: Path):  # noqa: F811
    d = build_app_data(_report(), Codex(codex_path), parse_inventory(INVENTORY))
    assert d["blueprints"] and all(b["batch"] >= 1 for b in d["blueprints"])
    assert all(f["batch"] >= 1 for f in d["foundry"])


# -- index.html ------------------------------------------------------------------------------


def test_views_are_history_steps_and_back_works():
    assert 'history[push?"pushState":"replaceState"]' in SCRIPT
    assert 'window.addEventListener("popstate", fromHash)' in SCRIPT
    assert "function openView" in SCRIPT and 'setHash(VIEW+"/"+keep, true)' in SCRIPT  # sub-tabs too


def test_keyboard_shortcuts():
    assert 'e.key==="/"' in SCRIPT and '$("q").focus()' in SCRIPT
    assert 'e.key==="?"' in SCRIPT and '$("keys").showModal()' in SCRIPT
    assert '<dialog id="keys" class="dialog" aria-labelledby="keys-title">' in PAGE
    assert "typing(e.target)" in SCRIPT  # never while typing in a field


def test_sell_list_has_a_best_column_and_market_links():
    assert '{k:"best",l:"Best"' in SCRIPT and "d/p>=10" in SCRIPT
    assert "https://warframe.market/items/'+encodeURIComponent(slug)" in SCRIPT
    assert 'target="_blank" rel="noopener"' in SCRIPT  # pywebview sends these to the system browser


def test_long_lists_say_they_are_cut_and_use_one_handler():
    assert "Showing first '+ROW_CAP.toLocaleString()+' of '" in SCRIPT and "var ROW_CAP=1500" in SCRIPT
    assert '$("view").addEventListener("click", onTableClick)' in SCRIPT
    assert "tr.onclick" not in SCRIPT and "tr.onkeydown" not in SCRIPT


def test_setup_screen_hides_controls_that_need_an_account():
    assert (
        'var SETUP_HIDE=["q","csv","refresh","grab","loadinv","export","updatedata","filters","fbar"]'
        in SCRIPT
    )
    body = SCRIPT.split("function renderSetup(d){", 1)[1]
    assert body.lstrip().startswith("setupMode(true);")
    assert "setupMode(false);" in SCRIPT.split("function load(data){", 1)[1].split("function ", 1)[0]


def test_smaller_fixes_are_in_place():
    assert 'spec.key==="relics"||spec.key==="crack"' in SCRIPT  # crack rows list drops
    assert "/api/names?ids=" in SCRIPT and "function splitCamel" in SCRIPT  # finished goal names
    assert "Side with " in SCRIPT and "attacker_faction" in SCRIPT  # invasions
    assert '["Score (What to farm)"' in SCRIPT
    assert 'noun={relics:"relics", sell:"items", mods:"mods"}' in SCRIPT
    assert "data-gup" in SCRIPT and "data-gdone" in SCRIPT and "goals_done" in SCRIPT  # goals
    assert "th.num button{text-align:right}" in PAGE and "white-space:nowrap}" in PAGE
    assert "showMe(s)" in SCRIPT and '{sub:"finish", id:s.item}' in SCRIPT
    assert 'button type="button" class="card" data-go=' in SCRIPT  # overview cards open views
    assert "priced as intact" in SCRIPT and "up to " in SCRIPT  # earnings are estimates
    assert "body.compact" in PAGE and "PREFS.settings.compact" in SCRIPT
