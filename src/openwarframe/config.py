"""Settings and on-disk layout.

Everything OpenWarframe stores lives under one directory, with one sub-folder per account
(``accounts/<account id>/`` holds that account's snapshots and inventory):

    %LOCALAPPDATA%\\OpenWarframe   (Windows)
    ~/.local/share/OpenWarframe    (Linux)
    ~/Library/Application Support/OpenWarframe (macOS)

Override it with the OPENWARFRAME_HOME environment variable (tests do this).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

from . import __version__

log = logging.getLogger(__name__)

APP_NAME = "OpenWarframe"
USER_AGENT = f"OpenWarframe/{__version__} (+https://github.com/AES256Afro/OpenWarframe)"


@dataclass
class Settings:
    home: Path
    platform: str = "pc"
    account_id: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def codex_path(self) -> Path:
        return self.home / "codex.sqlite"

    @property
    def account_dir(self) -> Path:
        """Everything tied to one account. Before an account is set: the data folder itself."""
        return self.home / "accounts" / self.account_id if self.account_id else self.home

    @property
    def snapshots_dir(self) -> Path:
        return self.account_dir / "snapshots"

    @property
    def inventory_path(self) -> Path:
        return self.account_dir / "inventory.json"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    def ensure_dirs(self) -> None:
        for d in (self.home, self.cache_dir, self.snapshots_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_home() -> Path:
    env = os.environ.get("OPENWARFRAME_HOME")
    if env:
        return Path(env)
    return Path(user_data_dir(APP_NAME, appauthor=False))


def load_settings(home: Path | None = None) -> Settings:
    home = home or default_home()
    settings = Settings(home=home)
    cfg = settings.config_path
    if cfg.exists():
        try:
            data = tomllib.loads(cfg.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
            # a broken config must not stop the app from starting: keep a copy, use defaults
            bad = cfg.with_name(f"config.bad-{time.strftime('%Y%m%d-%H%M%S')}.toml")
            with contextlib.suppress(OSError):
                cfg.replace(bad)
            log.warning("config.toml could not be read (%s); moved it to %s and started fresh", exc, bad.name)
            data = {}
        settings.platform = str(data.get("platform", settings.platform))
        acc = data.get("account_id")
        settings.account_id = str(acc) if acc else None
        settings.extra = {k: v for k, v in data.items() if k not in {"platform", "account_id"}}
    migrate_to_account_folders(settings)
    settings.ensure_dirs()
    return settings


def migrate_to_account_folders(settings: Settings) -> int:
    """Move data from the old shared layout into one folder per account. Returns files moved.

    Up to 0.4.3 every snapshot and the inventory sat directly in the data folder, so
    switching accounts mixed them up (diffs across accounts, the old inventory shown with
    the new profile). Each old snapshot names its account, so it moves to that account's
    folder; the old inventory belongs to the account that is set, because switching
    accounts used to delete it.
    """
    if not settings.account_id:
        return 0
    legacy_snaps = settings.home / "snapshots"
    moved = 0
    if legacy_snaps.is_dir() and legacy_snaps != settings.snapshots_dir:
        import json

        for f in sorted(legacy_snaps.glob("*.json")):
            try:
                owner = (json.loads(f.read_text(encoding="utf-8")).get("identity") or {}).get("account_id")
            except (OSError, ValueError):
                owner = None
            dest = settings.home / "accounts" / (owner or settings.account_id) / "snapshots" / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                with contextlib.suppress(OSError):
                    f.replace(dest)
                    moved += 1
        with contextlib.suppress(OSError):
            legacy_snaps.rmdir()  # only when empty
    legacy_inv = settings.home / "inventory.json"
    if legacy_inv.is_file() and not settings.inventory_path.exists():
        settings.inventory_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            legacy_inv.replace(settings.inventory_path)
            moved += 1
    if moved:
        log.info("moved %d files into %s", moved, settings.account_dir)
    return moved


def save_settings(settings: Settings) -> Path:
    """Write config.toml: the keys OpenWarframe owns plus every extra it can represent."""
    from .fsutil import atomic_write_text

    top: dict = {"platform": settings.platform}
    if settings.account_id:
        top["account_id"] = settings.account_id
    tables: dict[str, dict] = {}
    for k, v in settings.extra.items():
        if isinstance(v, dict):
            tables[k] = v
        else:
            top[k] = v
    lines = [line for k, v in top.items() if (line := _toml_line(k, v))]
    for name, table in tables.items():
        lines += ["", f"[{_toml_key(name)}]"]
        lines += [line for k, v in table.items() if not isinstance(v, dict) and (line := _toml_line(k, v))]
    settings.ensure_dirs()
    atomic_write_text(settings.config_path, "\n".join(lines) + "\n")
    return settings.config_path


_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(k: str) -> str:
    return k if _BARE_KEY.match(k) else _toml_str(k)


def _toml_str(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\u{o:04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_value(v) -> str | None:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, str):
        return _toml_str(v)
    if isinstance(v, list | tuple):
        parts = [_toml_value(x) for x in v]
        return None if any(p is None for p in parts) else "[" + ", ".join(parts) + "]"
    return None


def _toml_line(k: str, v) -> str | None:
    val = _toml_value(v)
    return None if val is None else f"{_toml_key(str(k))} = {val}"
