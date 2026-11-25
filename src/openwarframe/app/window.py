"""The app's own window: Edge WebView2 on Windows, WKWebView (Cocoa) on macOS.

Opening the page in a Chrome or Edge ``--app`` window works, but Windows then treats
the window as Chrome's: it sits under Chrome's taskbar button and pinning it pins
Chrome. With this window OpenWarframe has its own taskbar button and icon, and pinning
it starts OpenWarframe again. WebView2 ships with Windows 10 and 11.

If pywebview or the WebView2 runtime is missing, ``available()`` is False and the
server falls back to the Chrome or Edge app window. On macOS pywebview uses the system
WebKit, which is always present, so the window only needs pywebview and pyobjc.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import logging
import shutil
import sys
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "OpenWarframe.App"
TITLE = "OpenWarframe"
POPOUT_TITLE = "OpenWarframe reward pick"
BACKGROUND = "#0a0f1d"


def icon_path() -> str:
    return str(resources.files("openwarframe.app").joinpath("static/icon.ico"))


def available() -> bool:
    """True when the native window can be used on this computer."""
    if sys.platform == "darwin":
        try:
            import webview  # noqa: F401
            from webview.platforms import cocoa  # noqa: F401

            return True
        except Exception as exc:  # noqa: BLE001
            log.info("native window not available: %s", exc)
            return False
    if sys.platform != "win32":
        return False
    try:
        import webview  # noqa: F401
        from webview.platforms import winforms

        return bool(winforms.is_chromium)
    except Exception as exc:  # noqa: BLE001 - any failure means: use the browser window
        log.info("native window not available: %s", exc)
        return False


def relaunch_command() -> str:
    """The command Windows runs when the pinned taskbar button is clicked."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    launcher = shutil.which("openwarframe-app")
    if launcher:
        return f'"{launcher}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" -m openwarframe.app'


# -- taskbar identity (Win32) -----------------------------------------------------------


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    # 8-byte header and a 16-byte union; only the string member (VT_LPWSTR) is used
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("r1", ctypes.c_ushort),
        ("r2", ctypes.c_ushort),
        ("r3", ctypes.c_ushort),
        ("pwszVal", ctypes.c_void_p),
        ("pad", ctypes.c_void_p),
    ]


_VT_LPWSTR = 31
_IID_IPROPERTYSTORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_FMTID_APPUSERMODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
# System.AppUserModel.* property ids
_PID_RELAUNCH_COMMAND = 2
_PID_RELAUNCH_ICON = 3
_PID_RELAUNCH_NAME = 4
_PID_ID = 5


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def set_process_app_id() -> bool:
    """Give this process its own taskbar group. Call before any window exists."""
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_ID))
        return True
    except (AttributeError, OSError) as exc:
        log.info("could not set the app id: %s", exc)
        return False


def set_window_identity(hwnd: int, command: str, icon: str, name: str = TITLE) -> bool:
    """Tag a window so the taskbar groups it as OpenWarframe and a pin relaunches it."""
    if sys.platform != "win32" or not hwnd:
        return False
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    store = ctypes.c_void_p()
    shell32 = ctypes.windll.shell32
    shell32.SHGetPropertyStoreForWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    hr = shell32.SHGetPropertyStoreForWindow(
        ctypes.c_void_p(hwnd), ctypes.byref(_guid(_IID_IPROPERTYSTORE)), ctypes.byref(store)
    )
    if hr != 0 or not store:
        log.info("no property store for window %s (0x%08x)", hwnd, hr & 0xFFFFFFFF)
        return False
    vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    set_value = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)
    )(vtbl[6])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    fmtid = _guid(_FMTID_APPUSERMODEL)
    ok = True
    keep = []  # the strings must stay alive until SetValue has copied them
    try:
        # the window's app id must be set for the relaunch values to count
        for pid, value in (
            (_PID_ID, APP_ID),
            (_PID_RELAUNCH_COMMAND, command),
            (_PID_RELAUNCH_ICON, f"{icon},0"),
            (_PID_RELAUNCH_NAME, name),
        ):
            buf = ctypes.create_unicode_buffer(value)
            keep.append(buf)
            pv = _PROPVARIANT(vt=_VT_LPWSTR, pwszVal=ctypes.cast(buf, ctypes.c_void_p))
            key = _PROPERTYKEY(fmtid, pid)
            hr = set_value(store, ctypes.byref(key), ctypes.byref(pv))
            if hr != 0:
                ok = False
                log.info("setting taskbar property %s failed (0x%08x)", pid, hr & 0xFFFFFFFF)
    finally:
        release(store)
    return ok


