"""A tiny local web server that hosts the desktop app.

It listens on 127.0.0.1 only, on a free port. On Windows the page opens in OpenWarframe's
own WebView2 window (window.py), which has its own taskbar button; the app stops when it is
closed. Otherwise, or with OPENWARFRAME_BROWSER_WINDOW set, it opens in a Chrome or Edge
"app" window (no tabs, no address bar) and stops a short while after that window is closed.
"""

from __future__ import annotations

import contextlib
import functools
import gzip
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..config import Settings, load_settings
from ..fsutil import atomic_write_text

log = logging.getLogger(__name__)
# The browser-window page pings every 10 s, but browsers slow timers in hidden or minimised
# windows to about once a minute, so the server waits well past that before stopping.
IDLE_SECONDS = 150
PRICE_MAX_AGE = 6 * 3600  # market prices are re-checked after six hours, even in a long session
LIVE_MAX_AGE = 45  # seconds the Live tab's answer is reused (sooner when EE.log changes)
GZIP_MIN = 1024  # smaller responses are sent as they are
MAX_NAME_IDS = 500  # /api/names answers at most this many ids per request
PROFILE_REFRESH_HOURS = 24  # the profile is fetched again on open once it is this old
RELEASES_API = "https://api.github.com/repos/AES256Afro/OpenWarframe/releases/latest"
MAX_BODY = 64 << 20
SERVER_SETTINGS = (
    "reward_watch",
    "save_recordings",
    "capture_hotkey",
    "game_language",
    "names_lang",
)  # changed by their own endpoints, not the page  # an inventory file is a few MB; anything this big is not one of ours

