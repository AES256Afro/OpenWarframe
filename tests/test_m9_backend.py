"""M9 backend fixes: vendor names and price labels, market rank/refinement filter, gzip,
caches (EE.log, live, snapshots, OCR probe), invasion factions, /api/names, cache pruning.
No network."""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from openwarframe.app import live as live_mod
from openwarframe.app.live import build_live, faction_name, you_are_here
from openwarframe.app.server import AppState, _accepts_gzip, make_handler
from openwarframe.codex import Codex
from openwarframe.codex.build import _item_json
from openwarframe.codex.display import (
    display_name_for,
    price_label,
    price_parts,
    split_camel,
    vendor_display_name,
)
from openwarframe.config import Settings
from openwarframe.http import CachedClient, prune_cache
from openwarframe.sources.static.market import price_basis, top_prices
from test_codex_build import CELL, RHINO, RHINO_BP, codex_path  # noqa: F401
from test_live_app import NOW, WORLD, FakeClient, _data

VM = "/Lotus/Types/Game/VendorManifests"


# -- D3: vendor names and price labels ----------------------------------------------------
def test_vendor_names_read_like_the_game():
    assert vendor_display_name(f"{VM}/Ostron/FishmongerVendorManifest") == "Fisher Hai-Luk (Cetus)"
    assert vendor_display_name(f"{VM}/Solaris/FishmongerVendorManifest") == "The Business (Fortuna)"
    assert vendor_display_name(f"{VM}/Hubs/HunhowVendorManifest") == "Hunhow"
    assert (
        vendor_display_name(f"{VM}/Events/RadioLegionIntermission10VendorManifest")
        == "Nightwave: Intermission 10"
    )
    # unknown vendors: words, no "Vendor"/"Manifest", and where they stand when known
    assert vendor_display_name(f"{VM}/Zariman/ArchimedeanVendorManifest") == "Archimedean (Chrysalith)"
    assert vendor_display_name(f"{VM}/Events/WaterFightVendorManifest") == "Water Fight"
    assert vendor_display_name(f"{VM}/FocusSchools/MaduraiVendorManifest") == "Madurai focus school"
    assert vendor_display_name("HunhowVendor") == "Hunhow"  # an old database's stored name
    assert vendor_display_name(None) == "Vendor"
    assert split_camel("RadioLegionIntermission10") == "Radio Legion Intermission 10"
    assert split_camel("EliteAlertVendor") == "Elite Alert Vendor"


def test_price_keys_get_labels():
    assert price_label("regularPrice") == "Credits"
    assert price_label("premiumPrice") == "Platinum"
    assert price_label("primePrice") == "Ducats"
    assert price_label("someNewCost") == "Some New Cost"
    parts = price_parts(
        {
            "credits": {"minValue": 5000, "maxValue": 15000},
            "platinum": 120,
            "premiumPrice": 0,
            "syndicate": {"tag": "EntratiLabSyndicate", "minRank": 5, "standingCost": 30000},
            "focusXpCost": {"polarity": "AP_ATTACK", "cost": 1000000},
        },
        {"EntratiLabSyndicate": "Cavia"},
    )
    assert parts == [
        "5,000–15,000 Credits",
        "120 Platinum",
        "30,000 Cavia Standing",
        "Cavia rank 5",
        "1,000,000 Madurai Focus",
    ]
    assert price_parts({"credits": "junk", "syndicate": "x", "focusXpCost": 3}) == []


