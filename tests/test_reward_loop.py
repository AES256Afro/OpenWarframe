"""The reward watcher's whole loop: log events in, a ranked pick out. No game, no OCR."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from openwarframe.app import rewards as rewards_mod
from openwarframe.app.rewards import RewardWatcher
from openwarframe.config import Settings
from openwarframe.live import ocr
from openwarframe.live.eelog import Event
from openwarframe.live.match import RewardCatalog, RewardEntry, rank
from openwarframe.live.reward import Analysis

CATALOG = RewardCatalog([RewardEntry("/u/forma", "Forma Blueprint", "/f", "Forma")])


def _fake_game(monkeypatch: pytest.MonkeyPatch, events: list[Event], window=object()) -> threading.Event:
    from openwarframe.live import eelog, reward

    done = threading.Event()

    def watch(path, should_stop):
        yield from events
        done.set()
        while not should_stop():
            done.wait(0.01)

    monkeypatch.setattr(eelog, "watch", watch)
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "find_game_window", lambda: window)
    monkeypatch.setattr(ocr, "capture", lambda win: "image")
    monkeypatch.setattr(ocr, "read_ui_scale", lambda: 1.0)
    matches = [CATALOG.match("FORMA BLUEPRINT")]
    monkeypatch.setattr(reward, "analyze", lambda *a, **k: Analysis(1, 1.0, {}, matches, rank(matches)))
    monkeypatch.setattr(rewards_mod, "CAPTURE_DELAY", 0)
    monkeypatch.setattr(rewards_mod, "_price_map", lambda slugs, cache: {})
    monkeypatch.setattr(RewardWatcher, "_context", lambda self: (CATALOG, (set(), {}, set())))
    return done


def test_a_reward_screen_in_the_log_becomes_a_pick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    done = _fake_game(
        monkeypatch,
        [
            Event("mission_loaded", 1.0, "", {}),
            Event("reward_screen_opened", 2.0, "", {"marker": "Got rewards"}),
        ],
    )
    w = RewardWatcher(Settings(home=tmp_path))
    w.start()
    assert done.wait(5)
    w.stop()
    w.thread.join(5)
    last = w.status()["last"]
    assert last and last["pick"]["name"] == "Forma Blueprint" and last["source"] == "game"


def test_no_game_window_keeps_watching_and_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    done = _fake_game(monkeypatch, [Event("reward_screen_opened", 2.0, "", {})], window=None)
    w = RewardWatcher(Settings(home=tmp_path))
    w.start()
    assert done.wait(5)
    for _ in range(100):
        if "not found" in w.status()["message"]:
            break
        done.wait(0.01)
    assert w.status()["state"] == "watching" and "game window was not found" in w.status()["message"]
    w.stop()
