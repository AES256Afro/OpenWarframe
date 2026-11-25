"""Relic reward helper inside the app.

A background thread follows EE.log. When the fissure reward screen opens it waits a
moment for the names to be drawn, captures the game window, reads the reward names with
the system OCR (Windows.Media.Ocr or Apple Vision), matches them to relic rewards and
ranks them for this account. The newest
result is served at /api/reward and shown in the Rewards tab and the pop-out window.

Only the log file and screen pixels are read. Nothing touches game memory or input.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import UTC, datetime

from ..config import Settings

log = logging.getLogger(__name__)
CAPTURE_DELAY = 1.5
MARKET_TOP = "https://api.warframe.market/v2/orders/item/{slug}/top"
PRICE_TIMEOUT = 4  # seconds per request: prices are a bonus, the pick must not wait on them
KEEP_RECORDINGS = 30  # newest reward screens kept when saving them is on
OCR_LANGUAGE = "en-US"  # the item list is English; reading with the profile language fails


def _price_map(slugs: list[str], cache_dir) -> dict[str, float]:
    """Typical sell price per market slug (cached 6 h). Best effort."""
    from ..http import CachedClient
    from ..sources.static.market import order_prices

    out: dict[str, float] = {}
    client = CachedClient(cache_dir, timeout=PRICE_TIMEOUT, retries=1)
    try:
        for slug in slugs:
            try:
                top = client.get_json(MARKET_TOP.format(slug=slug), max_age=6 * 3600).get("data", {})
            except Exception:  # noqa: BLE001
                continue
            sells = sorted(order_prices(top.get("sell")))[:5]
            if sells:
                out[slug] = sells[len(sells) // 2]
    finally:
        client.close()
    return out


def prune_recordings(home, keep: int = KEEP_RECORDINGS) -> int:
    """Delete all but the newest ``keep`` saved reward screens. Returns how many went."""
    import shutil

    from ..live.reward import recordings_dir

    root = recordings_dir(home)
    if not root.is_dir():
        return 0
    old = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)[keep:]
    for d in old:
        shutil.rmtree(d, ignore_errors=True)
    return len(old)


class RewardWatcher:
    """Follows EE.log in a thread and reads each fissure reward screen.

    The game database is only open while the reward list is loaded, never while watching:
    on Windows an open file can't be replaced, so a database held for hours blocked every
    game-data update. Each run has its own stop signal, so a quick Stop then Start can't
    leave two threads writing the status.
    """

    def __init__(self, settings: Settings, *, save_recordings: bool = False) -> None:
        self.settings = settings
        self.lock = threading.Lock()  # status fields
        self._control = threading.Lock()  # start/stop
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.state = "off"  # off | starting | watching | reading | error
        self.message = ""
        self.last: dict | None = None
        self.history: deque[dict] = deque(maxlen=12)
        self.save_recordings = save_recordings
        self._context_stamp: tuple | None = None

    # -- control ---------------------------------------------------------------------
    def status(self) -> dict:
        from ..live.ocr import ocr_available

        with self.lock:
            return {
                "state": self.state,
                "message": self.message,
                "ocr": ocr_available(),
                "last": self.last,
                "history": list(self.history),
                "save_recordings": self.save_recordings,
            }

    def start(self) -> dict:
        from ..live.ocr import ocr_available

        if not ocr_available():
            with self.lock:
                self.state, self.message = "error", "Text recognition is not available on this system."
            return self.status()
        with self._control:
            old = self.thread
            if old and old.is_alive():
                if not self.stop_event.is_set():
                    return self.status()  # already watching
                old.join(timeout=5)  # stopping: let it finish its current screen
                if old.is_alive():
                    with self.lock:
                        self.message = "Still finishing the last screen. Try again in a moment."
                    return self.status()
            stop = self.stop_event = threading.Event()
            with self.lock:
                self.state, self.message = "starting", "Loading the reward list…"
            self.thread = threading.Thread(target=self._run, args=(stop,), name="reward-watcher", daemon=True)
            self.thread.start()
        return self.status()

    def stop(self) -> dict:
        with self._control:
            self.stop_event.set()
            with self.lock:
                self.state, self.message = "off", "Stopped."
        return self.status()

    def set_recording(self, on: bool) -> dict:
        self.save_recordings = bool(on)
        return self.status()

    def _say(self, stop: threading.Event, state: str, message: str) -> None:
        """Update the status, unless this run was stopped (a newer run owns the status)."""
        if stop.is_set():
            return
        with self.lock:
            self.state, self.message = state, message

    # -- work ------------------------------------------------------------------------
    def _data_stamp(self) -> tuple:
        """Changes when the game database, inventory or newest snapshot changes."""
        s = self.settings

        def mtime(p):
            try:
                return p.stat().st_mtime_ns
            except OSError:
                return None

        snaps = sorted(s.snapshots_dir.glob("*.json")) if s.snapshots_dir.exists() else []
        return (mtime(s.codex_path), mtime(s.home / "inventory.json"), snaps[-1].name if snaps else None)

    def _context(self):
        """(reward catalog, account needs). The database is closed before this returns."""
        from ..codex import Codex
        from ..live.match import RewardCatalog, account_needs

        self._context_stamp = self._data_stamp()
        codex = Codex(self.settings.codex_path)
        try:
            catalog = RewardCatalog.from_codex(codex.conn)
        finally:
            codex.close()
        return catalog, account_needs(self.settings)

    def _analyze(
        self, image, catalog, needs, *, source: str, event: dict | None = None, prices_now: bool = False
    ):
        """Read and rank one screen; publish the pick at once, then add prices.

        Prices come from warframe.market and can take seconds on a slow connection, while
        the reward screen gives 15. The pick without prices is published first; prices
        re-rank it a moment later (or right away with ``prices_now``, for the sample).
        """
        from ..live import ocr
        from ..live.reward import analyze, save_recording

        analysis = analyze(image, catalog, ui_scale=ocr.read_ui_scale(), language=OCR_LANGUAGE, needs=needs)
        result = analysis.to_dict()
        result["time"] = datetime.now(UTC).isoformat(timespec="seconds")
        result["source"] = source
        result["prices"] = {}
        result["pick"] = result["ranked"][0] if result["ranked"] else None
        if not prices_now:
            self._publish(result)
        if source == "game" and self.save_recordings:
            try:
                d = save_recording(self.settings.home, image, analysis, event=event)
                result["saved_to"] = str(d)
                prune_recordings(self.settings.home)
            except OSError as exc:
                log.warning("could not save recording: %s", exc)
        priced = self._add_prices(analysis, result, needs)
        if prices_now:
            self._publish(priced)
        return priced

    def _add_prices(self, analysis, result: dict, needs) -> dict:
        from ..live.match import rank

        slugs = [m.entry.slug for m in analysis.matches if m.entry and m.entry.slug]
        prices = _price_map(slugs, self.settings.cache_dir) if slugs else {}
        if not prices:
            return result
        needed, parts, owned = needs
        analysis.ranked = rank(
            analysis.matches, needed_items=needed, owned_parts=parts, owned_items=owned, prices=prices
        )
        priced = {**result, **analysis.to_dict(), "prices": prices}
        priced["pick"] = priced["ranked"][0] if priced["ranked"] else None
        with self.lock:  # replace the unpriced result if it is still the one on show
            if self.last is result:
                self.last = priced
            for i, r in enumerate(self.history):
                if r is result:
                    self.history[i] = priced
        return priced

    def _publish(self, result: dict) -> None:
        with self.lock:
            self.last = result
            self.history.appendleft(result)

    def _run(self, stop: threading.Event) -> None:
        from ..live import ocr
        from ..live.eelog import default_log_path, watch

        try:
            catalog, needs = self._context()
        except Exception as exc:  # noqa: BLE001
            self._say(stop, "error", f"Could not load the game database: {exc}")
            return
        path = default_log_path()
        if path.exists():
            self._say(stop, "watching", "Waiting for a fissure reward screen.")
        else:
            self._say(
                stop,
                "watching",
                f"Waiting for the game log at {path}. Start Warframe once; if it lives somewhere "
                "else, set OPENWARFRAME_WARFRAME_DIR to the game's folder.",
            )
        try:
            reported: list[str] = []
            for ev in watch(path, should_stop=stop.is_set):
                if ev.kind == "reward_reported":
                    reported.append(ev.data.get("item", ""))
                elif ev.kind in ("reward_screen_closed", "mission_loaded"):
                    reported = []
                if ev.kind != "reward_screen_opened":
                    continue
                self._say(stop, "reading", "Reward screen open, reading names…")
                if stop.wait(CAPTURE_DELAY):
                    break
                try:
                    if self._data_stamp() != self._context_stamp:
                        catalog, needs = self._context()  # synced, new inventory or game data
                    win = ocr.find_game_window()
                    if win is None:
                        self._say(stop, "watching", "Reward screen seen, but the game window was not found.")
                        continue
                    self._analyze(
                        ocr.capture(win),
                        catalog,
                        needs,
                        source="game",
                        event={"kind": ev.kind, "time": ev.time, "reported": list(reported)},
                    )
                    msg = "Waiting for the next reward screen."
                except Exception as exc:  # noqa: BLE001 - keep watching after a bad read
                    log.warning("reward read failed: %s", exc)
                    msg = f"Could not read that screen ({exc}). Still watching."
                self._say(stop, "watching", msg)
        except Exception as exc:  # noqa: BLE001
            self._say(stop, "error", f"Watching stopped: {exc}")

    def demo(self, names: list[str] | None = None, players: int = 4) -> dict:
        """Run the whole pipeline on a drawn sample screen, to check OCR works here."""
        from ..live.synthetic import reward_screen

        catalog, needs = self._context()
        names = (
            names or [e.name for e in catalog.entries[:: max(1, len(catalog.entries) // players)]][:players]
        )
        image = reward_screen(names, (1920, 1080))
        result = self._analyze(image, catalog, needs, source="sample", prices_now=True)
        result["sample_names"] = names
        return result


def keep_on_top(title: str, timeout: float = 10.0) -> bool:
    """Mark a top-level window with this exact title as always-on-top (Windows)."""
    import sys

    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            HWND_TOPMOST = ctypes.c_void_p(-1)  # noqa: N806
            return bool(user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010))
        time.sleep(0.3)
    return False