def bring_to_front(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    user32 = ctypes.windll.user32
    SW_RESTORE = 9  # noqa: N806
    if user32.IsIconic(ctypes.c_void_p(hwnd)):
        user32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))


def allow_other_process_to_focus() -> None:
    """A second launch is in the foreground; let the running app take focus from it."""
    if sys.platform == "win32":
        ASFW_ANY = -1  # noqa: N806
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)


def _hwnd(window) -> int:
    try:
        return int(window.native.Handle.ToInt64())
    except Exception:  # noqa: BLE001
        return 0


# -- the windows ------------------------------------------------------------------------


class NativeWindows:
    """The main window and the optional always-on-top reward pop-out."""

    def __init__(self, base_url: str, storage: Path) -> None:
        self.base_url = base_url
        self.storage = storage
        self.main = None
        self.popout = None

    def run(self) -> None:
        """Open the main window and block until it is closed."""
        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True  # Export CSV
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        set_process_app_id()
        self.main = webview.create_window(
            TITLE,
            self.base_url,
            width=1360,
            height=900,
            min_size=(900, 600),
            background_color=BACKGROUND,
            text_select=True,
        )
        self.main.events.shown += self._tag(self.main)
        self.main.events.closed += self._close_others
        self.storage.mkdir(parents=True, exist_ok=True)
        webview.start(
            gui="cocoa" if sys.platform == "darwin" else "edgechromium",
            private_mode=False,  # keep the remembered tab and settings between runs
            storage_path=str(self.storage),
            icon=icon_path(),
        )

    def _tag(self, window):
        def handler(*_):
            ok = set_window_identity(_hwnd(window), relaunch_command(), icon_path())
            log.info("taskbar identity %s", "set" if ok else "not set")

        return handler

    def _close_others(self, *_):
        if self.popout is not None:
            with contextlib.suppress(Exception):
                self.popout.destroy()

    def raise_main(self) -> bool:
        if self.main is None:
            return False
        with contextlib.suppress(Exception):
            self.main.restore()
            self.main.show()
        bring_to_front(_hwnd(self.main))
        return True

    def open_popout(self) -> None:
        import webview

        if self.popout is not None:
            try:
                self.popout.restore()
                self.popout.show()
                return
            except Exception:  # noqa: BLE001 - it was closed; make a new one
                self.popout = None
        g = self._popout_geometry()
        self.popout = webview.create_window(
            POPOUT_TITLE,
            self.base_url + "mini",
            width=g["width"],
            height=g["height"],
            x=g["x"],
            y=g["y"],
            on_top=True,
            background_color=BACKGROUND,
        )
        self.popout.events.shown += self._tag(self.popout)
        self.popout.events.closed += self._popout_closed
        # remember where the player put it (often a second monitor) for next time
        with contextlib.suppress(Exception):
            self.popout.events.moved += lambda x, y: self._save_popout(x=x, y=y)
            self.popout.events.resized += lambda w, h: self._save_popout(width=w, height=h)

    @property
    def _geometry_path(self) -> Path:
        return self.storage.parent / "popout-window.json"

    def _popout_geometry(self) -> dict:
        g = {"width": 440, "height": 300, "x": 40, "y": 40}
        try:
            saved = json.loads(self._geometry_path.read_text(encoding="utf-8"))
            g.update({k: int(v) for k, v in saved.items() if k in g and isinstance(v, int | float)})
        except (OSError, ValueError):
            pass
        g["width"], g["height"] = max(300, g["width"]), max(200, g["height"])
        return g

    def _save_popout(self, **changes) -> None:
        from ..fsutil import atomic_write_text

        g = self._popout_geometry()
        g.update({k: int(v) for k, v in changes.items() if v is not None})
        with contextlib.suppress(OSError):
            atomic_write_text(self._geometry_path, json.dumps(g))

    def _popout_closed(self, *_):
        self.popout = None
