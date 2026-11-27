"""Update OpenWarframe from inside the app: download, check, install, reopen.

How it updates depends on how it was installed:

- ``installer`` (Windows Setup .exe, the folder has ``unins000.exe``): download the new
  ``-windows-setup.exe`` and run it silently with ``/RELAUNCH=1``; Inno Setup closes the old
  app, installs over it in place and starts the new one.
- ``zip`` (Windows zip, unpacked anywhere): download the new ``-windows.zip``; a small
  PowerShell script waits for the app to close, swaps the files in that folder and starts it.
- ``mac`` (OpenWarframe.app): download the new ``-macos.zip``; a shell script waits for the app
  to close, replaces the bundle and opens it.
- ``source`` (``uv tool`` or a checkout): not updated from the app; run the install command again.

Every download is checked against the release's SHA256SUMS file before anything runs.
Downloads go to ``<data folder>/updates`` and are removed by the next update.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

ASSET_SUFFIX = {"installer": "-windows-setup.exe", "zip": "-windows.zip", "mac": "-macos.zip"}
SUMS_FILE = {"installer": "SHA256SUMS.txt", "zip": "SHA256SUMS.txt", "mac": "SHA256SUMS-macos.txt"}
SOURCE_HINT = (
    "This copy runs from source. To update, run the install command again: "
    "irm https://github.com/AES256Afro/OpenWarframe/releases/latest/download/install.ps1 | iex"
)


class UpdateError(Exception):
    """Shown to the player as is."""


def app_folder() -> Path:
    """Where the running app's files are (the folder with OpenWarframe.exe, or the .app bundle)."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
    return exe.parent


def install_kind() -> str:
    if not getattr(sys, "frozen", False):
        return "source"
    folder = app_folder()
    if sys.platform == "win32":
        return "installer" if (folder / "unins000.exe").exists() else "zip"
    if sys.platform == "darwin" and folder.suffix == ".app":
        return "mac"
    return "source"


def pick_asset(release: dict, kind: str) -> tuple[dict, dict] | None:
    """The release file for this kind of install and its checksum file, if the release has both."""
    if kind not in ASSET_SUFFIX:
        return None
    assets = release.get("assets") or []
    tag = str(release.get("tag_name") or "")
    want = f"OpenWarframe-{tag}{ASSET_SUFFIX[kind]}"
    asset = next((a for a in assets if a.get("name") == want), None)
    sums = next((a for a in assets if a.get("name") == SUMS_FILE[kind]), None)
    return (asset, sums) if asset and sums else None


def expected_hash(sums_text: str, name: str) -> str:
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise UpdateError(f"The release's checksum list doesn't include {name}.")


def download(release: dict, kind: str, folder: Path, *, client: httpx.Client | None = None) -> Path:
    """Download this install's release file into ``folder`` and check its SHA-256."""
    picked = pick_asset(release, kind)
    if not picked:
        raise UpdateError("This release has no update file for your kind of install.")
    asset, sums = picked
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    own = client is None
    client = client or httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=120.0),
        headers={"User-Agent": "OpenWarframe updater"},
    )
    try:
        sums_resp = client.get(sums["browser_download_url"])
        sums_resp.raise_for_status()
        want = expected_hash(sums_resp.text, asset["name"])
        target = folder / asset["name"]
        digest = hashlib.sha256()
        with client.stream("GET", asset["browser_download_url"]) as resp:
            resp.raise_for_status()
            with target.open("wb") as fh:
                for chunk in resp.iter_bytes(1 << 16):
                    digest.update(chunk)
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        raise UpdateError(f"The download failed ({exc}). Check your connection and try again.") from exc
    finally:
        if own:
            client.close()
    if digest.hexdigest() != want:
        target.unlink(missing_ok=True)
        raise UpdateError("The download didn't match the release's checksum, so it was not installed.")
    return target


def windows_zip_script(zip_path: Path, app_dir: Path, pid: int) -> str:
    """PowerShell that waits for the app to close, swaps its folder's files and starts it again."""

    def q(p: Path | str) -> str:
        return "'" + str(p).replace("'", "''") + "'"

    return f"""$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Updating OpenWarframe'
Write-Host 'Updating OpenWarframe. This window closes by itself.'
try {{ Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue }} catch {{}}
$zip = {q(zip_path)}
$app = {q(app_dir)}
$tmp = Join-Path (Split-Path $zip) 'unpacked'
if (Test-Path $tmp) {{ Remove-Item $tmp -Recurse -Force }}
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$new = Join-Path $tmp 'OpenWarframe'
if (-not (Test-Path (Join-Path $new 'OpenWarframe.exe'))) {{ throw 'The update zip has no OpenWarframe.exe' }}
if (Test-Path (Join-Path $app '_internal')) {{ Remove-Item (Join-Path $app '_internal') -Recurse -Force }}
Copy-Item -Path (Join-Path $new '*') -Destination $app -Recurse -Force
Remove-Item $tmp -Recurse -Force
Start-Process -FilePath (Join-Path $app 'OpenWarframe.exe') -WorkingDirectory $app
"""


def mac_script(zip_path: Path, app_bundle: Path, pid: int) -> str:
    """sh that waits for the app to quit, replaces the bundle and opens it."""

    def q(p: Path | str) -> str:
        return "'" + str(p).replace("'", "'\\''") + "'"

    return f"""#!/bin/sh
set -e
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
tmp={q(zip_path.parent / "unpacked")}
rm -rf "$tmp"
ditto -x -k {q(zip_path)} "$tmp"
test -d "$tmp/OpenWarframe.app"
rm -rf {q(app_bundle)}
ditto "$tmp/OpenWarframe.app" {q(app_bundle)}
xattr -dr com.apple.quarantine {q(app_bundle)} 2>/dev/null || true
rm -rf "$tmp"
open {q(app_bundle)}
"""


def launch(kind: str, file: Path) -> None:
    """Start the step that installs ``file``; the app must quit right after this returns."""
    pid = os.getpid()
    if kind == "installer":
        args = [str(file), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]
        subprocess.Popen(args, close_fds=True, creationflags=_detached())  # noqa: S603
    elif kind == "zip":
        script = file.parent / "update.ps1"
        script.write_text(windows_zip_script(file, app_folder(), pid), encoding="utf-8-sig")
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        subprocess.Popen(args, close_fds=True, creationflags=_detached(console=True))  # noqa: S603
    elif kind == "mac":
        script = file.parent / "update.sh"
        script.write_text(mac_script(file, app_folder(), pid), encoding="utf-8")
        subprocess.Popen(["/bin/sh", str(script)], close_fds=True, start_new_session=True)  # noqa: S603
    else:
        raise UpdateError(SOURCE_HINT)


def _detached(console: bool = False) -> int:
    if sys.platform != "win32":
        return 0
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    if console:  # a console of its own, so the player sees what is happening
        flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return flags
