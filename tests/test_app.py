"""Inventory reader, desktop app data and the local server. No network, no browser."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from openwarframe.app.data import build_app_data
from openwarframe.app.server import AppState, make_handler
from openwarframe.codex import Codex
from openwarframe.config import Settings
from openwarframe.inventory import load_inventory, parse_inventory, refinement_of, relic_base
from test_codex_build import CELL, CHASSIS, CHASSIS_BP, RELIC, RHINO, RHINO_BP, codex_path  # noqa: F401
from test_guide import _report

INVENTORY = {
    "Suits": [{"ItemType": RHINO, "XP": 1000}],
    "LongGuns": [],
    "MiscItems": [
        {"ItemType": RELIC, "ItemCount": 2},
        {"ItemType": RELIC.replace("Bronze", "Platinum"), "ItemCount": 1},
        {"ItemType": CELL, "ItemCount": 1},
    ],
    "Recipes": [{"ItemType": RHINO_BP, "ItemCount": 1}],
    "RegularCredits": 5000,
}


def test_relic_names_and_refinements():
    assert refinement_of(RELIC.replace("Bronze", "Gold")) == "Flawless"
    assert relic_base(RELIC.replace("Bronze", "Silver")) == RELIC


def test_parse_inventory_counts_everything():
    inv = parse_inventory(INVENTORY)
    assert inv.owns(RHINO) and not inv.owns("/x")
    assert inv.relics[RELIC] == {"Intact": 2, "Radiant": 1}
    assert inv.recipes[RHINO_BP] == 1 and inv.misc[CELL] == 1
    assert inv.credits == 5000
    with pytest.raises(ValueError):
        parse_inventory({"hello": 1})


def test_load_inventory_unwraps_tool_exports(tmp_path: Path):
    p = tmp_path / "inv.json"
    p.write_text(json.dumps({"InventoryJson": json.dumps(INVENTORY)}), encoding="utf-8")
    assert load_inventory(p).owns(RHINO)


def test_app_data_without_inventory_marks_ownership_unknown(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    d = build_app_data(_report(), cx, None)
    assert d["meta"]["inventory"] is None
    assert all(i["owned"] is None for i in d["items"])
    assert {i["state"] for i in d["items"]} <= {"Mastered", "Leveling", "Never leveled"}
    assert d["blueprints"] == []


def test_app_data_with_inventory_tracks_relics_and_blueprint_parts(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    d = build_app_data(_report(), cx, parse_inventory(INVENTORY))
    relic = next(r for r in d["relics"] if r["id"] == RELIC)
    assert relic["count"] == 3 and relic["refinements"] == {"Intact": 2, "Radiant": 1}
    # the fixture relic drops nowhere in the drop tables, so its parts count as vaulted
    assert relic["vaulted"] and relic["vaulted_parts"] == 1 and relic["drops"][0]["vaulted"]
    bp = next(b for b in d["blueprints"] if b["id"] == RHINO_BP)
    parts = {p["name"]: p for p in bp["parts"]}
    assert parts["Orokin Cell"]["short"] == 2  # recipe wants 3, inventory has 1
    chassis = parts["Rhino Prime Chassis"]
    assert chassis["short"] == 1
    assert any(r["relic"] == "Lith R2" and r["owned"] == 3 for r in chassis["relics"])
    assert not bp["ready"]
    assert CHASSIS_BP  # imported for clarity: the relic drops the chassis blueprint


@pytest.fixture
def server(tmp_path: Path):
    state = AppState(Settings(home=tmp_path))
    state.cache = {"meta": {"mr": 1}, "items": [], "relics": [], "blueprints": []}
    state.cache_fp = state._fingerprint()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", state
    srv.shutdown()
    srv.server_close()


def test_server_serves_page_and_data(server):
    base, _ = server
    page = urllib.request.urlopen(base + "/").read().decode("utf-8")
    assert "<title>OpenWarframe</title>" in page
    assert json.loads(urllib.request.urlopen(base + "/api/data").read())["meta"]["mr"] == 1


def test_server_rejects_other_origins(server):
    base, _ = server
    req = urllib.request.Request(
        base + "/api/inventory/clear", data=b"", method="POST", headers={"Origin": "https://evil.example"}
    )
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 403


def test_server_rejects_non_inventory_upload(server):
    base, state = server
    req = urllib.request.Request(base + "/api/inventory", data=b'{"not": "inventory"}', method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 400
    assert not state.inventory_path.exists()


def test_inventory_reads_mods_and_wallet():
    data = dict(INVENTORY)
    data["RawUpgrades"] = [{"ItemType": "/Mods/Vitality", "ItemCount": 3}]
    data["Upgrades"] = [{"ItemType": "/Mods/Vitality", "UpgradeFingerprint": '{"lvl":10}'}]
    data["FusionPoints"] = 1234
    data["PendingRecipes"] = [{"ItemType": RHINO_BP, "CompletionDate": {"$date": {"$numberLong": "1"}}}]
    inv = parse_inventory(data)
    assert inv.mods["/Mods/Vitality"] == {"unranked": 3, "ranks": [10]}
    assert inv.endo == 1234 and inv.pending[0]["recipe"] == RHINO_BP


def test_extras_foundry_resources_and_sell(codex_path: Path):  # noqa: F811
    import sqlite3

    from openwarframe.app.extras import build_foundry, build_resources, build_sell

    with sqlite3.connect(codex_path) as w:
        w.execute("UPDATE recipe SET ducats = 45 WHERE unique_name = ?", (RHINO_BP,))
    cx = Codex(codex_path)
    data = dict(INVENTORY)
    data["PendingRecipes"] = [{"ItemType": CHASSIS_BP, "CompletionDate": {"$date": {"$numberLong": "1"}}}]
    data["MiscItems"] = data["MiscItems"] + [{"ItemType": CHASSIS, "ItemCount": 2}]
    inv = parse_inventory(data)

    foundry = build_foundry(cx.conn, inv)
    assert foundry[0]["ready"] and foundry[0]["name"] == "Rhino Prime Chassis"

    # Rhino Prime is already built, so its blueprint needs no resources any more
    res = {r["name"]: r for r in build_resources(cx.conn, inv, lambda uid: None, cx.graph, set())}
    assert "Orokin Cell" not in res
    not_built = parse_inventory({**data, "Suits": []})
    res = {r["name"]: r for r in build_resources(cx.conn, not_built, lambda uid: None, cx.graph, set())}
    assert res["Orokin Cell"]["need"] == 3 and res["Orokin Cell"]["short"] == 2

    sell = {r["id"]: r for r in build_sell(cx.conn, inv, cx.graph, set(), {})}
    # Rhino Prime is already built in INVENTORY, so its one blueprint is spare
    assert sell[RHINO_BP]["spare"] == 1 and sell[RHINO_BP]["ducats_total"] == 45


def test_prefs_are_saved_merged_and_filtered(tmp_path: Path):
    state = AppState(Settings(home=tmp_path))
    assert state.get_prefs() == {}
    state.save_prefs(json.dumps({"goals": ["/a"], "evil": 1}).encode())
    merged = state.save_prefs(json.dumps({"settings": {"zoom": 1.15}}).encode())
    assert merged == {"goals": ["/a"], "settings": {"zoom": 1.15}}
    assert json.loads(state.prefs_path.read_text(encoding="utf-8"))["goals"] == ["/a"]
    with pytest.raises(ValueError):
        state.save_prefs(b"[1, 2]")


def test_fingerprint_changes_when_new_data_lands(tmp_path: Path):
    s = Settings(home=tmp_path)
    s.ensure_dirs()
    state = AppState(s)
    before = state._fingerprint()
    (s.snapshots_dir / "2026-11-24T181907Z.json").write_text("{}", encoding="utf-8")
    after_snapshot = state._fingerprint()
    assert after_snapshot != before
    state.inventory_path.write_text(json.dumps(INVENTORY), encoding="utf-8")
    assert state._fingerprint() != after_snapshot


def test_latest_keyword_beats_a_stray_file_named_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from openwarframe.account.store import SnapshotStore

    store = SnapshotStore(tmp_path / "snaps")
    (store.directory / "2026-10-17T201719Z.json").write_text("{}", encoding="utf-8")
    (store.directory / "2026-11-24T181907Z.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "latest").write_text("not a snapshot", encoding="utf-8")
    assert store._resolve("latest").name == "2026-11-24T181907Z.json"
    assert store._resolve("previous").name == "2026-10-17T201719Z.json"
    assert store._resolve("2026-10").name == "2026-10-17T201719Z.json"


def _old_codex(src: Path, dest: Path) -> None:
    """A copy of the fixture database as an older release left it: schema 1, no ducats."""
    import sqlite3

    dest.write_bytes(src.read_bytes())
    conn = sqlite3.connect(dest)
    conn.execute("ALTER TABLE recipe DROP COLUMN ducats")
    conn.execute("UPDATE source_version SET version = '1' WHERE source = 'schema'")
    conn.commit()
    conn.close()


def test_schema_version_is_read_from_disk(tmp_path: Path, codex_path: Path):  # noqa: F811
    from openwarframe.codex import codex_schema_version
    from openwarframe.codex.schema import SCHEMA_VERSION

    assert codex_schema_version(tmp_path / "missing.sqlite") == 0
    assert codex_schema_version(codex_path) == SCHEMA_VERSION
    (tmp_path / "junk.sqlite").write_bytes(b"not a database")
    assert codex_schema_version(tmp_path / "junk.sqlite") == 0


def test_outdated_database_is_updated_before_building(
    tmp_path: Path,
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    import openwarframe.codex as codex_mod
    from openwarframe.codex.schema import SCHEMA_VERSION

    home = tmp_path / "home"
    home.mkdir()
    s = Settings(home=home)
    _old_codex(codex_path, s.codex_path)
    calls = []

    def fake_update(settings, **_):
        calls.append(settings.codex_path)
        settings.codex_path.write_bytes(codex_path.read_bytes())

    monkeypatch.setattr(codex_mod, "update_codex", fake_update)
    out = AppState(s).build()
    assert calls == [s.codex_path]
    assert codex_mod.codex_schema_version(s.codex_path) == SCHEMA_VERSION
    assert "ducats" not in out.get("error", "") and out.get("setup") is True


def test_failed_database_update_is_reported_not_raised(
    tmp_path: Path,
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    import openwarframe.codex as codex_mod

    home = tmp_path / "home"
    home.mkdir()
    s = Settings(home=home)
    _old_codex(codex_path, s.codex_path)

    def offline(settings, **_):
        raise OSError("no network")

    monkeypatch.setattr(codex_mod, "update_codex", offline)
    out = AppState(s).build()
    assert "could not be updated" in out["error"] and "no network" in out["error"]
    assert out["can_update"] is True


def test_data_errors_come_back_as_json(server, monkeypatch: pytest.MonkeyPatch):
    base, state = server

    def boom(**_):
        raise RuntimeError("no such column: ducats")

    monkeypatch.setattr(state, "build", boom)
    out = json.loads(urllib.request.urlopen(base + "/api/data").read())
    assert "no such column: ducats" in out["error"] and out["can_update"] is True


def test_second_launch_finds_the_running_app(server):
    from openwarframe.app.server import _running_instance

    base, state = server
    assert _running_instance(state.settings) is None
    port = int(base.rsplit(":", 1)[1])
    (state.settings.home / "app.lock").write_text(json.dumps({"port": port, "pid": 1}), encoding="utf-8")
    assert _running_instance(state.settings) == port
    (state.settings.home / "app.lock").write_text('{"port": 1, "pid": 1}', encoding="utf-8")
    assert _running_instance(state.settings) is None


def test_no_account_shows_setup_instead_of_an_error(tmp_path: Path, codex_path: Path):  # noqa: F811
    home = tmp_path / "home"
    home.mkdir()
    s = Settings(home=home)
    s.codex_path.write_bytes(codex_path.read_bytes())
    out = AppState(s).build()
    assert out["setup"] is True and out["has_account"] is False and "can_update" not in out


def test_typed_account_id_is_checked_saved_and_fetched(server, monkeypatch: pytest.MonkeyPatch):
    base, state = server
    monkeypatch.setattr(state, "sync", lambda: {"synced": True})

    def post(body: dict):
        req = urllib.request.Request(base + "/api/account", data=json.dumps(body).encode(), method="POST")
        return json.loads(urllib.request.urlopen(req).read())

    with pytest.raises(urllib.error.HTTPError) as err:
        post({"id": "not-an-id"})
    assert err.value.code == 400 and "24 characters" in json.loads(err.value.read())["error"]
    assert state.settings.account_id is None
    assert post({"id": "AB" * 12, "platform": "pc"}) == {"synced": True}
    assert state.settings.account_id == "ab" * 12
    assert "ab" * 12 in (state.settings.home / "config.toml").read_text(encoding="utf-8")


def test_first_grab_saves_the_account_and_fetches_the_profile(server, monkeypatch: pytest.MonkeyPatch):
    from openwarframe.sources.account import session

    base, state = server
    state.settings.extra["session_reader_ok"] = True
    monkeypatch.setattr(session, "SUPPORTED", True)
    monkeypatch.setattr(session, "grab_session", lambda expected=None: ("cd" * 12, INVENTORY))
    monkeypatch.setattr(state, "sync", lambda: {"synced": True})
    assert state.grab(accept=False) == {"synced": True}
    assert state.settings.account_id == "cd" * 12
    assert load_inventory(state.inventory_path).owns(RHINO)
