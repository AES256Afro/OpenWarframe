"""Where Warframe keeps EE.log and EE.cfg on this computer.

Windows: ``%LOCALAPPDATA%\\Warframe``.

macOS: the native Mac client and Windows-under-CrossOver/Wine both work, and neither path
is documented, so we look in every likely folder and use the one whose EE.log changed
most recently. Set ``OPENWARFRAME_WARFRAME_DIR`` to the folder that holds EE.log to skip
the search.
"""

from __future__ import annotations

import os
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


def warframe_dir() -> Path:
    """The folder with Warframe's EE.log/EE.cfg (it may not exist if the game never ran)."""
    env = os.environ.get("OPENWARFRAME_WARFRAME_DIR")
    if env:
        return Path(env)
    if sys.platform != "darwin":
        return _windows_dir()
    best: tuple[float, Path] | None = None
    candidates = mac_candidates()
    for d in candidates:
        log = d / "EE.log"
        try:
            mtime = log.stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, d)
    if best:
        return best[1]
    existing = [d for d in candidates if d.is_dir()]
    return existing[0] if existing else candidates[0]
