"""Milestone 1 hardening: the local server, crafted inputs, safe writes and exports. No network."""

from __future__ import annotations

import csv
import http.client
import json
import threading
import urllib.request
from collections import Counter
from pathlib import Path

import pytest
from openpyxl import load_workbook

from openwarframe.account.store import SnapshotStore
from openwarframe.app.data import build_app_data
from openwarframe.codex import Codex
from openwarframe.config import Settings, load_settings, save_settings
from openwarframe.exports.data import write_csv
from openwarframe.exports.tables import build_tables
from openwarframe.exports.xlsx import SHEET_ORDER, write_xlsx
from openwarframe.fsutil import atomic_write_text
from openwarframe.http import CachedClient
from openwarframe.inventory import parse_inventory
from openwarframe.sources.static.market import order_prices
from test_app import INVENTORY, server  # noqa: F401
from test_codex_build import codex_path  # noqa: F401
from test_guide import _report

from .test_exports import report  # noqa: F401

XSS = "<img src=x onerror=alert(1)>"


def _raw(base: str, method: str, path: str, headers: dict, body: bytes = b"") -> tuple[int, dict, bytes]:
    host, port = base.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in headers.items():
        conn.putheader(k, v)
    conn.endheaders(body or None)
    r = conn.getresponse()
    out = r.status, dict(r.getheaders()), r.read()
    conn.close()
    return out


# -- local server -----------------------------------------------------------------------------


def test_requests_for_another_hostname_are_refused(server):  # noqa: F811
    base, _ = server
    port = base.rsplit(":", 1)[1]
    # DNS rebinding: a page on evil.example pointed its hostname at 127.0.0.1
    for method in ("GET", "POST"):
        status, _, _ = _raw(
            base, method, "/api/data", {"Host": f"evil.example:{port}", "Content-Length": "0"}
        )
        assert status == 403
    status, _, _ = _raw(base, "GET", "/api/data", {"Content-Length": "0"})  # no Host at all
    assert status == 403
    for host in (f"127.0.0.1:{port}", f"localhost:{port}"):
        assert _raw(base, "GET", "/api/ping", {"Host": host})[0] == 200