# The page only ever talks to this server. These headers stop other sites from framing it
# (clickjacking the consent button) and stop injected markup from loading or sending anything.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.cache: dict | None = None
        self.cache_fp: tuple | None = None
        self.status = ""
        self.last_ping = time.monotonic()
        self.prices: dict[str, dict] = {}  # id -> price, with "_at" (time.time()) for expiry
        self.codex_warning: str | None = None
        self.update_info: dict | None = None
        self.release: dict | None = None  # the newest GitHub release, for the in-app update
        self.updating = False
        from .rewards import RewardWatcher

        prefs = self.get_prefs().get("settings", {})
        self.rewards = RewardWatcher(
            settings,
            save_recordings=bool(prefs.get("save_recordings")),
            language=str(prefs.get("game_language") or "en"),
        )
        from .hotkey import GlobalHotkey

        self.hotkey = GlobalHotkey()
        self.prefs_lock = threading.Lock()
        self.windows = None  # NativeWindows when the app has its own window
        self._live: tuple[tuple, float, dict] | None = None  # (key, time.monotonic(), answer)

    @property
    def inventory_path(self) -> Path:
        return self.settings.inventory_path

    def _fingerprint(self) -> tuple:
        """Changes whenever a newer snapshot, inventory or game database lands on disk."""
        s = self.settings

        def stamp(p: Path):
            try:
                st = p.stat()
                return (st.st_mtime_ns, st.st_size)
            except OSError:
                return None

        latest = self._latest_snapshot()
        return (
            latest.name if latest else None,
            stamp(latest) if latest else None,
            stamp(self.inventory_path),
            stamp(s.codex_path),
            stamp(s.home / "names" / f"{self.names_lang}.json"),  # names refreshed or language changed
            self.names_lang,
        )

    def _latest_snapshot(self) -> Path | None:
        """Newest snapshot file: one quick scan of the folder, no sorting.

        Snapshot names are UTC timestamps, so the largest name is the newest. Caching on the
        folder's modified time missed new files on Windows, where that time can lag behind.
        """
        try:
            with os.scandir(self.settings.snapshots_dir) as it:
                newest = max((e.name for e in it if e.name.endswith(".json") and e.is_file()), default=None)
        except OSError:
            return None
        return self.settings.snapshots_dir / newest if newest else None

    def ensure_codex(self) -> str | None:
        """Build or update the game database when it is missing or older than this code.

        Returns an error message, or None when the database is ready.
        """
        from ..codex import codex_schema_version, update_codex
        from ..codex.schema import READABLE_FROM, SCHEMA_VERSION

        have = codex_schema_version(self.settings.codex_path)
        if have >= SCHEMA_VERSION:
            return None
        self.status = "Updating the game database (first run after an update can take a minute)…"
        try:
            update_codex(self.settings)
            self.codex_warning = None
        except PermissionError:
            return (
                "The game database is out of date but is in use by another OpenWarframe window. "
                "Close every OpenWarframe window, then open it again."
            )
        except Exception as exc:  # noqa: BLE001
            if have >= READABLE_FROM:
                # offline after an update: the old database still works, so keep going with it
                self.codex_warning = (
                    f"The game data could not be updated ({exc}), so you are seeing the data you already "
                    "had. Some newer details may be missing until it updates."
                )
                log.warning("codex update failed, using the existing database: %s", exc)
                return None
            if have > 0:
                return (
                    f"The game database is out of date and could not be updated ({exc}). "
                    "Check your internet connection."
                )
            return f"The game database could not be downloaded ({exc}). Check your internet connection."
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
                parsed = reparse(snap, codex)
                report = build_report(parsed, codex, inventory=inv)
                data = build_app_data(report, codex, inv)
                data["meta"]["standing_left"] = dict(parsed.progression.daily_affiliations)
                tr = self._translator(codex.conn)
                if tr:
                    tr.strings({k: v for k, v in data.items() if k != "meta"})
                data["meta"]["names_lang"] = tr.lang if tr else "en"
                from ..codex.languages import LANGUAGES

                data["meta"]["languages"] = [[c, label] for c, (label, _) in LANGUAGES.items()]
            finally:
                codex.close()
            data["meta"]["inventory_error"] = inv_error
            self.cache, self.cache_fp = data, fp
            return self.cache

    def fetch_prices(self, ids: list[str], limit: int = 80, kind: str = "relics") -> dict:
        """Lowest and typical sell price on warframe.market for up to `limit` rows (cached 6 h)."""
        from ..http import CachedClient
        from ..sources.static.market import top_prices

        if kind not in ("relics", "sell", "mods", "pieces"):
            raise ValueError("unknown price list")
        data = self.build()
        if kind == "pieces":
            rows_ = [p for c in data.get("farm", {}).get("finish", []) for p in c["pieces"]]
        else:
            rows_ = data.get(kind, [])
        slugs = {r["id"]: r.get("slug") for r in rows_ if r.get("id")}
        bases = self._price_bases({s for s in slugs.values() if s})
        client = CachedClient(self.settings.cache_dir)
        out: dict[str, dict] = {}
        try:
            for rid in ids[:limit]:
                slug = slugs.get(rid)
                if not slug:
                    continue
                if rid in self.prices and time.time() - self.prices[rid].get("_at", 0) < PRICE_MAX_AGE:
                    out[rid] = self.prices[rid]
                    continue
                try:
                    price = top_prices(client, slug, **bases.get(slug, {}))
                except Exception as exc:  # noqa: BLE001
                    log.warning("price for %s failed: %s", slug, exc)
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status == 429:  # rate limited: return what we have instead of waiting minutes
                        break
                    continue
                finally:
                    if client.last_was_network:  # failed or stale, a request still went out
                        time.sleep(0.34)  # warframe.market asks for at most 3 requests a second
                price["_at"] = time.time()
                self.prices[rid] = out[rid] = price
        finally:
            client.close()
        for r in rows_:
            if r.get("id") in self.prices:
                r["price"] = self.prices[r["id"]]["typical"]
        return out

    def _price_bases(self, slugs: set[str]) -> dict[str, dict]:
        """slug -> top_prices filter: mods and arcanes at rank 0, relics Intact."""
        import sqlite3

        from ..sources.static.market import price_basis

        if not slugs or not self.settings.codex_path.exists():
            return {}
        out: dict[str, dict] = {}
        try:
            conn = sqlite3.connect(f"file:{self.settings.codex_path.as_posix()}?mode=ro", uri=True)
            try:
                for slug, tags in conn.execute("SELECT slug, tags FROM market_item"):
                    if slug in slugs:
                        try:
                            out[slug] = price_basis(json.loads(tags or "[]"))
                        except ValueError:
                            continue
            finally:
                conn.close()
        except sqlite3.Error as exc:
            log.warning("could not read market tags: %s", exc)
        return out

    def names(self, ids: list[str]) -> dict[str, str]:
        """Display names for uniqueNames (goals saved by id), from the game database."""
        from ..codex import Codex

        ids = [i for i in dict.fromkeys(ids) if i][:MAX_NAME_IDS]
        if not ids or not self.settings.codex_path.exists():
            return {}
        codex = Codex(self.settings.codex_path)
        try:
            return {i: codex.display_name(i) for i in ids}
        finally:
            codex.close()

    def how_to_get(self, uid: str) -> dict:
        """Every known way to get one item, its blueprint and parts (for the item details)."""
        from ..codex import Codex
        from ..codex.howto import how_to_get
        from ..inventory import load_inventory

        if not uid or not self.settings.codex_path.exists():
            return {"error": "No game data yet."}
        owned: dict[str, int] = {}
        if self.inventory_path.exists():
            with contextlib.suppress(Exception):  # a damaged inventory only loses the "you have" marks
                owned = {r: sum(c.values()) for r, c in load_inventory(self.inventory_path).relics.items()}
        with Codex(self.settings.codex_path) as codex:
            if codex.item(uid) is None:
                return {"error": "That item isn't in the game data."}
            answer = how_to_get(codex, uid, owned)
            tr = self._translator(codex.conn)
            return tr.strings(answer) if tr else answer

    def capabilities(self) -> dict:
        """What this computer and account can do, so the page never offers the impossible.

        ``game_here``: the account plays on PC, so the game can run on this computer (a
        console or mobile account can't use the game log, the inventory reader or the reward
        helper). ``grab``: reading the inventory from the running game works here (Windows and
        a PC account). ``ocr``: text recognition for the reward helper.
        """
        from ..sources.account import session
        from ..sources.account.profile import PLATFORM_LABELS
        from .rewards import ocr_available

        game_here = (self.settings.platform or "pc") == "pc"
        return {
            "game_here": game_here,
            "grab": bool(session.SUPPORTED and game_here),
            "ocr": bool(game_here and ocr_available()),
            "platform_label": PLATFORM_LABELS.get(self.settings.platform or "pc", self.settings.platform),
            "os": "mac"
            if sys.platform == "darwin"
            else "windows"
            if sys.platform == "win32"
            else "linux"
            if sys.platform.startswith("linux")
            else "other",
        }

    def apply_hotkey(self) -> dict:
        """Register the "read the reward screen now" key from the settings (default Ctrl+Alt+F9).

        Only where the reward helper can work: a PC account with text recognition here.
        """
        from .hotkey import DEFAULT

        spec = self.get_prefs().get("settings", {}).get("capture_hotkey", DEFAULT)
        caps = self.capabilities()
        if not (caps["game_here"] and caps["ocr"]):
            spec = None
        return self.hotkey.start(spec, lambda: self.rewards.capture_now("hotkey"))

    def set_game_language(self, lang: str) -> dict:
        """The game client's language: reward names are read in it. Downloads its names once."""
        from ..codex.languages import LANGUAGES, load_names
        from ..http import CachedClient

        if lang not in LANGUAGES:
            return {**self.reward_status(), "error": f"Unknown language {lang!r}."}
        if lang != "en":
            client = CachedClient(self.settings.cache_dir)
            try:
                names = load_names(self.settings.home, lang, client)
            finally:
                client.close()
            if not names:
                return {
                    **self.reward_status(),
                    "error": f"Could not download the {LANGUAGES[lang][0]} item names. Check your connection.",
                }
        self.save_prefs(json.dumps({"settings": {"game_language": lang}}).encode())
        self.rewards.language = lang
        return self.reward_status()

    def refresh_names(self) -> None:
        """After a game-data update: the chosen language's names, newly built if DE's changed."""
        from ..codex.languages import load_names
        from ..http import CachedClient

        lang = self.rewards.language
        if lang == "en":
            return
        client = CachedClient(self.settings.cache_dir)
        try:
            load_names(self.settings.home, lang, client, refresh=True)
        finally:
            client.close()

    @property
    def names_lang(self) -> str:
        return str(self.get_prefs().get("settings", {}).get("names_lang") or "en")

    def _translator(self, conn):
        from ..codex.translate import translator

        return translator(self.settings.home, conn, self.names_lang)

    def build_for(
        self,
        uid: str,
        *,
        target: str | None,
        owned_only: bool,
        stacks: bool,
        level: str = "sp",
        stripped: bool = False,
    ) -> dict:
        """A suggested mod build for one gun (builds.search)."""
        from ..builds.search import suggest
        from ..builds.weapons import NotAGun
        from ..codex import Codex
        from ..inventory import load_inventory

        if not uid or not self.settings.codex_path.exists():
            return {"error": "No game data yet."}
        owned = None
        if owned_only and self.inventory_path.exists():
            with contextlib.suppress(Exception):
                inv = load_inventory(self.inventory_path)
                owned = {u: max(m.get("ranks") or [0]) for u, m in inv.mods.items()}
        with Codex(self.settings.codex_path) as codex:
            try:
                b = suggest(
                    codex.conn, uid, target=target, owned=owned, stacks=stacks, level=level, stripped=stripped
                )
            except NotAGun as exc:
                return {"error": str(exc)}
            tr = self._translator(codex.conn)
            if tr:  # mod and weapon names in the chosen language
                for m in b["mods"]:
                    m["name"] = tr.by_id(m["id"], m["name"])
                if b.get("upgrade"):
                    b["upgrade"]["name"] = tr.by_name(b["upgrade"]["name"])
        return b

    def frame_build_for(
        self, uid: str, *, abilities: list[int] | None, survivability: str, owned_only: bool
    ) -> dict:
        """A suggested mod build for one Warframe (builds.frames)."""
        from ..builds.frames import NotAFrame, suggest_frame
        from ..codex import Codex
        from ..inventory import load_inventory

        if not uid or not self.settings.codex_path.exists():
            return {"error": "No game data yet."}
        owned = None
        if owned_only and self.inventory_path.exists():
            with contextlib.suppress(Exception):
                inv = load_inventory(self.inventory_path)
                owned = {u: max(m.get("ranks") or [0]) for u, m in inv.mods.items()}
        with Codex(self.settings.codex_path) as codex:
            try:
                b = suggest_frame(
                    codex.conn, uid, abilities=abilities, survivability=survivability, owned=owned
                )
            except NotAFrame as exc:
                return {"error": str(exc)}
            tr = self._translator(codex.conn)
            if tr:
                for m in b["mods"]:
                    m["name"] = tr.by_id(m["id"], m["name"])
        return b

    def set_names_lang(self, lang: str) -> dict:
        """Show item names in ``lang`` in the app and exports. Downloads its names once."""
        from ..codex.languages import LANGUAGES, load_names
        from ..http import CachedClient

        if lang not in LANGUAGES:
            return {"error": f"Unknown language {lang!r}."}
        if lang != "en":
            client = CachedClient(self.settings.cache_dir)
            try:
                names = load_names(self.settings.home, lang, client)
            finally:
                client.close()
            if not names:
                return {
                    "error": f"Could not download the {LANGUAGES[lang][0]} item names. Check your connection."
                }
        self.save_prefs(json.dumps({"settings": {"names_lang": lang}}).encode())
        with self.lock:
            self.cache = None  # build again with the new names
        self._live = None
        return self.build(force=True)

    def reward_status(self) -> dict:
        from ..codex.languages import LANGUAGES

        return {
            **self.rewards.status(),
            "hotkey": self.hotkey.describe(),
            "languages": [[code, label] for code, (label, _) in LANGUAGES.items()],
        }

    # -- freshness -------------------------------------------------------------------
    def profile_age_hours(self) -> float | None:
        """How old the newest profile snapshot is, from its file name (UTC), or None."""
        checked = self.profile_checked()
        latest = self._latest_snapshot()
        taken = None
        if latest:
            try:
                taken = datetime.strptime(latest.stem, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
            except ValueError:
                taken = None
        newest = max((t for t in (taken, checked) if t is not None), default=None)
        return None if newest is None else (datetime.now(UTC) - newest).total_seconds() / 3600

    def profile_checked(self) -> datetime | None:
        """When the profile was last fetched, changed or not."""
        from ..account.sync import profile_checked_path

        try:
            return datetime.fromtimestamp(profile_checked_path(self.settings).stat().st_mtime, tz=UTC)
        except OSError:
            return None

    def refresh_on_open(self) -> None:
        """Warm the cache, and fetch the profile again when it is more than a day old.

        A player coming back after a long break should see where they are now, not where
        they were. Failures (offline) are only logged: the app works with what it has.
        """
        age = self.profile_age_hours()
        if self.settings.account_id and age is not None and age > PROFILE_REFRESH_HOURS:
            self.status = "Fetching your latest profile…"
            try:
                self.sync()
                return
            except Exception as exc:  # noqa: BLE001
                log.info("profile refresh on open failed: %s", exc)
            finally:
                self.status = ""
        self.build()

    def check_for_update(self) -> dict:
        """Is a newer OpenWarframe released? Asks GitHub at most once a day; can be turned off."""
        from .. import __version__
        from ..http import CachedClient

        if self.get_prefs().get("settings", {}).get("check_updates") is False:
            return {"current": __version__, "disabled": True}
        if self.update_info is not None:
            return self.update_info
        client = CachedClient(self.settings.cache_dir, timeout=8, retries=1)
        try:
            rel = client.get_json(RELEASES_API, max_age=24 * 3600)
        except Exception as exc:  # noqa: BLE001 - offline: just don't show anything
            log.info("update check failed: %s", exc)
            return {"current": __version__, "error": True}
        finally:
            client.close()
        from .updater import install_kind, pick_asset

        tag = str(rel.get("tag_name") or "")
        kind = install_kind()
        info = {
            "current": __version__,
            "latest": tag.lstrip("v"),
            "newer": _version_tuple(tag) > _version_tuple(__version__),
            "url": rel.get("html_url") or "https://github.com/AES256Afro/OpenWarframe/releases/latest",
            "kind": kind,
            # the app can download and install this release itself
            "can_install": bool(pick_asset(rel, kind)),
        }
        self.release = rel
        self.update_info = info
        return info

    def install_update(self) -> dict:
        """Download the newer release for this install, start installing it, then quit.

        The installer (or the swap script) starts the new version when it is done.
        """
        from .updater import UpdateError, download, launch

        info = self.check_for_update()
        if not info.get("newer"):
            return {"error": "You already have the newest version."}
        rel = self.release
        if not rel or not info.get("can_install"):
            from .updater import SOURCE_HINT

            return {
                "error": SOURCE_HINT
                if info.get("kind") == "source"
                else "Download it from the release page.",
                "url": info.get("url"),
            }
        with self.lock:
            if self.updating:
                return {"error": "An update is already being installed."}
            self.updating = True
        try:
            file = download(rel, info["kind"], self.settings.home / "updates")
            launch(info["kind"], file)
        except (UpdateError, OSError) as exc:
            self.updating = False
            log.warning("update failed: %s", exc)
            return {"error": str(exc), "url": info.get("url")}
        threading.Timer(1.5, self._quit_for_update).start()
        return {"ok": True, "latest": info["latest"]}

    def _quit_for_update(self) -> None:
        """Quit at once so the installer can replace our files (the lock file goes too)."""
        lock = self.settings.home / "app.lock"
        try:
            if json.loads(lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                lock.unlink()
        except (OSError, ValueError):
            pass
        os._exit(0)

    def export(self, body: bytes) -> dict:
        """Write the account exports (Excel, dashboard, guide...) like `openwarframe export`."""
        from ..account.store import SnapshotStore
        from ..account.sync import reparse
        from ..codex import Codex
        from ..exports import run_exports
        from ..exports.extras import export_folder, gather_extras
        from ..inventory import load_inventory
        from ..report import build_report

        req = json.loads(body.decode("utf-8") or "{}")
        formats = [str(f) for f in req.get("formats") or ["xlsx", "dashboard", "guide", "json", "csv"]]
        s = self.settings
        inv = None
        if s.inventory_path.exists():
            with contextlib.suppress(Exception):
                inv = load_inventory(s.inventory_path)
        store = SnapshotStore(s.snapshots_dir)
        snap = store.load("latest")
        with Codex(s.codex_path) as codex:
            parsed = reparse(snap, codex)
            report = build_report(parsed, codex, inventory=inv)
            extras = gather_extras(s, store, parsed, codex)
            tr = self._translator(codex.conn)
        folder = export_folder(s, snap, share=False)
        results = run_exports(
            report,
            folder,
            formats,
            guide_pdf=bool(req.get("pdf", True)),
            guide_docx=True,
            extras=extras,
            translator=tr,
        )
        with contextlib.suppress(OSError):
            atomic_write_text(s.exports_dir / "LATEST.txt", str(folder.resolve()) + "\n")
        return {
            "folder": str(folder),
            "files": [{"format": r.format, "path": str(r.path), "detail": r.detail} for r in results],
        }

    def open_folder(self, body: bytes) -> dict:
        """Show an export folder in Finder or Explorer. Only folders under the exports folder."""
        req = json.loads(body.decode("utf-8") or "{}")
        target = Path(str(req.get("folder", ""))).resolve()
        root = self.settings.exports_dir.resolve()
        if root not in (target, *target.parents) or not target.is_dir():
            raise ValueError("Only export folders can be opened.")
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])  # noqa: S603
        return {"ok": True}

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
        if not self.settings.account_id:
            # set the account first: the inventory is stored in that account's folder
            self.settings.account_id = account
            save_settings(self.settings)
        self._store_inventory(data)
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
        # fetch the new profile before saving anything: a typo or a network error leaves the
        # current account as it was. Each account keeps its own snapshots and inventory.
        from dataclasses import replace

        from ..account.sync import sync_profile

        sync_profile(replace(self.settings, account_id=account, platform=platform))
        self.settings.account_id, self.settings.platform = account, platform
        save_settings(self.settings)
        # an inventory loaded before the account was set sits in the data folder: move it in
        from ..config import migrate_to_account_folders

        migrate_to_account_folders(self.settings)
        return self.build(force=True)

    def live(self, force: bool = False) -> dict:
        """World state matched against the account (cached about LIVE_MAX_AGE seconds).

        Built again sooner when the account data or the game log changes, so "you are
        here" follows the game without a minute's delay.
        """
        from ..codex import Codex
        from ..http import CachedClient
        from ..live.eelog import default_log_path
        from .live import build_live

        data = self.build()
        if "error" in data:
            return data
        try:
            st = default_log_path().stat()
            log_stamp = (st.st_mtime_ns, st.st_size)
        except (OSError, RuntimeError):
            log_stamp = None
        key = (id(data), self.cache_fp, log_stamp)
        cached = self._live
        if not force and cached and cached[0] == key and time.monotonic() - cached[1] < LIVE_MAX_AGE:
            return cached[2]
        codex = Codex(self.settings.codex_path)
        client = CachedClient(self.settings.cache_dir)
        try:
            answer = build_live(codex.conn, data, client)
            tr = self._translator(codex.conn)
            if tr:
                tr.strings(answer)
        finally:
            client.close()
            codex.close()
        self._live = (key, time.monotonic(), answer)
        return answer

    @property
    def prefs_path(self) -> Path:
        return self.settings.home / "app-prefs.json"

    def get_prefs(self) -> dict:
        """Saved goals, ticks and settings, each the right type even if the file was damaged."""
        try:
            data = json.loads(self.prefs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        shapes = {"goals": list, "checks": dict, "settings": dict, "skipped": dict, "views": dict}
        return {k: v for k, v in data.items() if k not in shapes or isinstance(v, shapes[k])}

    def save_prefs(self, body: bytes, *, from_page: bool = False) -> dict:
        """Goals, checklist ticks and comfort settings, kept in the data folder.

        ``from_page``: the page's copy of the settings can be stale for the settings the server
        changes itself (reward watching, saving screens), so those are never taken from it.
        """
        data = json.loads(body.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("preferences must be an object")
        if "settings" in data and not isinstance(data["settings"], dict):
            raise ValueError("settings must be an object")
        allowed = {
            k: data[k] for k in ("goals", "checks", "settings", "skipped", "views", "session") if k in data
        }
        if from_page and "settings" in allowed:
            allowed["settings"] = {k: v for k, v in allowed["settings"].items() if k not in SERVER_SETTINGS}
        with self.prefs_lock:  # read-merge-write must not interleave between request threads
            current = self.get_prefs()
            if isinstance(allowed.get("settings"), dict):
                # merge settings key by key: the page's copy may not know a setting the server
                # changed (reward watching, saving screens), and must not erase it
                allowed["settings"] = {**current.get("settings", {}), **allowed["settings"]}
            merged = {**current, **allowed}
            atomic_write_text(self.prefs_path, json.dumps(merged))
        return merged

    def forget_consent(self) -> dict:
        """Take back permission to read the game session; the next grab asks again."""
        from ..config import save_settings

        if self.settings.extra.pop("session_reader_ok", None) is not None:
            save_settings(self.settings)
        return {"ok": True, "session_ok": False}

    def sync(self) -> dict:
        from ..account.sync import sync_profile

        sync_profile(self.settings)
        return self.build(force=True)

    def _store_inventory(self, data) -> None:
        from ..inventory import parse_inventory, unwrap

        data = unwrap(data)
        parse_inventory(data)  # validates
        atomic_write_text(self.inventory_path, json.dumps(data))

    def save_inventory(self, body: bytes) -> dict:
        self._store_inventory(json.loads(body.decode("utf-8-sig")))
        return self.build(force=True)


def _accepts_gzip(header: str | None) -> bool:
    """Accept-Encoding lists gzip, and not with q=0."""
    for part in (header or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() in ("gzip", "*"):
            q = params.strip().removeprefix("q=")
            try:
                return float(q) > 0 if params.strip().startswith("q=") else True
            except ValueError:
                return True
    return False


def _version_tuple(v: str) -> tuple[int, ...]:
    """'v0.5.1' -> (0, 5, 1); anything unreadable sorts as oldest."""
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts[:3]) if parts else ()


INCLUDE_RE = re.compile(r"^(?:/\*@include (\S+)\*/|//@include (\S+))$", re.M)


@functools.cache
def page_source(name: str = "static/index.html") -> str:
    """The page with its parts filled in.

    ``index.html`` is a shell: its style and script live in ``static/page/`` (one file per area),
    and each ``/*@include page/x.css*/`` or ``//@include page/x.js`` line is replaced by that
    file. The result is one self-contained page with a single script scope, as before the split.
    """
    base = resources.files("openwarframe.app").joinpath(name)
    folder = resources.files("openwarframe.app").joinpath(name.rsplit("/", 1)[0])

    def part(m: re.Match) -> str:
        return folder.joinpath(m.group(1) or m.group(2)).read_text(encoding="utf-8").removesuffix("\n")

    return INCLUDE_RE.sub(part, base.read_text(encoding="utf-8"))


def _page(name: str = "static/index.html") -> bytes:
    return page_source(name).encode("utf-8")


def make_handler(state: AppState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console quiet
            log.debug(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            gz = len(body) > GZIP_MIN and _accepts_gzip(self.headers.get("Accept-Encoding"))
            if gz:
                body = gzip.compress(body, compresslevel=5)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", "no-store")
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            """Only answer requests addressed to this server by name.

            A web page can point its own hostname at 127.0.0.1 (DNS rebinding) and then read
            responses as if they were its own; such requests carry that page's hostname.
            """
            port = self.server.server_port
            if self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return True
            self.close_connection = True
            self._send(403, b"forbidden", "text/plain")
            return False

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return
            state.last_ping = time.monotonic()
            if self.path in ("/", "/index.html"):
                self._send(200, _page(), "text/html; charset=utf-8")
            elif self.path == "/api/data":
                try:
                    data = state.build()
                    if isinstance(data.get("meta"), dict):
                        data["meta"]["session_ok"] = state.session_ok
                        data["meta"]["caps"] = state.capabilities()
                        data["meta"]["codex_warning"] = state.codex_warning
                        checked = state.profile_checked()
                        data["meta"]["profile_checked"] = checked.isoformat() if checked else None
                    else:  # the setup screen needs to know what works here too
                        data = {**data, "caps": state.capabilities()}
                    self._json(data)
                except Exception as exc:  # noqa: BLE001 - show the real problem instead of a dropped connection
                    log.exception("building app data failed")
                    self._json(
                        {"error": f"OpenWarframe hit a problem loading your data: {exc}", "can_update": True}
                    )
            elif self.path == "/api/status":
                self._json({"status": state.status})
            elif self.path.split("?", 1)[0] == "/api/live":
                try:
                    self._json(state.live(force="force=1" in self.path))
                except Exception as exc:  # noqa: BLE001 - network trouble is shown in the app
                    self._json({"error": f"Could not load the world state: {exc}"})
            elif self.path == "/api/prefs":
                self._json(state.get_prefs())
            elif urlsplit(self.path).path == "/api/frame-build":
                if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                    self._json({"error": "forbidden"}, 403)
                    return
                q = parse_qs(urlsplit(self.path).query)
                keys = [int(k) for k in (q.get("abilities") or [""])[0].split(",") if k.strip().isdigit()]
                try:
                    self._json(
                        state.frame_build_for(
                            (q.get("id") or [""])[0],
                            abilities=keys or None,
                            survivability=(q.get("surv") or ["some"])[0],
                            owned_only=(q.get("owned") or ["0"])[0] == "1",
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - shown in the item details
                    log.exception("frame build failed")
                    self._json({"error": f"Could not work out a build: {exc}"})
            elif urlsplit(self.path).path == "/api/build":
                if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                    self._json({"error": "forbidden"}, 403)
                    return
                q = parse_qs(urlsplit(self.path).query)
                try:
                    self._json(
                        state.build_for(
                            (q.get("id") or [""])[0],
                            target=(q.get("target") or ["none"])[0],
                            owned_only=(q.get("owned") or ["0"])[0] == "1",
                            stacks=(q.get("stacks") or ["1"])[0] == "1",
                            level=(q.get("level") or ["sp"])[0],
                            stripped=(q.get("stripped") or ["0"])[0] == "1",
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - shown in the item details
                    log.exception("build failed")
                    self._json({"error": f"Could not work out a build: {exc}"})
            elif self.path == "/api/reward":
                self._json(state.reward_status())
            elif self.path == "/mini":
                self._send(200, _page("static/mini.html"), "text/html; charset=utf-8")
            elif self.path == "/api/update":
                self._json(state.check_for_update())
            elif self.path == "/api/version":
                self._json({"version": repr(state._fingerprint())})
            elif self.path == "/api/ping":
                self._json({"ok": True})
            elif urlsplit(self.path).path == "/api/howto":
                # ?id=<uniqueName, URL-encoded> -> how to get it (sources, parts, notes)
                if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                    self._json({"error": "forbidden"}, 403)
                    return
                uid = (parse_qs(urlsplit(self.path).query).get("id") or [""])[0]
                try:
                    self._json(state.how_to_get(uid))
                except Exception as exc:  # noqa: BLE001
                    log.exception("how to get %s failed", uid)
                    self._json({"error": f"Could not look that up: {exc}"})
            elif urlsplit(self.path).path == "/api/names":
                # ?ids=a,b,c (each id URL-encoded) -> {id: display name}
                if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                    self._json({"error": "forbidden"}, 403)
                    return
                query = parse_qs(urlsplit(self.path).query)
                ids = [i.strip() for v in query.get("ids", []) for i in v.split(",")]
                try:
                    self._json(state.names(ids))
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": f"Could not look up names: {exc}"})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return
            state.last_ping = time.monotonic()
            if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}"):
                self._json({"error": "forbidden"}, 403)
                return
            raw_length = (self.headers.get("Content-Length") or "0").strip()
            if not raw_length.isdigit():
                self.close_connection = True
                self._json({"error": "bad request"}, 400)
                return
            length = int(raw_length)
            if length > MAX_BODY:
                self.close_connection = True
                self._json({"error": "That file is too large to be a Warframe inventory."}, 413)
                return
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
                    self._json(state.save_prefs(body, from_page=True))
                elif self.path == "/api/reward/watch":
                    req = json.loads(body.decode("utf-8") or "{}")
                    on = bool(req.get("on"))
                    state.save_prefs(json.dumps({"settings": {"reward_watch": on}}).encode())
                    self._json(state.rewards.start() if on else state.rewards.stop())
                elif self.path == "/api/reward/recordings":
                    req = json.loads(body.decode("utf-8") or "{}")
                    on = bool(req.get("on"))
                    state.save_prefs(json.dumps({"settings": {"save_recordings": on}}).encode())
                    self._json(state.rewards.set_recording(on))
                elif self.path == "/api/reward/capture":
                    state.rewards.capture_now("button")
                    self._json(state.reward_status())
                elif self.path == "/api/names":
                    req = json.loads(body.decode("utf-8") or "{}")
                    self._json(state.set_names_lang(str(req.get("lang") or "en")))
                elif self.path == "/api/reward/language":
                    req = json.loads(body.decode("utf-8") or "{}")
                    self._json(state.set_game_language(str(req.get("lang") or "en")))
                elif self.path == "/api/reward/hotkey":
                    req = json.loads(body.decode("utf-8") or "{}")
                    key = req.get("key")
                    key = str(key)[:40] if key else ""
                    state.save_prefs(json.dumps({"settings": {"capture_hotkey": key}}).encode())
                    state.apply_hotkey()
                    self._json(state.reward_status())
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
                    with contextlib.suppress(Exception):  # names are a bonus: never fail the update
                        state.refresh_names()
                    self._json(state.build(force=True))
                elif self.path == "/api/update/install":
                    self._json(state.install_update())
                elif self.path == "/api/export":
                    self._json(state.export(body))
                elif self.path == "/api/open-folder":
                    self._json(state.open_folder(body))
                elif self.path == "/api/consent/forget":
                    self._json(state.forget_consent())
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
    if open_window:  # a headless server (tests, the CI smoke test) builds on first request instead
        threading.Thread(target=state.refresh_on_open, daemon=True).start()  # warm up, refresh old data
    if state.get_prefs().get("settings", {}).get("reward_watch"):
        state.rewards.start()
    if open_window:
        state.apply_hotkey()
    threading.Thread(target=server.serve_forever, name="app-server", daemon=True).start()
    try:
        if open_window and _use_native(native):
            if _run_native(url, state):
                return
            log.warning("own window failed to open; using a browser window instead")
        if open_window:
            _open_window(url, settings)
            # the browser window pings the server; stop a while after it is closed
            wall = time.time()
            while time.monotonic() - state.last_ping <= IDLE_SECONDS:
                time.sleep(5)
                now = time.time()
                if now - wall > 60:  # the computer slept: give the window time to ping again
                    state.last_ping = time.monotonic()
                wall = now
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
