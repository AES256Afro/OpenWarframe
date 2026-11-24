"""Game-session reader: pattern search, process scan (on a stand-in process) and download."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import httpx
import pytest

from openwarframe.app.server import AppState
from openwarframe.config import Settings, load_settings
from openwarframe.sources.account import session as sess
from openwarframe.sources.account.session import (
    Session,
    SessionError,
    fetch_inventory,
    find_sessions,
    pick_session,
)
from test_app import INVENTORY

ACC = "0123456789abcdef01234567"
OTHER = "fedcba9876543210fedcba98"


def test_find_sessions_counts_well_formed_matches_only():
    buf = (
        b"junk?accountId=" + ACC.encode() + b"&nonce=123456789 more "
        b"?accountId=" + ACC.encode() + b"&nonce=123456789&x=1 "
        b"?accountId=nothex_______________&nonce=1 "
        b"?accountId=" + OTHER.encode() + b"&nonce=55555"
    )
    found = find_sessions(buf)
    assert found[(ACC, "123456789")] == 2
    assert found[(OTHER, "55555")] == 1
    assert len(found) == 2


def test_pick_session_prefers_the_configured_account():
    found = Counter({(OTHER, "1111"): 5, (ACC, "2222"): 2})
    assert pick_session(found).account_id == OTHER
    assert pick_session(found, ACC) == Session(ACC, "2222", 2)
    assert pick_session(Counter()) is None


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_inventory_returns_json_and_sends_the_session():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=INVENTORY)

    assert fetch_inventory(Session(ACC, "42", 3), _client(handler))["Suits"]
    assert seen == {"accountId": ACC, "nonce": "42"}


def test_fetch_inventory_explains_a_refused_session():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="nope")

    with pytest.raises(SessionError, match="HTTP 403"):
        fetch_inventory(Session(ACC, "42", 3), _client(handler))


@pytest.mark.skipif(sys.platform != "win32", reason="process reading is Windows only")
def test_scan_process_reads_a_stand_in_process():
    code = (
        "import sys,time\n"
        "a='?account'+'Id='+'0123456789abcdef'+'01234567'+'&nonce='+'987654321'\n"
        "keep=[bytearray(a.encode()) for _ in range(3)]\n"
        "print('ready',flush=True)\n"
        "time.sleep(60)\n"
    )
    # a venv python.exe is a launcher that starts the real interpreter as a child process
    exe = getattr(sys, "_base_executable", None) or sys.executable
    proc = subprocess.Popen([exe, "-c", code], stdout=subprocess.PIPE, text=True)  # noqa: S603
    try:
        assert proc.stdout.readline().strip() == "ready"
        found = sess.scan_process(proc.pid, expected_account=ACC)
        assert found is not None
        assert found.account_id == ACC and found.nonce == "987654321" and found.hits >= 3
    finally:
        proc.kill()
        proc.wait()


def test_grab_without_game_explains(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sess, "find_game_pid", lambda: None)
    with pytest.raises(SessionError, match="not running"):
        sess.grab_inventory()


def test_app_asks_for_consent_once_then_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENWARFRAME_HOME", str(tmp_path))
    state = AppState(load_settings())
    monkeypatch.setattr(state, "build", lambda force=False: {"ok": True})
    monkeypatch.setattr(sess, "grab_session", lambda account=None: ("ab" * 12, INVENTORY))
    monkeypatch.setattr(state, "sync", lambda: {"ok": True})  # never touch the network

    first = state.grab(accept=False)
    assert first["needs_consent"] and "own risk" in first["risk"]
    assert not state.inventory_path.exists()

    assert state.grab(accept=True) == {"ok": True}
    assert json.loads(state.inventory_path.read_text(encoding="utf-8"))["Suits"]
    assert load_settings().extra["session_reader_ok"] is True
    assert state.grab(accept=False) == {"ok": True}  # no second prompt
    assert isinstance(Settings(home=tmp_path).home, Path)