def test_pages_cannot_be_framed_or_load_anything_else(server):  # noqa: F811
    base, _ = server
    with urllib.request.urlopen(base + "/") as r:
        h = r.headers
    assert h["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert "connect-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(("length", "status"), [("abc", 400), ("-1", 400), (str(65 << 20), 413)])
def test_bad_or_huge_content_length_is_refused(server, length: str, status: int):  # noqa: F811
    base, _ = server
    port = base.rsplit(":", 1)[1]
    got, _, _ = _raw(base, "POST", "/api/prefs", {"Host": f"127.0.0.1:{port}", "Content-Length": length})
    assert got == status


def test_consent_can_be_taken_back(server):  # noqa: F811
    base, state = server
    state.settings.extra["session_reader_ok"] = True
    assert json.loads(urllib.request.urlopen(base + "/api/data").read())["meta"]["session_ok"] is True
    req = urllib.request.Request(base + "/api/consent/forget", data=b"", method="POST")
    assert json.loads(urllib.request.urlopen(req).read())["session_ok"] is False
    assert "session_reader_ok" not in load_settings(state.settings.home).extra
    assert json.loads(urllib.request.urlopen(base + "/api/data").read())["meta"]["session_ok"] is False


def test_concurrent_pref_saves_never_fail(tmp_path: Path):
    from openwarframe.app.server import AppState

    state = AppState(Settings(home=tmp_path))
    errors: list[Exception] = []

    def save(i: int) -> None:
        try:
            state.save_prefs(json.dumps({"checks": {"d": {str(i): True}}}).encode())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert isinstance(json.loads(state.prefs_path.read_text(encoding="utf-8")), dict)
    assert not list(tmp_path.glob("*.tmp"))


# -- crafted inventory files ----------------------------------------------------------------


def test_wallet_values_from_a_file_are_numbers_or_nothing():
    inv = parse_inventory(
        {
            **INVENTORY,
            "RegularCredits": XSS,
            "PremiumCredits": "<svg onload=",
            "PremiumCreditsFree": "alert(2)>",
            "FusionPoints": {"$numberLong": "1500"},
            "PrimeTokens": True,
        }
    )
    assert inv.credits is None and inv.platinum is None and inv.regal_aya is None
    assert inv.endo == 1500


def test_zero_platinum_is_zero_not_unknown():
    inv = parse_inventory({**INVENTORY, "PremiumCredits": 0, "PremiumCreditsFree": 0})
    assert inv.platinum == 0
    assert parse_inventory({**INVENTORY, "PremiumCredits": "12", "PremiumCreditsFree": 3}).platinum == 15


def test_crafted_inventory_cannot_put_markup_in_app_data(codex_path: Path):  # noqa: F811
    inv = parse_inventory({**INVENTORY, "RegularCredits": XSS, "PremiumCredits": XSS})
    data = build_app_data(_report(), Codex(codex_path), inv)
    assert XSS not in json.dumps(data["meta"]["inventory"])


def test_market_prices_must_be_numbers():
    assert order_prices(
        [{"platinum": 12}, {"platinum": XSS}, {"platinum": True}, {}, "x", {"platinum": 3.5}]
    ) == [
        12,
        3.5,
    ]
    assert order_prices(None) == []


def test_page_escapes_wallet_and_prices():
    page = (Path(__file__).parents[1] / "src/openwarframe/app/static/index.html").read_text(encoding="utf-8")
    assert "(m.inventory.credits||0).toLocaleString()" not in page
    assert "(inv.platinum||0)+' p'" not in page
    assert "+' '+p.price+'p'" not in page
    assert "amt(m.inventory.credits)" in page


# -- config, snapshots, cache -----------------------------------------------------------------


def test_config_round_trips_windows_paths_quotes_and_tables(tmp_path: Path):
    s = Settings(home=tmp_path, account_id="0123456789abcdef01234567")
    s.extra = {
        "ee_log": "C:\\Users\\me\\AppData\\Local\\Warframe\\EE.log",
        "note": 'say "hi"\n\ttab \x01',
        "flag": True,
        "n": 3,
        "x": 1.5,
        "names": ["a", 'b"c'],
        "ranking": {"vaulted_first": True, "weight": 0.5},
        "odd key": "ok",
    }
    save_settings(s)
    back = load_settings(tmp_path)
    assert back.account_id == s.account_id
    assert back.extra == s.extra


def test_a_broken_config_is_set_aside_and_the_app_still_starts(tmp_path: Path):
    (tmp_path / "config.toml").write_text('ee_log = "C:\\Users\\me"\n', encoding="utf-8")  # invalid escape
    s = load_settings(tmp_path)
    assert s.account_id is None and s.extra == {}
    assert list(tmp_path.glob("config.bad-*.toml"))


def test_a_damaged_latest_snapshot_is_skipped(tmp_path: Path):
    from datetime import UTC, datetime

    from openwarframe.account import parse_profile
    from test_account import _profile

    store = SnapshotStore(tmp_path)
    snap = parse_profile(_profile(), taken_at=datetime(2026, 10, 16, tzinfo=UTC))
    store.save(snap)
    (tmp_path / "2099-01-01T000000Z.json").write_text('{"truncated": ', encoding="utf-8")  # newest, cut short
    assert store.latest() is not None
    assert store.load("latest").taken_at == snap.taken_at


def test_a_damaged_cached_json_file_is_downloaded_again(tmp_path: Path):
    import httpx

    url = "https://example.invalid/data.json"
    calls = Counter()

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    client = CachedClient(tmp_path)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert client.get_json(url) == {"ok": True}
    body, _ = client._paths(url)
    body.write_bytes(b'{"ok": tr')  # cut short on disk
    assert client.get_json(url, max_age=86400) == {"ok": True}
    assert calls["n"] == 2
    client.close()


def test_atomic_write_leaves_no_temp_files(tmp_path: Path):
    p = tmp_path / "a" / "file.json"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert p.read_text(encoding="utf-8") == "two"
    assert [x.name for x in p.parent.iterdir()] == ["file.json"]


# -- exports ----------------------------------------------------------------------------------


def _poison(tables) -> str:
    for t in tables:
        if t.name not in SHEET_ORDER:  # tables the workbook writes as sheets of their own
            continue
        for row in t.rows:
            for col in t.columns:
                if isinstance(row.get(col), str) and col != "wiki_url":
                    row[col] = '=HYPERLINK("https://evil.example","click")'
                    return t.name
    raise AssertionError("no text cell to poison")


def test_excel_export_stores_formula_looking_text_as_text(report, tmp_path: Path):  # noqa: F811
    tables = build_tables(report)
    _poison(tables)
    report.notes.append("bad\x01char from upstream")
    path = write_xlsx(report, tables, tmp_path / "a.xlsx")
    wb = load_workbook(path)
    cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row]
    poisoned = [c for c in cells if isinstance(c.value, str) and c.value.startswith("=HYPERLINK")]
    assert poisoned and all(c.data_type == "s" for c in poisoned)
    assert any(c.value == "badchar from upstream" for c in cells)


def test_csv_export_quotes_formula_looking_text(report, tmp_path: Path):  # noqa: F811
    tables = build_tables(report)
    name = _poison(tables)
    write_csv(tables, tmp_path)
    with (tmp_path / f"{name}.csv").open(encoding="utf-8-sig", newline="") as fh:
        values = [v for row in csv.reader(fh) for v in row]
    assert '\'=HYPERLINK("https://evil.example","click")' in values
    assert not any(v.startswith("=") for v in values)
