"""Reward helper inside the app: watcher state, sample pipeline, pop-out helper."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openwarframe.app.rewards import RewardWatcher, keep_on_top
from openwarframe.config import Settings
from openwarframe.live.ocr import ocr_available
from test_codex_build import codex_path  # noqa: F401


def _settings(tmp_path: Path, codex: Path) -> Settings:
    s = Settings(home=tmp_path)
    s.ensure_dirs()
    (tmp_path / "codex.sqlite").write_bytes(codex.read_bytes())
    return s


def test_watcher_starts_off_and_stops_cleanly(tmp_path: Path, codex_path: Path):  # noqa: F811
    w = RewardWatcher(_settings(tmp_path, codex_path))
    st = w.status()
    assert st["state"] == "off" and st["last"] is None and st["history"] == []
    assert w.stop()["state"] == "off"


@pytest.mark.skipif(not ocr_available(), reason="Windows OCR not available")
def test_sample_screen_runs_the_whole_pipeline(
    tmp_path: Path,
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    from openwarframe.app import rewards

    monkeypatch.setattr(rewards, "_price_map", lambda slugs, cache: {})
    w = RewardWatcher(_settings(tmp_path, codex_path))
    r = w.demo(["Rhino Prime Chassis Blueprint", "Orokin Cell"], players=2)
    assert r["source"] == "sample" and r["players"] == 2
    names = {x["name"] for x in r["ranked"]}
    assert "Rhino Prime Chassis Blueprint" in names
    assert w.status()["last"]["time"] == r["time"]
    assert not (tmp_path / "live").exists()  # sample screens are not saved as recordings


def test_keep_on_top_gives_up_quietly():
    if sys.platform != "win32":
        assert keep_on_top("x", timeout=0.1) is False
    else:
        assert keep_on_top("no window has this title 7f3a", timeout=0.3) is False
