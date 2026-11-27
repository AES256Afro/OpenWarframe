"""The command line end to end, on a tiny game database and a synthetic profile. No network."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openwarframe.account import SnapshotStore, parse_profile
from openwarframe.cli import app
from openwarframe.config import Settings, save_settings
from test_account import _profile
from test_app import INVENTORY
from test_codex_build import codex_path  # noqa: F401

ACCOUNT = "5" * 24  # the synthetic profile's account


@pytest.fixture
def home(tmp_path: Path, codex_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    h = tmp_path / "home"
    monkeypatch.setenv("OPENWARFRAME_HOME", str(h))
    s = Settings(home=h, account_id=ACCOUNT)
    s.ensure_dirs()
    save_settings(s)
    s.codex_path.write_bytes(codex_path.read_bytes())
    store = SnapshotStore(s.snapshots_dir)
    store.save(parse_profile(_profile(braton_xp=100_000), taken_at=datetime(2026, 11, 1, tzinfo=UTC)))
    store.save(parse_profile(_profile(braton_xp=450_000), taken_at=datetime(2026, 11, 2, tzinfo=UTC)))
    return h


def run(*args: str) -> str:
    result = CliRunner().invoke(app, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_account_and_summary_commands(home: Path):
    assert ACCOUNT in run("account", "show")
    out = run("summary")
    assert "MR" in out and "mastery" in out
    assert "2026-11-02" in run("snapshots")
    assert "Changes" in run("diff") or "no progression changes" in run("diff")


def test_codex_commands_find_and_explain_items(home: Path):
    assert "Rhino" in run("codex", "search", "rhino")
    assert "Recipe" in run("codex", "item", "Rhino Prime")
    assert "warframe.market" in run("codex", "sources", "Rhino Prime")  # tradeable as a set
    assert "leaf totals" in run("codex", "tree", "Rhino Prime")
    assert "sources" in run("codex", "info")


def test_inventory_import_clear_and_consent(home: Path, tmp_path: Path):
    f = tmp_path / "inv.json"
    f.write_text(json.dumps({"InventoryJson": json.dumps(INVENTORY)}), encoding="utf-8")
    assert "Inventory loaded" in run("inventory", "import", str(f))
    inv_path = home / "accounts" / ACCOUNT / "inventory.json"
    assert json.loads(inv_path.read_text(encoding="utf-8"))["Suits"]  # stored unwrapped
    assert "Inventory cleared" in run("inventory", "clear") and not inv_path.exists()
    assert "No permission was stored" in run("inventory", "forget-consent")


def test_export_and_guide_write_their_files(home: Path, tmp_path: Path):
    out = tmp_path / "out"
    run("export", "-f", "json,csv,xlsx,llm", "-o", str(out), "--no-pdf")
    assert (out / "account.json").exists() and list(out.glob("*.xlsx")) and (out / "csv").is_dir()
    guide = tmp_path / "guide"
    run("guide", "mastery", "-o", str(guide), "--no-pdf", "--no-docx")
    assert (guide / "mastery-plan.html").exists()


def test_backup_keeps_your_data_and_leaves_downloads_out(home: Path, tmp_path: Path):
    target = tmp_path / "b.zip"
    run("backup", "--out", str(target))
    names = zipfile.ZipFile(target).namelist()
    assert "config.toml" in names and any(n.startswith(f"accounts/{ACCOUNT}/snapshots/") for n in names)
    assert "codex.sqlite" not in names and not any(n.startswith(("cache/", "logs/")) for n in names)


def test_selfcheck_and_version(home: Path):
    assert "bundled files: ok" in run("selfcheck")
    assert "openwarframe" in run("version")


def test_every_run_writes_the_log_file(home: Path):
    run("version")
    assert (home / "logs" / "openwarframe.log").exists()


def test_export_points_latest_at_its_folder_and_guide_share_keeps_its_own(home: Path):
    out = run("export", "-f", "json", "--no-pdf")
    latest = (home / "exports" / "LATEST.txt").read_text(encoding="utf-8").strip()
    assert Path(latest).name == "full" and (Path(latest) / "account.json").exists()
    assert "Export folder:" in out

    personal = run("guide", "mastery", "--no-pdf", "--no-docx")
    shared = run("guide", "mastery", "--share", "--no-pdf", "--no-docx")
    folder = Path(latest).parent
    assert (folder / "full" / "mastery-plan.html").exists() and (
        folder / "share" / "mastery-plan.html"
    ).exists()
    assert "Tester" in (folder / "full" / "mastery-plan.html").read_text(encoding="utf-8")
    assert "Tester" not in (folder / "share" / "mastery-plan.html").read_text(encoding="utf-8")
    # short by default: a summary and the files written, the full plan only on request
    assert "The path" not in personal and "wrote" in personal and len(personal.splitlines()) < 20
    assert "wrote" in shared
    assert "The path" in run("guide", "mastery", "--no-html", "--show-plan")
