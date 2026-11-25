"""Relic reward helper inside the app.

A background thread follows EE.log. When the fissure reward screen opens it waits a
moment for the names to be drawn, captures the game window, reads the reward names with
Windows OCR, matches them to relic rewards and ranks them for this account. The newest
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


def _price_map(slugs: list[str], cache_dir) -> dict[str, float]:
    """Typical sell price per market slug (cached 6 h). Best effort."""
    from ..http import CachedClient
    from ..sources.static.market import order_prices

    out: dict[str, float] = {}
    client = CachedClient(cache_dir, timeout=8, retries=1)
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


class RewardWatcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.state = "off"  # off | starting | watching | reading | error
        self.message = ""
        self.last: dict | None = None
        self.history: deque[dict] = deque(maxlen=12)
        self.save_recordings = True

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
        if self.thread and self.thread.is_alive():
            return self.status()
        self.stop_event.clear()
        with self.lock:
            self.state, self.message = "starting", "Loading the reward list…"
        self.thread = threading.Thread(target=self._run, name="reward-watcher", daemon=True)
        self.thread.start()
        return self.status()

    def stop(self) -> dict:
        self.stop_event.set()
        with self.lock:
            self.state, self.message = "off", "Stopped."
        return self.status()

    # -- work ------------------------------------------------------------------------
    def _context(self):
        from ..codex import Codex
        from ..live.match import RewardCatalog, account_needs

        codex = Codex(self.settings.codex_path)
        return codex, RewardCatalog.from_codex(codex.conn), account_needs(self.settings)

    def _analyze(self, image, catalog, needs, *, source: str, event: dict | None = None) -> dict:
        from ..live import ocr
        from ..live.match import rank
        from ..live.reward import analyze, save_recording

        scale = ocr.read_ui_scale()
        analysis = analyze(image, catalog, ui_scale=scale, needs=needs)
        slugs = [m.entry.slug for m in analysis.matches if m.entry and m.entry.slug]
        prices = _price_map(slugs, self.settings.cache_dir) if slugs else {}
        if prices:
            needed, parts, owned = needs
            analysis.ranked = rank(
                analysis.matches, needed_items=needed, owned_parts=parts, owned_items=owned, prices=prices
            )
        result = analysis.to_dict()
        result["time"] = datetime.now(UTC).isoformat(timespec="seconds")
        result["source"] = source
        result["prices"] = prices
        result["pick"] = result["ranked"][0] if result["ranked"] else None
        if source == "game" and self.save_recordings:
            try:
                d = save_recording(self.settings.home, image, analysis, event=event)
                result["saved_to"] = str(d)
            except OSError as exc:
                log.warning("could not save recording: %s", exc)
        with self.lock:
            self.last = result
            self.history.appendleft(result)
        return result

    def _run(self) -> None:
        from ..live import ocr
        from ..live.eelog import default_log_path, watch

        try:
            codex, catalog, needs = self._context()
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.state, self.message = "error", f"Could not load the game database: {exc}"
            return
        path = default_log_path()
        with self.lock:
            self.state, self.message = "watching", "Waiting for a fissure reward screen."
        try:
            reported: list[str] = []
            for ev in watch(path, should_stop=self.stop_event.is_set):
                if ev.kind == "reward_reported":
                    reported.append(ev.data.get("item", ""))
                elif ev.kind in ("reward_screen_closed", "mission_loaded"):
                    reported = []
                if ev.kind != "reward_screen_opened":
                    continue
                with self.lock:
                    self.state, self.message = "reading", "Reward screen open, reading names…"
                time.sleep(CAPTURE_DELAY)
                win = ocr.find_game_window()
                if win is None:
                    with self.lock:
                        self.state, self.message = (
                            "watching",
                            "Reward screen seen, but the game window was not found.",
                        )
                    continue
                try:
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
                with self.lock:
                    self.state, self.message = "watching", msg
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.state, self.message = "error", f"Watching stopped: {exc}"
        finally:
            codex.close()
            if self.stop_event.is_set():
                with self.lock:
                    self.state = "off"

    def demo(self, names: list[str] | None = None, players: int = 4) -> dict:
        """Run the whole pipeline on a drawn sample screen, to check OCR works here."""
        from ..live.synthetic import reward_screen

        codex, catalog, needs = self._context()
        try:
            names = (
                names
                or [e.name for e in catalog.entries[:: max(1, len(catalog.entries) // players)]][:players]
            )
            image = reward_screen(names, (1920, 1080))
            result = self._analyze(image, catalog, needs, source="sample")
            result["sample_names"] = names
            return result
        finally:
            codex.close()


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
