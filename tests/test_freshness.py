"""Milestone 7: fresh data and quality of life. No network."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openwarframe.account import SnapshotStore, parse_profile
from openwarframe.app import server as server_mod
from openwarframe.app.data import build_app_data
from openwarframe.app.server import AppState, _version_tuple, page_source
from openwarframe.codex import Codex
from openwarframe.config import Settings
from openwarframe.inventory import parse_inventory
from test_account import _profile
from test_app import INVENTORY
from test_codex_build import codex_path  # noqa: F401
from test_guide import _report

PAGE = page_source()


def _snapshot_at(settings: Settings, hours_ago: float) -> None:
    taken = datetime.now(UTC) - timedelta(hours=hours_ago)
    SnapshotStore(settings.snapshots_dir).save(parse_profile(_profile(), taken_at=taken))


# -- game data ------------------------------------------------------------------------------


def test_offline_after_an_update_keeps_using_the_old_game_data(
    tmp_path: Path,
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    import openwarframe.codex as codex_mod

    s = Settings(home=tmp_path)
    s.codex_path.write_bytes(codex_path.read_bytes())
    with sqlite3.connect(s.codex_path) as c:  # one schema behind, still readable
        c.execute("UPDATE source_version SET version = '2' WHERE source = 'schema'")

    def offline(settings, **_):
        raise OSError("no network")

    monkeypatch.setattr(codex_mod, "update_codex", offline)
    state = AppState(s)
    assert state.ensure_codex() is None
    assert "could not be updated" in state.codex_warning and "no network" in state.codex_warning


def test_game_data_date_and_unknown_blueprints_are_reported(codex_path: Path):  # noqa: F811
    inv = parse_inventory(
        {**INVENTORY, "Recipes": INVENTORY["Recipes"] + [{"ItemType": "/New/Thing", "ItemCount": 1}]}
    )
    meta = build_app_data(_report(), Codex(codex_path), inv)["meta"]
    assert meta["unknown_blueprints"] == 1
    assert meta["game_data"]  # when the public export was downloaded


# -- the profile on open ------------------------------------------------------------------------


@pytest.mark.parametrize(("hours", "synced"), [(30, True), (2, False)])
def test_an_old_profile_is_fetched_again_on_open(tmp_path: Path, hours: float, synced: bool):
    s = Settings(home=tmp_path, account_id="a" * 24)
    _snapshot_at(s, hours)
    state = AppState(s)
    calls: list[str] = []
    state.sync = lambda: calls.append("sync")
    state.build = lambda force=False: calls.append("build")
    state.refresh_on_open()
    assert calls == (["sync"] if synced else ["build"])
    assert abs(state.profile_age_hours() - hours) < 0.1


def test_a_failed_refresh_on_open_still_shows_the_data(tmp_path: Path):
    s = Settings(home=tmp_path, account_id="a" * 24)
    _snapshot_at(s, 48)
    state = AppState(s)
    calls: list[str] = []

    def offline():
        raise OSError("offline")

    state.sync = offline
    state.build = lambda force=False: calls.append("build")
    state.refresh_on_open()
    assert calls == ["build"]


# -- new versions ----------------------------------------------------------------------------


def test_versions_compare_as_numbers():
    assert _version_tuple("v0.10.0") > _version_tuple("0.9.9")
    assert _version_tuple("garbage") < _version_tuple("0.0.1")


def test_the_update_check_reports_newer_releases_and_can_be_turned_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from openwarframe.http import CachedClient

    monkeypatch.setattr(
        CachedClient, "get_json", lambda self, url, **k: {"tag_name": "v99.0.0", "html_url": "https://x/rel"}
    )
    state = AppState(Settings(home=tmp_path))
    info = state.check_for_update()
    assert info["newer"] is True and info["latest"] == "99.0.0" and info["url"] == "https://x/rel"
    state.save_prefs(json.dumps({"settings": {"check_updates": False}}).encode())
    assert state.check_for_update()["disabled"] is True


# -- export from the app -----------------------------------------------------------------------


def test_export_writes_files_and_only_export_folders_can_be_opened(
    tmp_path: Path,
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    s = Settings(home=tmp_path)
    s.codex_path.write_bytes(codex_path.read_bytes())
    _snapshot_at(s, 1)
    state = AppState(s)
    out = state.export(json.dumps({"formats": ["json", "csv"]}).encode())
    folder = Path(out["folder"])
    assert (folder / "account.json").exists() and [f["format"] for f in out["files"]] == ["json", "csv"]

    opened: list = []
    monkeypatch.setattr(server_mod.subprocess, "Popen", lambda args, **k: opened.append(args))
    monkeypatch.setattr(server_mod.os, "startfile", lambda p: opened.append(p), raising=False)
    state.open_folder(json.dumps({"folder": str(folder)}).encode())
    assert opened
    with pytest.raises(ValueError):
        state.open_folder(json.dumps({"folder": str(tmp_path)}).encode())  # not an export folder


# -- remembered state ---------------------------------------------------------------------------


def test_view_filters_and_the_session_plan_are_saved(tmp_path: Path):
    state = AppState(Settings(home=tmp_path))
    state.save_prefs(
        json.dumps(
            {"views": {"relics": {"F": {"tier": "Axi"}}}, "session": {"plan": {"minutes": 30}}}
        ).encode()
    )
    p = state.get_prefs()
    assert p["views"]["relics"]["F"]["tier"] == "Axi" and p["session"]["plan"]["minutes"] == 30


def test_the_pop_out_remembers_where_it_was_put(tmp_path: Path):
    from openwarframe.app.window import NativeWindows

    w = NativeWindows("http://127.0.0.1:1/", tmp_path / "webview")
    assert w._popout_geometry() == {"width": 440, "height": 300, "x": 40, "y": 40}
    w._save_popout(x=1900, y=120)
    w._save_popout(width=520, height=360)
    assert NativeWindows("u", tmp_path / "webview")._popout_geometry() == {
        "width": 520,
        "height": 360,
        "x": 1900,
        "y": 120,
    }


def test_prices_are_rechecked_after_six_hours():
    assert server_mod.PRICE_MAX_AGE == 6 * 3600


def test_the_page_keeps_time_based_things_current():
    assert "function foundryLeft" in PAGE and "Date.parse(r.ready_at)" in PAGE  # Foundry timers
    assert "setInterval(function(){ if(DATA) loadLive(true); }, 60000);" in PAGE  # Live everywhere
    assert "LIVE.here.log_age_min>120" in PAGE  # stale "you are here"
    assert 'VIEW==="live"||VIEW==="farm"' in PAGE  # one headline per screen
    assert "function goView" in PAGE and "function restoreSession" in PAGE


def test_snapshot_mtime_is_not_used_for_profile_age(tmp_path: Path):
    s = Settings(home=tmp_path, account_id="a" * 24)
    _snapshot_at(s, 50)
    f = next(s.snapshots_dir.glob("*.json"))
    os.utime(f, (time.time(), time.time()))  # touched today, taken two days ago
    assert AppState(s).profile_age_hours() > 48


def test_steel_path_only_filter_is_remembered_and_steers_the_picks():
    # checkbox filters are saved as `true` (functions were lost on restart), with the test in CHECKS
    assert 'bind("fsponly","_sponly",function(r){return r.steel_path},"_nosp");' in PAGE
    assert "if(want===true&&CHECKS[k])" in PAGE
    assert "if(steelPathOnly()) return !!f.steel_path;" in PAGE  # Right now pick and suggestions
