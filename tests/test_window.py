"""The app's own window: when it is used, what a pinned taskbar button runs, and fallbacks.

The window itself needs a desktop, so these tests cover the decisions around it.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

from openwarframe.app import server as srv
from openwarframe.app import window as win
from openwarframe.config import Settings


def test_browser_window_when_asked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(win, "available", lambda: True)
    assert srv._use_native(None) is True
    assert srv._use_native(False) is False
    monkeypatch.setenv("OPENWARFRAME_BROWSER_WINDOW", "1")
    assert srv._use_native(None) is False


def test_not_available_off_windows(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert win.available() is False
    assert win.set_process_app_id() is False
    assert win.set_window_identity(123, "x", "y") is False


def test_pinned_button_runs_the_exe_when_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    exe = tmp_path / "OpenWarframe.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert win.relaunch_command() == f'"{exe}"'


def test_pinned_button_runs_the_launcher_when_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    launcher = tmp_path / "openwarframe-app.exe"
    monkeypatch.setattr(
        win.shutil, "which", lambda name: str(launcher) if name == "openwarframe-app" else None
    )
    assert win.relaunch_command() == f'"{launcher}"'
    monkeypatch.setattr(win.shutil, "which", lambda name: None)
    assert win.relaunch_command().endswith(" -m openwarframe.app")


def test_icon_ships_with_the_package():
    assert Path(win.icon_path()).is_file()


def test_failed_window_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    state = srv.AppState(Settings(home=tmp_path))

    def boom(self):
        raise RuntimeError("WebView2 missing")

    monkeypatch.setattr(win.NativeWindows, "run", boom)
    assert srv._run_native("http://127.0.0.1:1/", state) is False
    assert state.windows is None


class FakeWindows:
    def __init__(self):
        self.popouts = 0
        self.raised = 0

    def open_popout(self):
        self.popouts += 1

    def raise_main(self):
        self.raised += 1
        return True


def _post(base: str, path: str) -> dict:
    req = urllib.request.Request(base + path, data=b"", method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=5).read())


def test_raise_and_popout_use_the_own_window(server):  # noqa: F811
    base, state = server
    assert _post(base, "/api/raise") == {"native": False}  # browser-window app: nothing to raise
    state.windows = FakeWindows()
    assert _post(base, "/api/raise") == {"native": True}
    assert _post(base, "/api/reward/popout") == {"ok": True}
    assert state.windows.raised == 1 and state.windows.popouts == 1


from test_app import server  # noqa: E402, F401  (the running test server fixture)
