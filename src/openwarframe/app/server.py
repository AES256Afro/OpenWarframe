"""A tiny local web server that hosts the desktop app.

It listens on 127.0.0.1 only, on a free port. On Windows the page opens in OpenWarframe's
own WebView2 window (window.py), which has its own taskbar button; the app stops when it is
closed. Otherwise, or with OPENWARFRAME_BROWSER_WINDOW set, it opens in a Chrome or Edge
"app" window (no tabs, no address bar) and stops a short while after that window is closed.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from ..config import Settings, load_settings

log = logging.getLogger(__name__)
IDLE_SECONDS = 45


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.cache: dict | None = None
        self.cache_fp: tuple | None = None
        self.status = ""
        self.last_ping = time.time()
        self.prices: dict[str, dict] = {}
        from .rewards import RewardWatcher

        self.rewards = RewardWatcher(settings)
        self.windows = None  # NativeWindows when the app has its own window

    @property
    def inventory_path(self) -> Path:
        return self.settings.home / "inventory.json"

    def _fingerprint(self) -> tuple:
        """Changes whenever a newer snapshot, inventory or game database lands on disk."""
        s = self.settings

        def stamp(p: Path):
            try:
                st = p.stat()
                return (st.st_mtime_ns, st.st_size)
            except OSError:
                return None

        snaps = sorted(s.snapshots_dir.glob("*.json")) if s.snapshots_dir.exists() else []
        latest = snaps[-1] if snaps else None
        return (
            latest.name if latest else None,
            stamp(latest) if latest else None,
            stamp(self.inventory_path),
            stamp(s.codex_path),
        )

    def ensure_codex(self) -> str | None:
        """Build or update the game database when it is missing or older than this code.

        Returns an error message, or None when the database is ready.
        """
        from ..codex import codex_schema_version, update_codex
        from ..codex.schema import SCHEMA_VERSION

        have = codex_schema_version(self.settings.codex_path)
        if have >= SCHEMA_VERSION:
            return None
        self.status = "Updating the game database (first run after an update can take a minute)…"
        try:
            update_codex(self.settings)
        except PermissionError:
            return (
                "The game database is out of date but is in use by another OpenWarframe window. "
                "Close every OpenWarframe window, then open it again."
            )
        except Exception as exc:  # noqa: BLE001
            return f"The game database is out of date and could not be updated ({exc}). Check your internet connection."
        finally:
            self.status = ""
        return None

    def build(self, *, force: bool = False) -> dict:
        with self.lock:
            fp = self._fingerprint()
            if self.cache is not None and not force and fp == self.cache_fp:
                return self.cache
            problem = self.ensure_codex()
            if problem:
                return {"error": problem, "can_update": True}
            fp = self._fingerprint()  # the database may have just been replaced
            from ..account.store import SnapshotStore
            from ..account.sync import reparse
            from ..codex import Codex
            from ..inventory import load_inventory
            from ..report import build_report
            from .data import build_app_data

            s = self.settings
            if not s.codex_path.exists():
                return {"error": "No game database yet. Run: openwarframe codex update"}
            try:
                snap = SnapshotStore(s.snapshots_dir).load("latest")
            except FileNotFoundError:
                return {
                    "error": "Connect your Warframe account to get started."
                    if not s.account_id
                    else "Your profile has not been fetched yet.",
                    "setup": True,
                    "has_account": bool(s.account_id),
                }
            inv_error = None
            try:
                inv = load_inventory(self.inventory_path) if self.inventory_path.exists() else None
            except Exception as exc:  # noqa: BLE001 - shown in the app instead of silently ignored
                log.warning("inventory unreadable: %s", exc)
                inv, inv_error = (
                    None,
                    f"Your inventory file could not be read ({exc}). Get it from the game again.",
                )
            codex = Codex(s.codex_path)
            try:  # always close, so a failed build never leaves the database file locked
                report = build_report(reparse(snap, codex), codex)
                data = build_app_data(report, codex, inv)
            finally:
                codex.close()
            data["meta"]["inventory_error"] = inv_error
            self.cache, self.cache_fp = data, fp
            return self.cache

    def fetch_prices(self, ids: list[str], limit: int = 80, kind: str = "relics") -> dict:
        """Lowest and typical sell price on warframe.market for up to `limit` rows (cached 6 h)."""
        from ..http import CachedClient

        if kind not in ("relics", "sell", "mods", "pieces"):
            raise ValueError("unknown price list")
        data = self.build()
        if kind == "pieces":
            rows_ = [p for c in data.get("farm", {}).get("finish", []) for p in c["pieces"]]
        else:
            rows_ = data.get(kind, [])
        slugs = {r["id"]: r.get("slug") for r in rows_ if r.get("id")}
        client = CachedClient(self.settings.cache_dir)
        out: dict[str, dict] = {}
        try:
            for rid in ids[:limit]:
                slug = slugs.get(rid)
                if not slug:
                    continue
                if rid in self.prices:
                    out[rid] = self.prices[rid]
                    continue
                url = f"https://api.warframe.market/v2/orders/item/{slug}/top"
                cached = client.cached(url) is not None
                try:
                    top = client.get_json(url, max_age=6 * 3600).get("data", {})
                except Exception as exc:  # noqa: BLE001
                    log.warning("price for %s failed: %s", slug, exc)
                    continue
                sells = sorted(o["platinum"] for o in top.get("sell", []))[:5]
                buys = sorted((o["platinum"] for o in top.get("buy", [])), reverse=True)[:5]
                price = {
                    "low": sells[0] if sells else None,
                    "typical": sells[len(sells) // 2] if sells else None,
                    "buy": buys[0] if buys else None,
                }
                self.prices[rid] = out[rid] = price
                if not cached:
                    time.sleep(0.34)  # warframe.market asks for at most 3 requests a second
        finally:
            client.close()
        for r in rows_:
            if r.get("id") in self.prices:
                r["price"] = self.prices[r["id"]]["typical"]
        return out

    @property
    def session_ok(self) -> bool:
        return bool(self.settings.extra.get("session_reader_ok"))

    def grab(self, accept: bool) -> dict:
        """Read the game session and download the inventory. Needs consent once.

        On first run (no account set) the account ID the game is signed in to is saved and
        the profile is fetched too, so one click sets everything up.
        """
        from ..config import save_settings
        from ..sources.account import session

        if not session.SUPPORTED:
            raise session.SessionError(session.UNSUPPORTED_TEXT)
        if not self.session_ok:
            if not accept:
                return {"needs_consent": True, "risk": session.RISK_TEXT}
            self.settings.extra["session_reader_ok"] = True
            save_settings(self.settings)
        account, data = session.grab_session(self.settings.account_id)
        self._store_inventory(data)
        if not self.settings.account_id:
            self.settings.account_id = account
            save_settings(self.settings)
        if not self._has_snapshot():
            return self.sync()
        return self.build(force=True)

    def _has_snapshot(self) -> bool:
        d = self.settings.snapshots_dir
        return d.exists() and any(d.glob("*.json"))

    def set_account(self, body: bytes) -> dict:
        """Save an account ID typed into the app, then fetch that profile."""
        from ..config import save_settings
        from ..sources.account.profile import HOSTS, ProfileError, validate_account_id

        req = json.loads(body.decode("utf-8") or "{}")
        platform = str(req.get("platform") or "pc")
        if platform not in HOSTS:
            raise ValueError(f"Unknown platform {platform!r}.")
        try:
            account = validate_account_id(str(req.get("id", "")))
        except ProfileError:
            raise ValueError(
                "That is not an account ID. It is 24 characters long, using only digits and the letters a to f."
            ) from None
        if self.settings.account_id and self.settings.account_id != account and self.inventory_path.exists():
            self.inventory_path.unlink()  # that inventory belongs to the previous account
        self.settings.account_id, self.settings.platform = account, platform
        save_settings(self.settings)
        return self.sync()

    def live(self) -> dict:
        """World state matched against the account (cached about a minute)."""
        from ..codex import Codex
        from ..http import CachedClient
        from .live import build_live

        data = self.build()
        if "error" in data:
            return data
        codex = Codex(self.settings.codex_path)
        client = CachedClient(self.settings.cache_dir)
        try:
            return build_live(codex.conn, data, client)
        finally:
            client.close()
            codex.close()

    @property
    def prefs_path(self) -> Path:
        return self.settings.home / "app-prefs.json"

    def get_prefs(self) -> dict:
        try:
            data = json.loads(self.prefs_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_prefs(self, body: bytes) -> dict:
        """Goals, checklist ticks and comfort settings, kept in the data folder."""
        data = json.loads(body.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("preferences must be an object")
        allowed = {k: data[k] for k in ("goals", "checks", "settings", "skipped") if k in data}
        merged = {**self.get_prefs(), **allowed}
        tmp = self.prefs_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged), encoding="utf-8")
        tmp.replace(self.prefs_path)
        return merged

    def sync(self) -> dict:
        from ..account.sync import sync_profile

        sync_profile(self.settings)
        return self.build(force=True)

    def _store_inventory(self, data) -> None:
        from ..inventory import parse_inventory

        if isinstance(data, dict) and "InventoryJson" in data:
            raw = data["InventoryJson"]
            data = json.loads(raw) if isinstance(raw, str) else raw
        parse_inventory(data)  # validates
        self.inventory_path.write_text(json.dumps(data), encoding="utf-8")

    def save_inventory(self, body: bytes) -> dict:
        self._store_inventory(json.loads(body.decode("utf-8-sig")))
        return self.build(force=True)


def _page(name: str = "static/index.html") -> bytes:
    return resources.files("openwarframe.app").joinpath(name).read_bytes()


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console quiet
            log.debug(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            state.last_ping = time.time()
            if self.path in ("/", "/index.html"):
                self._send(200, _page(), "text/html; charset=utf-8")
            elif self.path == "/api/data":
                try:
                    self._json(state.build())
                except Exception as exc:  # noqa: BLE001 - show the real problem instead of a dropped connection
                    log.exception("building app data failed")
                    self._json(
                        {"error": f"OpenWarframe hit a problem loading your data: {exc}", "can_update": True}
                    )
            elif self.path == "/api/status":
                self._json({"status": state.status})
            elif self.path == "/api/live":
                try:
                    self._json(state.live())
                except Exception as exc:  # noqa: BLE001 - network trouble is shown in the app
                    self._json({"error": f"Could not load the world state: {exc}"})
            elif self.path == "/api/prefs":
                self._json(state.get_prefs())
            elif self.path == "/api/reward":
                self._json(state.rewards.status())
            elif self.path == "/mini":
                self._send(200, _page("static/mini.html"), "text/html; charset=utf-8")
            elif self.path == "/api/version":
                self._json({"version": repr(state._fingerprint())})
            elif self.path == "/api/ping":
                self._json({"ok": True})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802
            state.last_ping = time.time()
            if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                self._json({"error": "forbidden"}, 403)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            try:
                if self.path == "/api/sync":
                    self._json(state.sync())
                elif self.path == "/api/inventory":
                    self._json(state.save_inventory(body))
                elif self.path == "/api/inventory/grab":
                    req = json.loads(body.decode("utf-8") or "{}")
                    self._json(state.grab(bool(req.get("accept"))))
                elif self.path == "/api/prices":
                    req = json.loads(body.decode("utf-8") or "[]")
                    if isinstance(req, list):
                        req = {"ids": req, "kind": "relics"}
                    ids = [str(i) for i in req.get("ids", [])]
                    self._json(state.fetch_prices(ids, kind=str(req.get("kind", "relics"))))
                elif self.path == "/api/prefs":
                    self._json(state.save_prefs(body))
                elif self.path == "/api/reward/watch":
                    req = json.loads(body.decode("utf-8") or "{}")
                    on = bool(req.get("on"))
                    prefs = state.get_prefs()
                    settings_ = {**prefs.get("settings", {}), "reward_watch": on}
                    state.save_prefs(json.dumps({"settings": settings_}).encode())
                    self._json(state.rewards.start() if on else state.rewards.stop())
                elif self.path == "/api/reward/demo":
                    self._json(state.rewards.demo())
                elif self.path == "/api/reward/popout":
                    if state.windows is not None:
                        state.windows.open_popout()
                    else:
                        _open_popout(f"http://127.0.0.1:{self.server.server_port}/mini", state.settings)
                    self._json({"ok": True})
                elif self.path == "/api/raise":
                    # a second launch asks the running app to show its window
                    self._json({"native": bool(state.windows and state.windows.raise_main())})
                elif self.path == "/api/account":
                    self._json(state.set_account(body))
                elif self.path == "/api/codex/update":
                    from ..codex import update_codex

                    with state.lock:
                        update_codex(state.settings)
                    self._json(state.build(force=True))
                elif self.path == "/api/inventory/clear":
                    if state.inventory_path.exists():
                        state.inventory_path.unlink()
                    self._json(state.build(force=True))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:  # noqa: BLE001 - shown to the user in the app
                self._json({"error": str(exc)}, 400)

    return Handler


def _open_popout(url: str, settings: Settings) -> None:
    """Small always-on-top window that shows the latest reward pick."""
    from ..guide.documents import find_browser
    from .rewards import keep_on_top

    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return
    subprocess.Popen(  # noqa: S603
        [
            str(browser),
            f"--app={url}",
            f"--user-data-dir={settings.home / 'app-window'}",
            "--window-size=440,300",
            "--window-position=40,40",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    threading.Thread(target=keep_on_top, args=("OpenWarframe reward pick",), daemon=True).start()


def _open_window(url: str, settings: Settings) -> None:
    from ..guide.documents import find_browser

    browser = find_browser()
    if browser:
        profile = settings.home / "app-window"
        subprocess.Popen(  # noqa: S603
            [
                str(browser),
                f"--app={url}",
                f"--user-data-dir={profile}",
                "--window-size=1360,900",
                "--no-first-run",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        webbrowser.open(url)


def _running_instance(settings: Settings) -> int | None:
    """Port of an OpenWarframe server that is already running for this data folder."""
    import urllib.request

    lock = settings.home / "app.lock"
    try:
        port = int(json.loads(lock.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as r:
            return port if r.status == 200 else None
    except OSError:
        return None


def _raise_running(port: int) -> bool:
    """Ask a running app to bring its own window forward. False if it has none."""
    import urllib.request

    from .window import allow_other_process_to_focus

    allow_other_process_to_focus()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/raise", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return bool(json.loads(r.read()).get("native"))
    except (OSError, ValueError):
        return False


def run_app(
    *,
    port: int = 0,
    open_window: bool = True,
    settings: Settings | None = None,
    native: bool | None = None,
) -> None:
    """Start the local server and open the app.

    ``native``: use OpenWarframe's own window (None = when available on this PC), otherwise
    a Chrome or Edge app window that stops the server a while after it is closed.
    """
    settings = settings or load_settings()
    existing = _running_instance(settings) if open_window and not port else None
    if existing:
        # a second double-click: show the app that is already running instead of starting another
        if not _raise_running(existing):
            _open_window(f"http://127.0.0.1:{existing}/", settings)
        return
    state = AppState(settings)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    url = f"http://127.0.0.1:{server.server_port}/"
    lock = settings.home / "app.lock"
    if open_window:
        with contextlib.suppress(OSError):
            lock.write_text(json.dumps({"port": server.server_port, "pid": os.getpid()}), encoding="utf-8")
    print(f"OpenWarframe is running at {url}  (close the window to stop)")
    threading.Thread(target=state.build, daemon=True).start()  # warm the cache
    if state.get_prefs().get("settings", {}).get("reward_watch"):
        state.rewards.start()
    threading.Thread(target=server.serve_forever, name="app-server", daemon=True).start()
    try:
        if open_window and _use_native(native):
            if _run_native(url, state):
                return
            log.warning("own window failed to open; using a browser window instead")
        if open_window:
            _open_window(url, settings)
            # the browser window pings the server; stop a while after it is closed
            while time.time() - state.last_ping <= IDLE_SECONDS:
                time.sleep(5)
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        if open_window:
            try:
                if json.loads(lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                    lock.unlink()
            except (OSError, ValueError):
                pass


def _use_native(native: bool | None) -> bool:
    if native is False or os.environ.get("OPENWARFRAME_BROWSER_WINDOW"):
        return False
    from .window import available

    return available()


def _run_native(url: str, state: AppState) -> bool:
    """Run OpenWarframe's own window until it is closed. False if it could not open."""
    from .window import NativeWindows

    state.windows = NativeWindows(url, state.settings.home / "webview")
    try:
        state.windows.run()
    except Exception:  # noqa: BLE001 - fall back to the browser window
        log.exception("own window failed")
        state.windows = None
        return False
    return True
