"""Regressions found by re-auditing the fixes made since 0.4.0. No network."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwarframe.account import SnapshotStore, parse_profile
from openwarframe.app.server import AppState
from openwarframe.app.window import NativeWindows
from openwarframe.codex import Codex
from openwarframe.config import Settings
from openwarframe.report import build_report
from test_account import _profile
from test_codex_build import codex_path  # noqa: F401


def test_the_page_cannot_switch_server_owned_settings_back_on(tmp_path: Path):
    state = AppState(Settings(home=tmp_path))
    state.save_prefs(json.dumps({"settings": {"save_recordings": False, "reward_watch": False}}).encode())
    # the page still holds its stale copy from startup and saves it with an unrelated change
    stale = {"settings": {"save_recordings": True, "reward_watch": True, "zoom": 1.5}}
    state.save_prefs(json.dumps(stale).encode(), from_page=True)
    s = state.get_prefs()["settings"]
    assert s == {"save_recordings": False, "reward_watch": False, "zoom": 1.5}
    assert AppState(Settings(home=tmp_path)).rewards.save_recordings is False


def test_railjack_nodes_are_not_star_chart_nodes(tmp_path: Path, codex_path: Path):  # noqa: F811
    db = tmp_path / "c.sqlite"
    db.write_bytes(codex_path.read_bytes())
    snap = parse_profile(_profile(), taken_at=datetime(2026, 11, 1, tzinfo=UTC))
    before = build_report(snap, Codex(db)).headline.starchart_total
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO node (id, name, planet) VALUES ('CrewBattleNode553', 'Flexa', 'Railjack')")
    assert build_report(snap, Codex(db)).headline.starchart_total == before


def test_an_unchanged_profile_still_counts_as_just_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import openwarframe.account.sync as sync

    s = Settings(home=tmp_path, account_id="5" * 24)
    data = _profile()
    SnapshotStore(s.snapshots_dir).save(parse_profile(data, taken_at=datetime(2026, 1, 1, tzinfo=UTC)))
    monkeypatch.setattr(sync, "fetch_profile", lambda *a, **k: data)  # nothing changed since January
    _, _, written = sync.sync_profile(s)
    assert written is False
    assert AppState(s).profile_age_hours() < 0.1


def test_the_pop_out_never_comes_back_off_screen(tmp_path: Path):
    w = NativeWindows("u", tmp_path / "webview")
    w._save_popout(x=-32000, y=-32000)  # Windows' position for a minimised window
    assert w._popout_geometry()["x"] == 40
    w._save_popout(x=3000, y=100)  # on a second monitor that is later unplugged
    one_screen = [(0, 0, 1920, 1080)]
    assert w._popout_geometry(one_screen)[("x")] == 40
    assert w._popout_geometry([(0, 0, 1920, 1080), (1920, 0, 2560, 1440)])["x"] == 3000


def test_a_rate_limited_price_check_stops_instead_of_waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import openwarframe.sources.static.market as market

    state = AppState(Settings(home=tmp_path))
    rows = [{"id": f"r{i}", "slug": f"s{i}"} for i in range(80)]
    monkeypatch.setattr(state, "build", lambda force=False: {"relics": rows})
    calls: list[str] = []

    def limited(client, slug, **k):
        calls.append(slug)
        req = httpx.Request("GET", "https://x")
        raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))

    monkeypatch.setattr(market, "top_prices", limited)
    assert state.fetch_prices([r["id"] for r in rows]) == {}
    assert calls == ["s0"]


def test_an_inventory_loaded_before_the_account_follows_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import openwarframe.account.sync as sync

    state = AppState(Settings(home=tmp_path))
    (tmp_path / "inventory.json").write_text('{"Suits": []}', encoding="utf-8")  # loaded on first use
    monkeypatch.setattr(sync, "sync_profile", lambda s, **k: None)
    monkeypatch.setattr(state, "build", lambda force=False: {})
    state.set_account(json.dumps({"id": "ab" * 12}).encode())
    assert state.inventory_path == tmp_path / "accounts" / ("ab" * 12) / "inventory.json"
    assert state.inventory_path.exists()


def test_a_damaged_settings_entry_does_not_stop_the_app(tmp_path: Path):
    (tmp_path / "app-prefs.json").write_text(
        '{"settings": null, "goals": "x", "checks": {}}', encoding="utf-8"
    )
    state = AppState(Settings(home=tmp_path))  # used to raise AttributeError
    assert state.get_prefs() == {"checks": {}}
    with pytest.raises(ValueError):
        state.save_prefs(b'{"settings": null}')
