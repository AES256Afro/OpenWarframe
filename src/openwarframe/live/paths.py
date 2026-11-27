"""Where Warframe keeps EE.log and EE.cfg on this computer.

Windows: ``%LOCALAPPDATA%\\Warframe``.

macOS: the native Mac client and Windows-under-CrossOver/Wine both work, and neither path
is documented, so we look in every likely folder and use the one whose EE.log changed
most recently. Set ``OPENWARFRAME_WARFRAME_DIR`` to the folder that holds EE.log to skip
the search.

Linux: Warframe runs through Steam's Proton (app 230410) or Lutris/plain Wine; we look in
the Proton prefix of every Steam library and in the usual Wine prefixes, newest EE.log wins.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _windows_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Warframe"


def mac_candidates(home: Path | None = None) -> list[Path]:
    """Folders that may hold EE.log on a Mac, most likely first."""
    home = home or Path.home()
    lib = home / "Library"
    out = [
        lib / "Application Support" / "Warframe",
        lib / "Logs" / "Warframe",
        lib / "Caches" / "Warframe",
    ]
    out += sorted(lib.glob("Containers/*arframe*/Data/Library/Application Support/Warframe"))
    out += sorted(lib.glob("Application Support/Digital Extremes*/Warframe"))
    # Windows build under CrossOver, Whisky or plain Wine
    prefixes = list(lib.glob("Application Support/CrossOver/Bottles/*/drive_c"))
    prefixes += list(lib.glob("Containers/com.isaacmarovitz.Whisky/Bottles/*/drive_c"))
    prefixes += [home / ".wine" / "drive_c"]
    for c in prefixes:
        out += sorted(c.glob("users/*/AppData/Local/Warframe"))
        out += sorted(c.glob("users/*/Local Settings/Application Data/Warframe"))
    return out


STEAM_APP_ID = "230410"


def linux_candidates(home: Path | None = None) -> list[Path]:
    """Folders that may hold EE.log on Linux (Proton, Lutris, Wine), most likely first."""
    home = home or Path.home()
    steam_roots = [
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",  # Flatpak
    ]
    libraries: list[Path] = []
    for root in steam_roots:
        libraries.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        libraries += [Path(m) for m in re.findall(r'"path"\s+"([^"]+)"', text)]
    prefixes: list[Path] = []
    for lib in libraries:
        prefixes.append(lib / "steamapps" / "compatdata" / STEAM_APP_ID / "pfx" / "drive_c")
    prefixes += sorted((home / "Games").glob("*arframe*/drive_c"))  # Lutris default
    prefixes += [home / ".wine" / "drive_c"]
    out: list[Path] = []
    seen: set[Path] = set()
    for c in prefixes:
        for d in [
            c / "users" / "steamuser" / "AppData" / "Local" / "Warframe",
            *sorted(c.glob("users/*/AppData/Local/Warframe")),
        ]:
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out


def _newest(candidates: list[Path]) -> Path:
    best: tuple[float, Path] | None = None
    for d in candidates:
        try:
            mtime = (d / "EE.log").stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, d)
    if best:
        return best[1]
    existing = [d for d in candidates if d.is_dir()]
    return existing[0] if existing else candidates[0]


def warframe_dir() -> Path:
    """The folder with Warframe's EE.log/EE.cfg (it may not exist if the game never ran)."""
    env = os.environ.get("OPENWARFRAME_WARFRAME_DIR")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        return _newest(mac_candidates())
    if sys.platform.startswith("linux"):
        return _newest(linux_candidates())
    return _windows_dir()
