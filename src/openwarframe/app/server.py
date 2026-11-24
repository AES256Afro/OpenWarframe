"""A tiny local web server that hosts the desktop app.

It listens on 127.0.0.1 only, on a free port, and opens the page in a Chrome or Edge
"app" window (no tabs, no address bar). Nothing is installed and nothing needs signing.
The server stops on its own a short while after the window is closed.
"""

from __future__ import annotations

import json
import logging
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
        self.last_ping = time.time()
        self.prices: dict[str, dict] = {}

    @property
    def inventory_path(self) -> Path:
        return self.settings.home / "inventory.json"

    def build(self, *, force: bool = False) -> dict:
        with self.lock:
            if self.cache is not None and not force:
                return self.cache
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
                return {"error": "No snapshot yet. Click Refresh profile, or run: openwarframe sync"}
            codex = Codex(s.codex_path)
            try:
                inv = load_inventory(self.inventory_path) if self.inventory_path.exists() else None
            except (ValueError, OSError) as exc:
                log.warning("inventory unreadable: %s", exc)
                inv = None
            report = build_report(reparse(snap, codex), codex)
            self.cache = build_app_data(report, codex, inv)
            codex.close()
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
        """Read the game session and download the inventory. Needs consent once."""
        from ..config import save_settings
        from ..sources.account.session import RISK_TEXT, grab_inventory

        if not self.session_ok:
            if not accept:
                return {"needs_consent": True, "risk": RISK_TEXT}
            self.settings.extra["session_reader_ok"] = True
            save_settings(self.settings)
        data = grab_inventory(self.settings.account_id)
        return self.save_inventory(json.dumps(data).encode("utf-8"))

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

    def sync(self) -> dict:
        from ..account.sync import sync_profile

        sync_profile(self.settings)
        return self.build(force=True)

    def save_inventory(self, body: bytes) -> dict:
        from ..inventory import parse_inventory

        data = json.loads(body.decode("utf-8-sig"))
        if isinstance(data, dict) and "InventoryJson" in data:
            raw = data["InventoryJson"]
            data = json.loads(raw) if isinstance(raw, str) else raw
        parse_inventory(data)  # validates
        self.inventory_path.write_text(json.dumps(data), encoding="utf-8")
        return self.build(force=True)


def _page() -> bytes:
    return resources.files("openwarframe.app").joinpath("static/index.html").read_bytes()


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
                self._json(state.build())
            elif self.path == "/api/live":
                try:
                    self._json(state.live())
                except Exception as exc:  # noqa: BLE001 - network trouble is shown in the app
                    self._json({"error": f"Could not load the world state: {exc}"})
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
                elif self.path == "/api/inventory/clear":
                    if state.inventory_path.exists():
                        state.inventory_path.unlink()
                    self._json(state.build(force=True))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:  # noqa: BLE001 - shown to the user in the app
                self._json({"error": str(exc)}, 400)

    return Handler


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


def run_app(*, port: int = 0, open_window: bool = True, settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    state = AppState(settings)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"OpenWarframe is running at {url}  (close the window to stop)")
    threading.Thread(target=state.build, daemon=True).start()  # warm the cache
    if open_window:
        _open_window(url, settings)

    def watchdog():
        while True:
            time.sleep(5)
            if time.time() - state.last_ping > IDLE_SECONDS:
                server.shutdown()
                return

    if open_window:
        threading.Thread(target=watchdog, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
