from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from openwarframe.live import paths


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENWARFRAME_WARFRAME_DIR", str(tmp_path))
    assert paths.warframe_dir() == tmp_path


def test_mac_picks_the_most_recent_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENWARFRAME_WARFRAME_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    native = tmp_path / "Library/Application Support/Warframe"
    wine = (
        tmp_path
        / "Library/Application Support/CrossOver/Bottles/Steam/drive_c/users/crossover/AppData/Local/Warframe"
    )
    for d in (native, wine):
        d.mkdir(parents=True)
        (d / "EE.log").write_text("x")
    os.utime(native / "EE.log", (1, 1))
    assert paths.warframe_dir() == wine
    os.utime(wine / "EE.log", (0, 0))
    assert paths.warframe_dir() == native


def test_mac_without_game_points_at_native_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENWARFRAME_WARFRAME_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.warframe_dir() == tmp_path / "Library/Application Support/Warframe"
