"""Settings and on-disk layout.

Everything OpenWarframe stores lives under one directory:

    %LOCALAPPDATA%\\OpenWarframe   (Windows)
    ~/.local/share/OpenWarframe    (Linux)
    ~/Library/Application Support/OpenWarframe (macOS)

Override it with the OPENWARFRAME_HOME environment variable (tests do this).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "OpenWarframe"
USER_AGENT = "OpenWarframe/0.1 (+https://github.com/AES256Afro/OpenWarframe)"


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
    def snapshots_dir(self) -> Path:
        return self.home / "snapshots"

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
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
        settings.platform = str(data.get("platform", settings.platform))
        acc = data.get("account_id")
        settings.account_id = str(acc) if acc else None
        settings.extra = {k: v for k, v in data.items() if k not in {"platform", "account_id"}}
    settings.ensure_dirs()
    return settings
