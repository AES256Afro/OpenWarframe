"""How to get an item: sources, parts and the rules for items no drop table records."""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from openwarframe.app.server import AppState, make_handler, page_source
from openwarframe.codex import Codex
from openwarframe.codex.howto import _special_notes, how_to_get
from openwarframe.config import Settings
from test_codex_build import CHASSIS, RELIC, RHINO, codex_path  # noqa: F401


def test_prime_frame_lists_relics_for_its_parts(codex_path: Path):  # noqa: F811
    with Codex(codex_path) as cx:
        h = how_to_get(cx, RHINO, owned_relics={RELIC: 3})
    assert h["name"] == "Rhino Prime" and h["slug"] == "rhino_prime_set"
    chassis = next(p for p in h["parts"] if p["id"] == CHASSIS)
    assert chassis["component"]
    relic = next(s for s in chassis["sources"] if s["kind"] == "relic")
    assert not relic["where"].endswith("relic")  # "Lith R1", not "Lith R1 relic"
    assert relic["owned"] == 3
    assert "% intact" in relic["detail"] and "% radiant" in relic["detail"]
    assert relic["intact"] is not None and relic["radiant"] is not None
    # components come before resources
    kinds = [p["component"] for p in h["parts"]]
    assert kinds == sorted(kinds, reverse=True)


@pytest.mark.parametrize(
    ("uid", "name", "category", "recipe", "says"),
    [
        ("/Lotus/Weapons/Grineer/Bows/GrnBow/GrnBowWeapon", "Kuva Bramma", "Primary",
         "/Lotus/Types/Recipes/Weapons/KuvaWeapons/KuvaGrnBowBlueprint", "Kuva Lich"),
        ("/Lotus/Weapons/Corpus/X", "Tenet Arca Plasmor", "Primary", None, "Sister of Parvos"),
        ("/Lotus/Weapons/Corpus/Y", "Tenet Livia", "Melee", None, "Ergo Glast"),
        ("/Lotus/Weapons/Infested/Z", "Coda Motovore", "Melee", None, "Technocyte Coda"),
        ("/Lotus/Weapons/ClanTech/Chemical/FlameThrower", "Ignis", "Primary",
         "/Lotus/Weapons/ClanTech/Chemical/FlameThrowerBlueprint", "Chem Lab"),
        ("/Lotus/Weapons/Tenno/Rifle/Rifle", "Braton", "Primary", "/x/BratonBlueprint", None),
    ],
)  # fmt: skip
def test_items_without_drop_data_get_a_written_rule(uid, name, category, recipe, says):
    notes = _special_notes(uid, name, category, recipe)
    if says is None:
        assert notes == []  # handled by the "usually the Market" fallback instead
    else:
        assert len(notes) == 1 and says in notes[0]


def test_unknown_blueprint_falls_back_to_market_wording(codex_path: Path):  # noqa: F811
    conn = sqlite3.connect(codex_path)
    with conn:
        for table in ("relic_reward", "node_reward", "market_item"):
            conn.execute(f"DELETE FROM {table}")  # noqa: S608
    conn.close()
    with Codex(codex_path) as cx:
        h = how_to_get(cx, RHINO)
    assert h["sources"] == [] and h["slug"] is None
    assert any("Prime Resurgence" in n or "Market" in n for n in h["notes"])


@pytest.fixture
def server(codex_path: Path):  # noqa: F811
    state = AppState(Settings(home=codex_path.parent))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def test_howto_endpoint(server):
    url = server + "/api/howto?id=" + urllib.parse.quote(RHINO, safe="")
    h = json.loads(urllib.request.urlopen(url).read())
    assert h["name"] == "Rhino Prime" and h["parts"]
    missing = json.loads(urllib.request.urlopen(server + "/api/howto?id=%2FLotus%2FNope").read())
    assert "error" in missing
    req = urllib.request.Request(url, headers={"Origin": "http://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 403


def test_page_asks_for_howto_when_details_open():
    page = page_source()
    assert '"/api/howto?id="+encodeURIComponent(id)' in page
    assert "function howtoHtml(h)" in page
    assert "No drop sources recorded" not in page
    # every value from the lookup goes through esc()
    body = page[page.index("function howtoSource(x)") : page.index("function renderTable()")]
    assert "+x.where+" not in body and "+n+" not in body
