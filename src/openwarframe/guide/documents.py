"""Turn a rendered guide into shareable documents.

* PDF: printed by a Chromium-based browser already on the machine (Chrome, Edge,
  Chromium, Brave) in headless mode, so the PDF is the HTML page with its print
  stylesheet. No browser download is needed. Override with OPENWARFRAME_BROWSER.
* Cloud: Google Drive and OneDrive have no upload API we can use without an OAuth
  app, but both have desktop sync clients. When one is installed we copy the files
  into an ``OpenWarframe`` folder inside it and the sync client uploads them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CLOUD_LABELS = {"gdrive": "Google Drive", "onedrive": "OneDrive"}
CLOUD_WEB = {
    "gdrive": "https://drive.google.com/drive/my-drive",
    "onedrive": "https://onedrive.live.com/",
}
CLOUD_SUBDIR = "OpenWarframe"


# -- browser / PDF -----------------------------------------------------------------------


def _candidate_browsers() -> list[Path]:
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
    for p in _candidate_browsers():
        if p.is_file():
            return p
    return None


def html_to_pdf(
    html_path: Path, pdf_path: Path, *, browser: Path | None = None, timeout: float = 120
) -> Path:
    """Print an HTML file to PDF with a headless Chromium browser.

    Raises RuntimeError with a readable message when no browser is found or printing fails.
    """
    browser = browser or find_browser()
    if not browser:
        raise RuntimeError(
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
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{browser.name} did not finish printing within {timeout:.0f}s") from exc
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"{browser.name} did not write the PDF ({tail[0][:160]})")
    return pdf_path


# -- cloud sync folders -------------------------------------------------------------------


def cloud_folders() -> dict[str, Path]:
    """Local sync folders for Google Drive for desktop and OneDrive, when present."""
    found: dict[str, Path] = {}
    home = Path.home()

    onedrive = [os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    onedrive_paths = [Path(p) for p in onedrive if p] + [home / "OneDrive"]
    onedrive_paths += sorted((home / "Library" / "CloudStorage").glob("OneDrive*"))
    for p in onedrive_paths:
        if p.is_dir():
            found["onedrive"] = p
            break

    gdrive_paths: list[Path] = []
    env = os.environ.get("OPENWARFRAME_GDRIVE")
    if env:
        gdrive_paths.append(Path(env))
    if sys.platform == "win32":
        gdrive_paths += [Path(f"{letter}:/My Drive") for letter in "GHIJKLMNOPQRSTUVWXYZDEF"]
    gdrive_paths += [home / "Google Drive" / "My Drive", home / "Google Drive", home / "My Drive"]
    gdrive_paths += [p / "My Drive" for p in sorted((home / "Library" / "CloudStorage").glob("GoogleDrive*"))]
    for p in gdrive_paths:
        try:
            if p.is_dir():
                found["gdrive"] = p
                break
        except OSError:  # unmounted drive letters
            continue
    return found


def parse_targets(spec: str | None) -> list[str]:
    if not spec:
        return []
    aliases = {
        "google": "gdrive",
        "googledrive": "gdrive",
        "drive": "gdrive",
        "gdrive": "gdrive",
        "onedrive": "onedrive",
    }
    out: list[str] = []
    for raw in spec.split(","):
        key = aliases.get(raw.strip().lower().replace(" ", "").replace("-", ""))
        if not key:
            raise ValueError(f"unknown cloud target '{raw.strip()}'; use onedrive or gdrive")
        if key not in out:
            out.append(key)
    return out


def copy_to_cloud(
    files: list[Path], targets: list[str], folders: dict[str, Path] | None = None
) -> dict[str, Path]:
    """Copy files into <sync folder>/OpenWarframe for each target. Returns target -> folder used.

    Raises RuntimeError when a requested target has no sync folder on this machine.
    """
    folders = cloud_folders() if folders is None else folders
    missing = [t for t in targets if t not in folders]
    if missing:
        names = ", ".join(CLOUD_LABELS[t] for t in missing)
        raise RuntimeError(
            f"No sync folder found for {names}. Install the desktop app (Google Drive for desktop or "
            "OneDrive), or upload the files by hand."
        )
    used: dict[str, Path] = {}
    for t in targets:
        dest = folders[t] / CLOUD_SUBDIR
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.exists():
                shutil.copy2(f, dest / f.name)
        used[t] = dest
    return used


# -- bundle -------------------------------------------------------------------------------


@dataclass
class GuideFiles:
    """What the toolbar in the HTML page can link to."""

    html: str = "mastery-plan.html"
    pdf: str | None = None
    docx: str | None = None
    folder: str | None = None  # absolute output folder, omitted in share mode
    cloud: dict[str, str] = field(default_factory=dict)  # target -> folder the files were copied to


@dataclass
class GuideBundle:
    html: Path
    pdf: Path | None = None
    docx: Path | None = None
    cloud: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def files(self) -> list[Path]:
        return [p for p in (self.html, self.pdf, self.docx) if p]


def write_guide_bundle(
    plan,
    out_dir: Path,
    *,
    pdf: bool = True,
    docx: bool = True,
    copy_to: list[str] | None = None,
    share: bool = False,
    browser: Path | None = None,
    folders: dict[str, Path] | None = None,
) -> GuideBundle:
    """Write mastery-plan.html plus optional .docx/.pdf, and copy them to cloud sync folders.

    The HTML is written twice when needed: first with links to the files we are about to
    create, then again if PDF printing failed, so its buttons never point at a missing file.
    """
    from .render import write_mastery_html
    from .word import write_mastery_docx

    copy_to = copy_to or []
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "mastery-plan.html"
    pdf_path = out_dir / "mastery-plan.pdf"
    docx_path = out_dir / "mastery-plan.docx"
    bundle = GuideBundle(html=html_path)

    if docx:
        bundle.docx = write_mastery_docx(plan, docx_path)

    folders = cloud_folders() if folders is None else folders
    planned_cloud = {t: str(folders[t] / CLOUD_SUBDIR) for t in copy_to if t in folders}
    links = GuideFiles(
        pdf=pdf_path.name if pdf else None,
        docx=docx_path.name if bundle.docx else None,
        folder=None if share else str(out_dir.resolve()),
        cloud=planned_cloud,
    )
    write_mastery_html(plan, html_path, files=links)

    if pdf:
        try:
            bundle.pdf = html_to_pdf(html_path, pdf_path, browser=browser)
        except RuntimeError as exc:
            bundle.warnings.append(f"PDF skipped: {exc}")
            links.pdf = None
            write_mastery_html(plan, html_path, files=links)

    if copy_to:
        missing = [t for t in copy_to if t not in folders]
        if missing:
            names = ", ".join(CLOUD_LABELS[t] for t in missing)
            bundle.warnings.append(
                f"No sync folder found for {names}. Install the desktop app, or use the upload steps "
                "the page shows."
            )
        ok = [t for t in copy_to if t in folders]
        if ok:  # the page already links these, so copy the final files last
            bundle.cloud = copy_to_cloud(bundle.files(), ok, folders)
    return bundle
