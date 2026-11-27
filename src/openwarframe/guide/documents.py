"""Turn a rendered guide into shareable documents.

* PDF: printed by a Chromium-based browser already on the machine (see
  ``openwarframe.printing``).
* Cloud: Google Drive and OneDrive have no upload API we can use without an OAuth
  app, but both have desktop sync clients. When one is installed we copy the files
  into an ``OpenWarframe`` folder inside it and the sync client uploads them.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..printing import (  # noqa: F401 - re-exported for older imports
    NO_BROWSER_WARNING,
    NoBrowserError,
    PrintError,
    candidate_browsers,
    find_browser,
    html_to_pdf,
    try_print,
)

CLOUD_LABELS = {"gdrive": "Google Drive", "onedrive": "OneDrive"}
CLOUD_WEB = {
    "gdrive": "https://drive.google.com/drive/my-drive",
    "onedrive": "https://onedrive.live.com/",
}
CLOUD_SUBDIR = "OpenWarframe"


# -- browser / PDF -----------------------------------------------------------------------
# The printer lives in openwarframe.printing (the dashboard and the brief use it too); these
# names stay here so older imports keep working.

_candidate_browsers = candidate_browsers


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
        bundle.pdf, warning = try_print(html_path, pdf_path, browser=browser)
        if warning:
            bundle.warnings.append(warning)
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