def test_vendor_sources_show_names_not_file_names(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    vendor = next(s for s in cx.sources_for(CELL) if s.kind == "vendor")
    assert vendor.where == "Loid (Necralisk)"
    assert "regularPrice" not in vendor.detail and "premiumPrice" not in vendor.detail
    # an older database stores the cut-down file name and raw price keys: still readable
    conn = sqlite3.connect(codex_path)
    conn.execute(
        "UPDATE vendor_offer SET vendor_name = 'FishmongerVendor', vendor = ?, prices = ?",
        (f"{VM}/Ostron/FishmongerVendorManifest", json.dumps({"items": [], "premiumPrice": 7})),
    )
    conn.commit()
    conn.close()
    cx = Codex(codex_path)
    vendor = next(s for s in cx.sources_for(CELL) if s.kind == "vendor")
    assert vendor.where == "Fisher Hai-Luk (Cetus)" and vendor.detail == "7 Platinum"


def test_display_names_for_any_id(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    assert display_name_for(cx.conn, RHINO) == "Rhino Prime"
    assert cx.display_name(RHINO_BP) == "Rhino Prime Blueprint"
    assert cx.display_name(f"{VM}/Hubs/HunhowVendorManifest") == "Hunhow"
    assert cx.display_name("/Lotus/Types/Something/BrandNewThing") == "Brand New Thing"


def test_cosmetic_records_keep_only_what_is_read():
    rec = {"uniqueName": "/x", "name": "Big", "primeSellingPrice": 15, "description": "long" * 100}
    assert json.loads(_item_json("Cosmetic", rec)) == {"primeSellingPrice": 15}
    assert json.loads(_item_json("Warframe", rec)) == rec


# -- F8: market prices by rank and refinement ---------------------------------------------
class OrdersClient:
    def __init__(self, data: dict) -> None:
        self.data, self.urls = data, []

    def get_json(self, url: str, **_):
        self.urls.append(url)
        return {"data": self.data}


def test_top_prices_filters_by_rank():
    orders = {
        "sell": [{"platinum": 90, "rank": 10}, {"platinum": 20, "rank": 0}, {"platinum": 25}],
        "buy": [{"platinum": 70, "rank": 10}, {"platinum": 15, "rank": 0}],
    }
    client = OrdersClient(orders)
    p = top_prices(client, "primed_flow", rank=0)
    assert client.urls[-1].endswith("/primed_flow/top?rank=0")
    assert p == {"low": 20, "typical": 25, "buy": 15, "basis": "rank 0"}
    p = top_prices(client, "primed_flow")  # no filter: everything counts, as before
    assert client.urls[-1].endswith("/primed_flow/top") and p["low"] == 20 and p["buy"] == 70
    assert p["basis"] is None


def test_top_prices_filters_relics_to_intact():
    orders = {"sell": [{"platinum": 60, "subtype": "radiant"}, {"platinum": 9, "subtype": "intact"}]}
    client = OrdersClient(orders)
    p = top_prices(client, "axi_a1_relic", subtype="intact")
    assert client.urls[-1].endswith("?subtype=intact")
    assert p["low"] == p["typical"] == 9 and p["buy"] is None and p["basis"] == "intact"


def test_price_basis_from_market_tags():
    assert price_basis(["mod", "legendary"]) == {"rank": 0}
    assert price_basis(["rare", "arcane_enhancement"]) == {"rank": 0}
    assert price_basis(["relic", "axi"]) == {"subtype": "intact"}
    assert price_basis(["set", "prime"]) == {} and price_basis(None) == {}


def test_server_prices_mods_unranked_and_relics_intact(
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    import openwarframe.sources.static.market as market

    conn = sqlite3.connect(codex_path)
    conn.executemany(
        "INSERT OR REPLACE INTO market_item VALUES (?,?,?,?)",
        [("/m", "a_mod", "A Mod", '["mod"]'), ("/r", "a_relic", "A Relic", '["relic"]')],
    )
    conn.commit()
    conn.close()
    state = AppState(Settings(home=codex_path.parent))
    rows = [{"id": "m", "slug": "a_mod"}, {"id": "r", "slug": "a_relic"}, {"id": "s", "slug": "a_set"}]
    monkeypatch.setattr(state, "build", lambda force=False: {"mods": rows})
    seen = {}

    def fake(client, slug, **kw):
        seen[slug] = kw
        return {"low": 1, "typical": 2, "buy": None, "basis": None}

    monkeypatch.setattr(market, "top_prices", fake)
    out = state.fetch_prices(["m", "r", "s"], kind="mods")
    assert set(out) == {"m", "r", "s"} and out["m"]["typical"] == 2
    assert seen == {"a_mod": {"rank": 0}, "a_relic": {"subtype": "intact"}, "a_set": {}}


# -- O2: gzip -----------------------------------------------------------------------------
def test_accept_encoding_parsing():
    assert _accepts_gzip("gzip, deflate, br")
    assert _accepts_gzip("br;q=1.0, gzip;q=0.8")
    assert not _accepts_gzip("gzip;q=0")
    assert not _accepts_gzip(None) and not _accepts_gzip("br")


@pytest.fixture
def server(codex_path: Path):  # noqa: F811
    state = AppState(Settings(home=codex_path.parent))
    state.cache = {"meta": {"mr": 1}, "items": [{"id": str(i), "name": "x" * 40} for i in range(200)]}
    state.cache_fp = state._fingerprint()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", state
    srv.shutdown()
    srv.server_close()


def test_data_is_gzipped_when_the_page_accepts_it(server):
    base, _ = server
    req = urllib.request.Request(base + "/api/data", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req) as r:
        assert r.headers["Content-Encoding"] == "gzip"
        raw = r.read()
    plain = json.loads(gzip.decompress(raw))
    assert plain["meta"]["mr"] == 1 and len(plain["items"]) == 200
    with urllib.request.urlopen(base + "/api/data") as r:  # no Accept-Encoding: plain JSON
        assert r.headers.get("Content-Encoding") is None
        assert json.loads(r.read())["meta"]["mr"] == 1
    req = urllib.request.Request(base + "/api/ping", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req) as r:  # tiny answers are not worth compressing
        assert r.headers.get("Content-Encoding") is None


# -- /api/names ---------------------------------------------------------------------------
def test_names_endpoint(server):
    base, _ = server
    ids = [RHINO, RHINO_BP, f"{VM}/Hubs/HunhowVendorManifest", "/Lotus/Unknown/FancyThing"]
    url = base + "/api/names?ids=" + ",".join(urllib.parse.quote(i, safe="") for i in ids)
    names = json.loads(urllib.request.urlopen(url).read())
    assert names == {
        RHINO: "Rhino Prime",
        RHINO_BP: "Rhino Prime Blueprint",
        f"{VM}/Hubs/HunhowVendorManifest": "Hunhow",
        "/Lotus/Unknown/FancyThing": "Fancy Thing",
    }
    assert json.loads(urllib.request.urlopen(base + "/api/names").read()) == {}
    req = urllib.request.Request(base + "/api/names?ids=x", headers={"Origin": "https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 403
    req = urllib.request.Request(base + "/api/names?ids=x", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 403


# -- O5: caches ---------------------------------------------------------------------------
LOG_LINE = (
    '10.000 Sys [Info]: Client loaded {{"difficulty":0,"name":"{node}"}} with MissionInfo:\n'
    '{{\n    "missionType" : "MT_DEFENSE",\n    "faction" : "FC_GRINEER"\n}}\n'
)


def test_you_are_here_reads_the_log_only_when_it_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    log = tmp_path / "EE.log"
    log.write_text(LOG_LINE.format(node="SolNode1"), encoding="utf-8")
    first = you_are_here(log)
    assert first and first["node"] == "SolNode1"
    first["where"] = "changed by the caller"  # callers add fields; the cache must not keep them
    opened = []
    real_open = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: opened.append(self) or real_open(self, *a, **k))
    again = you_are_here(log)
    assert again["node"] == "SolNode1" and "where" not in again and opened == []
    log.write_text(LOG_LINE.format(node="SolNode1") + LOG_LINE.format(node="SolNode2"), encoding="utf-8")
    st = log.stat()
    os.utime(log, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    opened.clear()  # write_text opened it too
    assert you_are_here(log)["node"] == "SolNode2" and opened == [log]
    assert you_are_here(tmp_path / "missing.log") is None


def test_live_answer_is_reused_until_the_log_changes(
    codex_path: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import openwarframe.live.eelog as eelog

    log = tmp_path / "EE.log"
    log.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(eelog, "default_log_path", lambda: log)
    state = AppState(Settings(home=codex_path.parent))
    data = _data(False)
    monkeypatch.setattr(state, "build", lambda force=False: data)
    built = []
    monkeypatch.setattr(
        live_mod, "build_live", lambda conn, d, client, **k: built.append(1) or {"n": len(built)}
    )
    assert state.live() == {"n": 1}
    assert state.live() == {"n": 1} and len(built) == 1
    st = log.stat()
    os.utime(log, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert state.live() == {"n": 2}
    state._live = (state._live[0], time.monotonic() - 3600, state._live[2])  # expired
    assert state.live() == {"n": 3}


def test_newest_snapshot_is_seen_at_once(tmp_path: Path):
    """No folder-time cache: Windows can keep the folder's time when a file is added."""
    s = Settings(home=tmp_path)
    s.ensure_dirs()
    state = AppState(s)
    assert state._fingerprint()[0] is None
    (s.snapshots_dir / "2026-11-24T181907Z.json").write_text("{}", encoding="utf-8")
    (s.snapshots_dir / "notes.txt").write_text("x", encoding="utf-8")
    assert state._fingerprint()[0] == "2026-11-24T181907Z.json"
    st = s.snapshots_dir.stat()
    (s.snapshots_dir / "2026-11-25T000000Z.json").write_text("{}", encoding="utf-8")
    os.utime(s.snapshots_dir, ns=(st.st_atime_ns, st.st_mtime_ns))  # folder time unchanged
    assert state._fingerprint()[0] == "2026-11-25T000000Z.json"


def test_ocr_probe_runs_once(monkeypatch: pytest.MonkeyPatch):
    from openwarframe.app import rewards
    from openwarframe.live import ocr

    calls = []
    probe = lambda: calls.append(1) or True  # noqa: E731
    monkeypatch.setattr(ocr, "ocr_available", probe)
    monkeypatch.setattr(rewards, "_OCR", None)
    assert rewards.ocr_available() and rewards.ocr_available() and len(calls) == 1
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)  # a new probe is asked again
    assert rewards.ocr_available() is False


# -- U11: invasion factions ---------------------------------------------------------------
def test_invasions_name_the_factions(codex_path: Path, tmp_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    world = json.loads(json.dumps(WORLD))
    world["Invasions"][0]["DefenderFaction"] = "FC_INFESTATION"
    live = build_live(cx.conn, _data(True), FakeClient(world), now_ms=NOW, log_path=tmp_path / "none.log")
    inv = live["invasions"][0]
    assert inv["attacker_faction"] == "Grineer" and inv["defender_faction"] == "Infested"
    assert inv["attacker"] == "Grineer"  # existing field kept
    assert inv["rewards"][0]["side"] == "Attacker" and inv["rewards"][0]["faction"] == "Grineer"
    assert faction_name("FC_CORPUS") == "Corpus" and faction_name("FC_NEW_ONES") == "New Ones"
    assert faction_name(None) == ""


# -- O6: HTTP cache pruning ---------------------------------------------------------------
def test_old_cache_entries_are_pruned(tmp_path: Path):
    client = CachedClient(tmp_path)
    old_body, old_meta = client._paths("https://old.example/")
    new_body, new_meta = client._paths("https://new.example/")
    orphan, _ = client._paths("https://orphan.example/")
    for p in (old_body, old_meta, new_body, new_meta, orphan):
        p.write_text("{}", encoding="utf-8")
    other = tmp_path / "notes.txt"
    other.write_text("keep", encoding="utf-8")
    long_ago = time.time() - 90 * 86400
    for p in (old_body, old_meta, orphan, other):
        os.utime(p, (long_ago, long_ago))
    os.utime(new_body, (long_ago, long_ago))  # an old body whose metadata is fresh stays
    client.close()
    assert prune_cache(tmp_path) == 2
    assert not old_body.exists() and not old_meta.exists() and not orphan.exists()
    assert new_body.exists() and new_meta.exists() and other.exists()
    assert prune_cache(tmp_path / "missing") == 0


def test_console_profile_never_drops_to_http_on_tls_trouble():
    import ssl

    import httpx

    from openwarframe.sources.account.profile import _tls_problem

    tls = httpx.ConnectError("handshake")
    tls.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")
    assert _tls_problem(tls)
    assert not _tls_problem(httpx.ConnectError("[Errno 61] Connection refused"))
