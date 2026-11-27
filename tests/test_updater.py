"""In-app update: which file to fetch, checksum checks, the swap scripts and the endpoint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from openwarframe.app import updater
from openwarframe.app.server import AppState
from openwarframe.config import Settings

ROOT = Path(__file__).parents[1]
PAYLOAD = b"new setup bytes"


def _release(tag: str = "v9.9.9") -> dict:
    url = "https://github.com/AES256Afro/OpenWarframe/releases/download/" + tag + "/"
    names = [f"OpenWarframe-{tag}-windows-setup.exe", f"OpenWarframe-{tag}-windows.zip", "SHA256SUMS.txt"]
    return {
        "tag_name": tag,
        "html_url": "https://github.com/AES256Afro/OpenWarframe/releases/tag/" + tag,
        "assets": [{"name": n, "browser_download_url": url + n} for n in names],
    }


def _client(digest: str | None = None) -> httpx.Client:
    good = hashlib.sha256(PAYLOAD).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("SHA256SUMS.txt"):
            return httpx.Response(200, text=f"{digest or good}  OpenWarframe-v9.9.9-windows-setup.exe\n")
        return httpx.Response(200, content=PAYLOAD)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("platform", "exe", "uninstaller", "kind"),
    [
        ("win32", "OpenWarframe/OpenWarframe.exe", True, "installer"),
        ("win32", "OpenWarframe/OpenWarframe.exe", False, "zip"),
        ("darwin", "OpenWarframe.app/Contents/MacOS/OpenWarframe", False, "mac"),
        ("linux", "OpenWarframe/OpenWarframe", False, "source"),
    ],
)
def test_install_kind(tmp_path: Path, monkeypatch, platform, exe, uninstaller, kind):
    path = tmp_path / exe
    path.parent.mkdir(parents=True)
    path.write_text("x")
    if uninstaller:
        (path.parent / "unins000.exe").write_text("x")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(path))
    monkeypatch.setattr(updater.sys, "platform", platform)
    assert updater.install_kind() == kind
    if kind == "mac":
        assert updater.app_folder().name == "OpenWarframe.app"


def test_running_from_source_is_not_updated_in_place():
    assert updater.install_kind() == "source"  # pytest is not a frozen build
    assert updater.pick_asset(_release(), "source") is None


def test_pick_asset_matches_the_install():
    asset, sums = updater.pick_asset(_release(), "installer")
    assert asset["name"] == "OpenWarframe-v9.9.9-windows-setup.exe" and sums["name"] == "SHA256SUMS.txt"
    assert updater.pick_asset(_release(), "zip")[0]["name"].endswith("-windows.zip")
    assert updater.pick_asset(_release(), "mac") is None  # no macOS zip in this release


def test_download_checks_the_hash(tmp_path: Path):
    f = updater.download(_release(), "installer", tmp_path / "updates", client=_client())
    assert f.read_bytes() == PAYLOAD
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(_release(), "installer", tmp_path / "updates", client=_client("0" * 64))
    assert not list((tmp_path / "updates").iterdir())  # a bad download is not kept


def test_scripts_quote_paths(tmp_path: Path):
    odd = tmp_path / "O'Brien" / "OpenWarframe"
    ps = updater.windows_zip_script(tmp_path / "u.zip", odd, 42)
    assert "O''Brien" in ps and "Wait-Process -Id 42" in ps and "Start-Process" in ps
    sh = updater.mac_script(tmp_path / "u.zip", odd.with_suffix(".app"), 42)
    assert "O'\\''Brien" in sh and "kill -0 42" in sh and "open " in sh


def test_installer_runs_silently_and_reopens(tmp_path: Path, monkeypatch):
    seen = {}
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: seen.setdefault("args", args))
    updater.launch("installer", tmp_path / "setup.exe")
    assert "/SILENT" in seen["args"] and "/RELAUNCH=1" in seen["args"]
    iss = (ROOT / "packaging/openwarframe.iss").read_text(encoding="utf-8")
    assert "Check: WantRelaunch" in iss and "{param:RELAUNCH|0}" in iss
    with pytest.raises(updater.UpdateError):
        updater.launch("source", tmp_path / "x")


def test_endpoint_installs_then_quits(tmp_path: Path, monkeypatch):
    state = AppState(Settings(home=tmp_path))
    state.update_info = {"current": "0.1.0", "latest": "9.9.9", "newer": True, "kind": "installer",
                         "can_install": True, "url": "u"}  # fmt: skip
    state.release = _release()
    calls = []
    monkeypatch.setattr(updater, "download", lambda rel, kind, folder: calls.append(kind) or folder / "s.exe")
    monkeypatch.setattr(updater, "launch", lambda kind, f: calls.append(f.name))
    monkeypatch.setattr(state, "_quit_for_update", lambda: calls.append("quit"))
    assert state.install_update() == {"ok": True, "latest": "9.9.9"}
    assert state.install_update()["error"].startswith("An update is already")
    import time

    time.sleep(1.7)
    assert calls == ["installer", "s.exe", "quit"]


def test_endpoint_reports_failures(tmp_path: Path, monkeypatch):
    state = AppState(Settings(home=tmp_path))
    state.update_info = {"current": "1", "latest": "1", "newer": False}
    assert "newest" in state.install_update()["error"]
    state.update_info = {
        "current": "0.1",
        "latest": "9.9.9",
        "newer": True,
        "kind": "source",
        "can_install": False,
    }
    assert "install command" in state.install_update()["error"]
    state.update_info = {
        "current": "0.1",
        "latest": "9.9.9",
        "newer": True,
        "kind": "zip",
        "can_install": True,
        "url": "u",
    }
    state.release = _release()

    def broken(*_):
        raise updater.UpdateError("The download failed (offline).")

    monkeypatch.setattr(updater, "download", broken)
    r = state.install_update()
    assert r["error"].startswith("The download failed") and not state.updating


def test_page_offers_update_now():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'id="updatenow"' in page and '"/api/update/install"' in page


@pytest.mark.skipif(updater.sys.platform != "win32", reason="runs PowerShell")
def test_windows_zip_swap_runs(tmp_path: Path):
    import os
    import shutil
    import subprocess
    import time
    import zipfile

    app = tmp_path / "My Apps" / "OpenWarframe"
    (app / "_internal").mkdir(parents=True)
    (app / "_internal" / "old.txt").write_text("old")
    upd = tmp_path / "updates"
    upd.mkdir()
    zpath = upd / "OpenWarframe-v9.9.9-windows.zip"
    # a harmless real program stands in for the new OpenWarframe.exe, so Start-Process works
    stand_in = Path(os.environ["SYSTEMROOT"]) / "System32" / "hostname.exe"
    with zipfile.ZipFile(zpath, "w") as z:
        z.write(stand_in, "OpenWarframe/OpenWarframe.exe")
        z.writestr("OpenWarframe/_internal/new.txt", "new")
    script = upd / "update.ps1"
    script.write_text(updater.windows_zip_script(zpath, app, 999_999), encoding="utf-8-sig")
    shell = shutil.which("pwsh") or "powershell.exe"
    subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True, timeout=120
    )
    time.sleep(1)
    assert (app / "_internal" / "new.txt").read_text() == "new"
    assert not (app / "_internal" / "old.txt").exists()  # the old runtime folder is replaced
    assert (app / "OpenWarframe.exe").exists() and not (upd / "unpacked").exists()


@pytest.mark.skipif(updater.sys.platform != "darwin", reason="uses ditto")
def test_mac_bundle_swap_runs(tmp_path: Path):
    import subprocess

    old = tmp_path / "Applications" / "OpenWarframe.app"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "old.txt").write_text("old")
    new = tmp_path / "build" / "OpenWarframe.app"
    (new / "Contents").mkdir(parents=True)
    (new / "Contents" / "new.txt").write_text("new")
    upd = tmp_path / "updates"
    upd.mkdir()
    zpath = upd / "OpenWarframe-v9.9.9-macos.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(new), str(zpath)], check=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    opened = tmp_path / "opened.txt"
    (fake_bin / "open").write_text(f'#!/bin/sh\necho "$1" > "{opened}"\n')
    (fake_bin / "open").chmod(0o755)
    script = upd / "update.sh"
    script.write_text(updater.mac_script(zpath, old, 999_999), encoding="utf-8")
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin"}
    subprocess.run(["/bin/sh", str(script)], check=True, timeout=60, env=env)
    assert (old / "Contents" / "new.txt").exists() and not (old / "Contents" / "old.txt").exists()
    assert opened.read_text().strip() == str(old)
