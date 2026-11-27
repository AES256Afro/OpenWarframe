"""Read-now: the global key's parsing and lifecycle, and capture_now on demand."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from openwarframe.app import hotkey, rewards
from openwarframe.app.server import AppState, page_source
from openwarframe.config import Settings


@pytest.mark.parametrize(
    ("spec", "mods", "vk"),
    [
        ("Ctrl+Alt+F9", 0x3, 0x78),
        ("F9", 0, 0x78),
        ("Ctrl+Shift+F12", 0x6, 0x7B),
        ("Ctrl+Alt+R", 0x3, ord("R")),
    ],
)
def test_parse(spec, mods, vk):
    assert hotkey.parse(spec) == (mods, vk)


@pytest.mark.parametrize("spec", ["", "Ctrl+", "Hyper+F9", "Ctrl+Space", "R", "F25"])
def test_parse_rejects(spec):
    with pytest.raises(ValueError):
        hotkey.parse(spec)


def test_every_offered_key_parses():
    for k in hotkey.CHOICES:
        hotkey.parse(k)
    assert hotkey.DEFAULT in hotkey.CHOICES


def test_off_and_unsupported(monkeypatch):
    hk = hotkey.GlobalHotkey()
    assert hk.start(None, lambda: None) == {
        "key": None,
        "active": False,
        "message": "Off.",
        "supported": hotkey.supported(),
    }
    monkeypatch.setattr(hotkey, "supported", lambda: False)
    d = hk.start("Ctrl+Alt+F9", lambda: None)
    assert not d["active"] and "Windows only" in d["message"]


@pytest.mark.skipif(not hotkey.supported(), reason="Windows only")
def test_windows_registers_and_unregisters():
    a, b = hotkey.GlobalHotkey(), hotkey.GlobalHotkey()
    try:
        assert a.start("Ctrl+Alt+Shift+F23", lambda: None)["active"]
        taken = b.start("Ctrl+Alt+Shift+F23", lambda: None)  # one key, one owner
        assert not taken["active"] and "taken" in taken["message"]
        a.stop()
        assert b.start("Ctrl+Alt+Shift+F23", lambda: None)["active"]  # freed by stop
    finally:
        a.stop()
        b.stop()


class FakeOcr:
    def __init__(self, window):
        self.window = window

    def find_game_window(self):
        return self.window

    def capture(self, win):
        return "image"


def _watcher(tmp_path: Path, monkeypatch, window):
    from openwarframe.live import ocr

    w = rewards.RewardWatcher(Settings(home=tmp_path))
    monkeypatch.setattr(rewards, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "find_game_window", FakeOcr(window).find_game_window)
    monkeypatch.setattr(ocr, "capture", FakeOcr(window).capture)
    monkeypatch.setattr(w, "_context", lambda: ("catalog", ("n", "p", "o")))
    seen = []

    def analyze(image, catalog, needs, *, source, **_):
        seen.append((image, catalog, source))
        result = {"ranked": [{"name": "Rhino Prime Systems"}], "source": source}
        w._publish(result)
        return result

    monkeypatch.setattr(w, "_analyze", analyze)
    return w, seen


def _wait(w):
    for _ in range(100):
        if not w._capturing:
            return
        time.sleep(0.02)


def test_capture_now_reads_without_the_log(tmp_path: Path, monkeypatch):
    w, seen = _watcher(tmp_path, monkeypatch, window="game")
    st = w.capture_now("hotkey")
    assert st["message"] == "Reading the screen…"
    _wait(w)
    assert seen == [("image", "catalog", "hotkey")]
    assert w.status()["last"]["source"] == "hotkey" and "asked for" in w.status()["message"]
    assert w.status()["state"] == "off"  # reading once doesn't start watching


def test_capture_now_without_the_game(tmp_path: Path, monkeypatch):
    w, seen = _watcher(tmp_path, monkeypatch, window=None)
    w.capture_now()
    _wait(w)
    assert seen == [] and "not found" in w.status()["message"]


def test_capture_now_without_ocr(tmp_path: Path, monkeypatch):
    w = rewards.RewardWatcher(Settings(home=tmp_path))
    monkeypatch.setattr(rewards, "ocr_available", lambda: False)
    assert "not available" in w.capture_now()["message"]


def test_hotkey_follows_settings_and_capabilities(tmp_path: Path, monkeypatch):
    state = AppState(Settings(home=tmp_path))
    calls = []
    monkeypatch.setattr(state.hotkey, "start", lambda spec, cb: calls.append(spec) or {})
    monkeypatch.setattr(state, "capabilities", lambda: {"game_here": True, "ocr": True})
    state.apply_hotkey()
    state.save_prefs(b'{"settings": {"capture_hotkey": "Alt+F9"}}')
    state.apply_hotkey()
    state.save_prefs(b'{"settings": {"capture_hotkey": ""}}')
    state.apply_hotkey()
    monkeypatch.setattr(state, "capabilities", lambda: {"game_here": False, "ocr": True})
    state.save_prefs(b'{"settings": {"capture_hotkey": "Alt+F9"}}')
    state.apply_hotkey()
    assert calls == ["Ctrl+Alt+F9", "Alt+F9", "", None]  # default, chosen, off, console account
    # the page can't overwrite the key: it is set through its own endpoint
    state.save_prefs(b'{"settings": {"capture_hotkey": "F9"}}', from_page=True)
    assert state.get_prefs()["settings"]["capture_hotkey"] == "Alt+F9"


def test_pages_offer_read_now():
    page = page_source()
    assert 'id="rw-now"' in page and '"/api/reward/capture"' in page and 'id="rw-key"' in page
    mini = page_source("static/mini.html")
    assert 'id="now"' in mini and '"/api/reward/capture"' in mini
