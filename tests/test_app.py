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

    res = {r["name"]: r for r in build_resources(cx.conn, inv, lambda uid: None)}
    assert res["Orokin Cell"]["need"] == 3 and res["Orokin Cell"]["short"] == 2

    sell = {r["id"]: r for r in build_sell(cx.conn, inv, lambda u: RHINO, set(), {})}
    # Rhino Prime is already built in INVENTORY, so its one blueprint is spare
    assert sell[RHINO_BP]["spare"] == 1 and sell[RHINO_BP]["ducats_total"] == 45
