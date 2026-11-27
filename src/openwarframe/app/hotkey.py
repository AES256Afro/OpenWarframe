"""A system-wide key that works while the game has focus (Windows).

Used by the reward helper: press the key on a reward screen and the app reads it at once.
Windows' RegisterHotKey delivers the key to us without reading or changing the game's input;
the game never sees that one key combination. On other systems ``start`` says the key
isn't available, and the "Read the screen now" button does the same job.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

DEFAULT = "Ctrl+Alt+F9"
CHOICES = ("Ctrl+Alt+F9", "Ctrl+Shift+F9", "Alt+F9", "Ctrl+Alt+R", "F9")
MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def parse(spec: str) -> tuple[int, int]:
    """'Ctrl+Alt+F9' -> (modifier flags, virtual-key code). ValueError if it isn't a key."""
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("no key given")
    *mods, key = parts
    flags = 0
    for m in mods:
        if m.lower() not in MODIFIERS:
            raise ValueError(f"unknown modifier {m!r}")
        flags |= MODIFIERS[m.lower()]
    k = key.upper()
    if len(k) == 1 and (k.isdigit() or "A" <= k <= "Z"):
        vk = ord(k)
    elif k.startswith("F") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        vk = 0x70 + int(k[1:]) - 1
    else:
        raise ValueError(f"unknown key {key!r}")
    if not flags and not k.startswith("F"):
        raise ValueError("a letter or digit needs Ctrl, Alt or Shift, or it would block typing")
    return flags, vk


class GlobalHotkey:
    """One registered key. ``start`` replaces whatever key was registered before."""

    def __init__(self) -> None:
        self.spec: str | None = None
        self.message = "Off."
        self.active = False
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._lock = threading.Lock()

    def describe(self) -> dict:
        return {"key": self.spec, "active": self.active, "message": self.message, "supported": supported()}

    def start(self, spec: str | None, callback: Callable[[], None]) -> dict:
        self.stop()
        if not spec:
            self.message = "Off."
            return self.describe()
        if not supported():
            self.spec, self.message = (
                spec,
                "A system-wide key works on Windows only. Use the Read now button.",
            )
            return self.describe()
        try:
            mods, vk = parse(spec)
        except ValueError as exc:
            self.spec, self.message = spec, f"Can't use {spec}: {exc}."
            return self.describe()
        ready = threading.Event()
        result: dict = {}
        t = threading.Thread(
            target=self._loop, args=(mods, vk, callback, ready, result), name="hotkey", daemon=True
        )
        t.start()
        ready.wait(5)
        with self._lock:
            self._thread = t
            self.spec = spec
            self.active = bool(result.get("ok"))
            self.message = (
                f"Press {spec} on a reward screen to read it."
                if self.active
                else f"{spec} is taken by another program. Pick another key."
            )
        return self.describe()

    def stop(self) -> None:
        with self._lock:
            tid, t = self._thread_id, self._thread
            self._thread = self._thread_id = None
            self.active = False
        if tid and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if t:
            t.join(timeout=2)

    def _loop(self, mods: int, vk: int, callback, ready: threading.Event, result: dict) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        ok = bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
        result["ok"] = ok
        ready.set()
        if not ok:
            return
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        callback()
                    except Exception:  # noqa: BLE001 - a failing read must not end the key
                        log.exception("hotkey action failed")
        finally:
            user32.UnregisterHotKey(None, 1)


def supported() -> bool:
    return sys.platform == "win32"
