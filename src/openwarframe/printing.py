"""Print HTML pages to PDF with a Chromium-based browser already on the machine.

Chrome, Edge, Chromium or Brave run headless, so the PDF is the page with its print
stylesheet and no browser download is needed. Override the browser with
OPENWARFRAME_BROWSER. Used by the mastery guide, the dashboard and the planning brief.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# One short line for players, the same wherever a PDF is skipped
NO_BROWSER_WARNING = "PDF skipped: no Chrome, Edge, Chromium or Brave found"


class PrintError(RuntimeError):
    """Printing failed. The message is short and readable; browser output goes to the log."""


class NoBrowserError(PrintError):
    pass


def pdf_failed_warning(name: str) -> str:
    """The player-facing line when the browser ran but did not produce ``name``."""
    return f"PDF skipped: the browser could not print {name} (details with -v)"


def candidate_browsers() -> list[Path]:
    env = os.environ.get("OPENWARFRAME_BROWSER")
    out: list[Path] = [Path(env)] if env else []
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rel = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Chromium\Application\chrome.exe",
        ]
        out += [Path(r) / p for r in roots if r for p in rel]
    elif sys.platform == "darwin":
        out += [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ]
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "msedge",
    ):
        found = shutil.which(name)
        if found:
            out.append(Path(found))
    return out


def find_browser() -> Path | None:
    """First Chromium-based browser found, or None."""
    for p in candidate_browsers():
        if p.is_file():
            return p
    return None


def html_to_pdf(
    html_path: Path, pdf_path: Path, *, browser: Path | None = None, timeout: float = 120
) -> Path:
    """Print an HTML file to PDF with a headless Chromium browser.

    Raises NoBrowserError when no browser is found and PrintError when printing fails.
    The browser's own output is logged at DEBUG (shown with -v), never put in the message.
    """
    browser = browser or find_browser()
    if not browser:
        raise NoBrowserError(
            "No Chrome, Edge, Chromium or Brave found for PDF output. Install one, or set "
            "OPENWARFRAME_BROWSER to its executable."
        )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()
    with tempfile.TemporaryDirectory(prefix="owf-pdf-") as profile:
        cmd = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_path.resolve()}",
            html_path.resolve().as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        except subprocess.TimeoutExpired as exc:
            raise PrintError(f"{browser.name} did not finish printing within {timeout:.0f}s") from exc
        except OSError as exc:
            log.debug("could not start %s: %s", browser, exc)
            raise PrintError(f"{browser.name} could not be started") from exc
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        log.debug(
            "%s did not write %s: %s", browser.name, pdf_path.name, (proc.stderr or proc.stdout or "").strip()
        )
        raise PrintError(f"{browser.name} did not write {pdf_path.name}")
    return pdf_path


def try_print(
    html_path: Path, pdf_path: Path, *, browser: Path | None = None
) -> tuple[Path | None, str | None]:
    """Print, turning every failure into one short warning: ``(pdf_or_None, warning_or_None)``."""
    browser = browser or find_browser()
    if not browser:
        return None, NO_BROWSER_WARNING
    try:
        return html_to_pdf(html_path, pdf_path, browser=browser), None
    except PrintError as exc:
        log.debug("printing %s failed: %s", pdf_path.name, exc)
        return None, pdf_failed_warning(pdf_path.name)
