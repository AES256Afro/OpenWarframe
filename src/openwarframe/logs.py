"""Where OpenWarframe writes what happened: a small rotating log file in the data folder.

The windowed app has no console, so before this its warnings and crashes vanished. Now
both the app and the CLI write to ``<data folder>/logs/openwarframe.log`` (at most four
files of 1 MB), uncaught errors included, so a player can send it with a bug report.
Secrets are masked before anything is written (see logsafe).
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import logsafe

LOG_NAME = "openwarframe.log"
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_installed: Path | None = None


def log_path(home: Path) -> Path:
    return Path(home) / "logs" / LOG_NAME


def setup_logging(
    home: Path, *, console_level: int | None = None, file_level: int = logging.INFO
) -> Path | None:
    """Log to the data folder's rotating file (and to the console at ``console_level``).

    Safe to call more than once; returns the log file, or None if it can't be written.
    """
    global _installed
    root = logging.getLogger()
    root.setLevel(min(file_level, console_level or logging.CRITICAL))
    if console_level is not None and not any(type(h) is logging.StreamHandler for h in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(console_level)
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)
    path = log_path(home)
    if _installed != path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=1 << 20, backupCount=3, encoding="utf-8")
        except OSError:
            path = None
        else:
            handler.setLevel(file_level)
            handler.setFormatter(logging.Formatter(FORMAT))
            for h in [h for h in root.handlers if isinstance(h, RotatingFileHandler)]:
                root.removeHandler(h)
                h.close()
            root.addHandler(handler)
            _installed = path
    logsafe.install()  # mask secrets in every handler, the file included
    _capture_crashes()
    return path


def _capture_crashes() -> None:
    """Write uncaught errors (main thread and background threads) to the log too."""
    if getattr(sys.excepthook, "_openwarframe", False):
        return
    previous = sys.excepthook

    def hook(kind, value, tb):
        if not issubclass(kind, KeyboardInterrupt):
            logging.getLogger("openwarframe").critical("uncaught error", exc_info=(kind, value, tb))
        previous(kind, value, tb)

    hook._openwarframe = True  # type: ignore[attr-defined]
    sys.excepthook = hook

    def thread_hook(args):
        if args.exc_type is not SystemExit:
            logging.getLogger("openwarframe").error(
                "uncaught error in thread %s",
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

    threading.excepthook = thread_hook
