"""Milestone 4: the reward helper under real-world conditions. No network, no game, no OCR."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from openwarframe.app import rewards as rewards_mod
from openwarframe.app.rewards import RewardWatcher, prune_recordings
from openwarframe.app.server import AppState
from openwarframe.config import Settings
from openwarframe.live import ocr
from openwarframe.live.eelog import EventParser
from openwarframe.live.match import RewardCatalog, RewardEntry, rank
from openwarframe.live.reward import Analysis
from test_codex_build import codex_path  # noqa: F401


def _catalog(*names: str, **extra) -> RewardCatalog:
    return RewardCatalog(
        [
            RewardEntry(unique_name=f"/u/{n}", name=n, final_item=f"/f/{n}", final_name=n, **extra)
            for n in names
        ]
    )


CATALOG = _catalog("Forma Blueprint", "Burston Prime Barrel", "Lex Prime Receiver", "Akstiletto Prime Link")


# -- squad size ------------------------------------------------------------------------------


def test_one_misread_slot_keeps_a_four_player_screen():
    # The 2-player boxes are the middle two of the 4-player layout, and the 1-player box is
    # the middle of the 3-player layout, so those smaller layouts read real names too.
    layouts = {
        4: ["#~ .:", "FORMA BLUEPRINT", "BURSTON PRIME BARREL", "LEX PRIME RECEIVER"],
        3: ["MA BLUEPR BURS", "TON PRIME BARREL LEX", "PRIME RECEIV"],
        2: ["FORMA BLUEPRINT", "BURSTON PRIME BARREL"],
        1: ["TON PRIME BARREL LEX"],
    }
    players, matches = CATALOG.pick_layout(layouts)
    assert players == 4
    assert matches[0].entry is None
    assert [m.entry.name for m in matches[1:]] == [
        "Forma Blueprint",
        "Burston Prime Barrel",
        "Lex Prime Receiver",
    ]
    assert rank(matches)[-1].reason == "not recognised"


def test_a_two_player_screen_is_still_two_players():
    layouts = {
        4: ["", "FORMA BLUEPRINT", "BURSTON PRIME BARREL", ""],  # outer boxes are empty
        3: ["MA BLUEPR", "TON PRIME BARR", ""],
        2: ["FORMA BLUEPRINT", "BURSTON PRIME BARREL"],
        1: ["TON PRIME BARR"],
    }
    assert CATALOG.pick_layout(layouts)[0] == 2


def test_half_names_in_straddling_boxes_do_not_win():
    # found with real OCR: on a 1-player screen the 2-player boxes each catch half of the
    # name, and both halves fuzzy-match it
    layouts = {
        1: ["FORMA BLUEPRINT"],
        2: ["FORMA BL", "UEPRINT"],
        3: ["", "FORMA BLUEPRINT", ""],
        4: ["", "FORMA BL", "UEPRINT", ""],
    }
    players, matches = _catalog("Forma Blueprint", "Forma").pick_layout(layouts)
    assert players == 1 and matches[0].entry.name == "Forma Blueprint"


def test_each_distinct_box_is_read_once(monkeypatch: pytest.MonkeyPatch):
    from PIL import Image

    calls: list[tuple] = []
    monkeypatch.setattr(ocr, "ocr_lines", lambda img, language=None: calls.append(img.size) or ["X"])
    layouts = ocr.read_all_layouts(Image.new("RGB", (1920, 1080)))
    assert sorted(len(v) for v in layouts.values()) == [1, 2, 3, 4]
    distinct = {b.as_tuple() for n in (4, 3, 2, 1) for b in ocr.slot_boxes(1920, 1080, n, 1.0)}
    assert len(calls) == len(distinct) < 10


# -- uncertain reads -----------------------------------------------------------------------


def test_a_cut_off_name_is_shown_but_never_the_pick():
    cat = _catalog("Saryn Prime Blueprint", "Saryn Prime Chassis Blueprint", "Forma Blueprint")
    clipped = cat.match("SARYN PRIME")
    assert clipped.entry is not None and clipped.unsure_of
    ranked = rank([clipped, cat.match("FORMA BLUEPRINT")])
    assert ranked[0].match.entry.name == "Forma Blueprint"
    assert ranked[1].reason.startswith("unsure: read 'SARYN PRIME'")
    assert cat.match("FORMA BLUEPRINT").unsure_of is None


# -- parts needed twice ------------------------------------------------------------------------


def test_a_part_needed_twice_stays_needed_until_you_hold_two():
    cat = RewardCatalog(
        [
            RewardEntry("/barrel", "Akstiletto Prime Barrel", "/aks", "Akstiletto Prime", need=2),
            RewardEntry(
                "/barrel-bp",
                "Akstiletto Prime Barrel Blueprint",
                "/aks",
                "Akstiletto Prime",
                need=2,
                makes="/barrel",
            ),
        ]
    )
    m = cat.match("AKSTILETTO PRIME BARREL")
    assert rank([m], needed_items={"/aks"}, owned_parts={"/barrel": 1})[0].needed
    assert not rank([m], needed_items={"/aks"}, owned_parts={"/barrel": 2})[0].needed
    bp = cat.match("AKSTILETTO PRIME BARREL BLUEPRINT")
    # one built barrel plus one barrel blueprint is two: the next blueprint is spare
    assert not rank([bp], needed_items={"/aks"}, owned_parts={"/barrel": 1, "/barrel-bp": 1})[0].needed


# -- the log -------------------------------------------------------------------------------------


def _feed(lines: list[str]) -> list[str]:
    p = EventParser()
    return [e.kind for ln in lines for e in p.feed(ln) if e.kind.startswith("reward_screen")]


def test_every_reward_round_is_read_even_without_a_close_line():
    got = "{t} Script [Info]: ProjectionRewardChoice.lua: Got rewards"
    kinds = _feed([got.format(t="100.000"), got.format(t="400.000"), got.format(t="700.000")])
    assert kinds.count("reward_screen_opened") == 3
    assert kinds == ["reward_screen_opened", "reward_screen_closed"] * 2 + ["reward_screen_opened"]


def test_the_same_line_logged_twice_at_once_is_one_screen():
    got = "{t} Script [Info]: ProjectionRewardChoice.lua: Got rewards"
    assert _feed([got.format(t="100.000"), got.format(t="100.400")]) == ["reward_screen_opened"]


# -- the watcher ---------------------------------------------------------------------------


@pytest.fixture
def watcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RewardWatcher:
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    return RewardWatcher(Settings(home=tmp_path))


def test_stop_then_start_right_away_starts_a_fresh_run(
    watcher: RewardWatcher, monkeypatch: pytest.MonkeyPatch
):
    runs: list[threading.Event] = []

    def fake_run(self, stop):
        runs.append(stop)
        self._say(stop, "watching", "fake")
        while not stop.wait(0.01):
            pass
        time.sleep(0.05)  # finishing a screen after the stop
        self._say(stop, "watching", "the old run must not write this")

    monkeypatch.setattr(RewardWatcher, "_run", fake_run)
    watcher.start()
    first = watcher.thread
    assert watcher.start() and watcher.thread is first  # a second Start while watching is a no-op
    watcher.stop()
    watcher.start()
    assert watcher.thread is not first and watcher.thread.is_alive()
    assert len(runs) == 2 and runs[0].is_set() and not runs[1].is_set()
    time.sleep(0.15)
    assert watcher.status()["message"] == "fake"
    watcher.stop()
    watcher.thread.join(1)
    assert watcher.status()["state"] == "off"


def test_the_watcher_never_keeps_the_game_database_open(
    tmp_path: Path,
    codex_path: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    import openwarframe.codex as codex_pkg

    open_now: list = []
    real = codex_pkg.Codex

    class Tracked(real):
        def __init__(self, path):
            super().__init__(path)
            open_now.append(self)

        def close(self):
            open_now.remove(self)
            super().close()

    monkeypatch.setattr(codex_pkg, "Codex", Tracked)
    w = RewardWatcher(Settings(home=codex_path.parent))
    catalog, needs = w._context()
    assert catalog.entries and open_now == []


def test_the_pick_is_shown_before_prices_arrive(watcher: RewardWatcher, monkeypatch: pytest.MonkeyPatch):
    from openwarframe.live import reward

    entry = RewardEntry("/u/forma", "Forma Blueprint", "/f", "Forma", slug="forma_blueprint")
    matches = [CATALOG.match("FORMA BLUEPRINT")]
    matches[0].entry = entry
    monkeypatch.setattr(reward, "analyze", lambda *a, **k: Analysis(1, 1.0, {}, matches, rank(matches)))
    monkeypatch.setattr(ocr, "read_ui_scale", lambda: 1.0)
    release = threading.Event()

    def slow_prices(slugs, cache_dir):
        release.wait(5)
        return {"forma_blueprint": 12}

    monkeypatch.setattr(rewards_mod, "_price_map", slow_prices)
    t = threading.Thread(
        target=watcher._analyze, args=(None, CATALOG, (set(), {}, set())), kwargs={"source": "game"}
    )
    t.start()
    for _ in range(100):
        if watcher.status()["last"]:
            break
        time.sleep(0.01)
    shown = watcher.status()["last"]
    assert shown and shown["pick"]["name"] == "Forma Blueprint" and shown["prices"] == {}
    release.set()
    t.join(2)
    assert watcher.status()["last"]["prices"] == {"forma_blueprint": 12}
    assert len(watcher.status()["history"]) == 1  # replaced, not added twice


def test_needs_reload_when_new_account_data_lands(watcher: RewardWatcher, tmp_path: Path):
    before = watcher._data_stamp()
    (tmp_path / "inventory.json").write_text("{}", encoding="utf-8")
    assert watcher._data_stamp() != before


# -- saved screens ---------------------------------------------------------------------------


def test_saving_screens_is_off_unless_chosen_and_kept_short(tmp_path: Path):
    assert RewardWatcher(Settings(home=tmp_path)).save_recordings is False
    root = tmp_path / "live" / "recordings"
    for i in range(35):
        (root / f"20261125-1200{i:02d}-000").mkdir(parents=True)
    assert prune_recordings(tmp_path, keep=30) == 5
    left = sorted(d.name for d in root.iterdir())
    assert len(left) == 30 and left[0] == "20261125-120005-000"  # the five oldest went


def test_the_recording_choice_survives_a_restart_and_other_saves(tmp_path: Path):
    state = AppState(Settings(home=tmp_path))
    state.save_prefs(json.dumps({"settings": {"save_recordings": True, "reward_watch": True}}).encode())
    # the page saves its own copy of the settings, which doesn't know about those two
    state.save_prefs(json.dumps({"settings": {"zoom": 1.15}}).encode())
    kept = state.get_prefs()["settings"]
    assert kept == {"save_recordings": True, "reward_watch": True, "zoom": 1.15}
    assert AppState(Settings(home=tmp_path)).rewards.save_recordings is True


# -- finding the game window -------------------------------------------------------------------


def test_openwarframe_is_never_taken_for_the_game():
    assert not ocr.is_game_window("OpenWarframe", "OpenWarframe")
    assert not ocr.is_game_window("OpenWarframe", "OpenWarframe reward pick")
    assert ocr.is_game_window("Warframe", "")
    assert ocr.is_game_window("wine64-preloader", "Warframe")
