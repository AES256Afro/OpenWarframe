"""Milestone 5: per-account data, damaged or changed inputs, and failures that explain
themselves. No network."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwarframe.account import SnapshotStore, parse_profile
from openwarframe.config import Settings, load_settings, migrate_to_account_folders, save_settings
from openwarframe.http import CachedClient
from openwarframe.sources.account.profile import ProfileError
from test_account import _profile

A, B = "a" * 24, "b" * 24


def _profile_for(account: str, rhino_xp: int = 900_000) -> dict:
    data = _profile(rhino_xp=rhino_xp)
    data["Results"][0]["AccountId"] = {"$oid": account}
    return data


# -- one folder per account ----------------------------------------------------------------


def test_each_account_has_its_own_snapshots_and_inventory(tmp_path: Path):
    s = Settings(home=tmp_path, account_id=A)
    assert s.snapshots_dir == tmp_path / "accounts" / A / "snapshots"
    assert s.inventory_path == tmp_path / "accounts" / A / "inventory.json"
    assert Settings(home=tmp_path).snapshots_dir == tmp_path / "snapshots"  # before an account is set


def test_old_shared_data_moves_to_the_right_account(tmp_path: Path):
    legacy = SnapshotStore(tmp_path / "snapshots")
    legacy.save(parse_profile(_profile_for(A), taken_at=datetime(2026, 11, 1, tzinfo=UTC)))
    legacy.save(parse_profile(_profile_for(B), taken_at=datetime(2026, 11, 2, tzinfo=UTC)))  # newest: B's
    (tmp_path / "inventory.json").write_text("{}", encoding="utf-8")
    save_settings(Settings(home=tmp_path, account_id=A))

    s = load_settings(tmp_path)  # migrates on load
    assert SnapshotStore(s.snapshots_dir).latest().identity.account_id == A  # not B's newer snapshot
    other = Settings(home=tmp_path, account_id=B)
    assert SnapshotStore(other.snapshots_dir).latest().identity.account_id == B
    assert s.inventory_path.exists() and not (tmp_path / "inventory.json").exists()
    assert not (tmp_path / "snapshots").exists()
    assert migrate_to_account_folders(s) == 0  # nothing left to move


# -- a changed profile format ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ("LoadOutInventory",),
        ("LoadOutInventory", "XPInfo"),
        ("Missions",),
        ("Affiliations",),
        ("ChallengeProgress",),
        ("PlayerSkills",),
        ("PlayerLevel",),
        ("LoadOutPreset",),
        ("DailyAffiliation",),
        ("AccountId",),
        ("DisplayName",),
        ("GuildName",),
        ("GuildTier",),
        ("Created",),
    ],
)
@pytest.mark.parametrize("value", [None, "text", 42, [None], {"x": None}])
def test_a_changed_or_null_profile_field_never_crashes(path: tuple[str, ...], value):
    data = _profile_for(A)
    node = data["Results"][0]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = copy.deepcopy(value)
    snap = parse_profile(data)
    assert snap.progression is not None


def test_null_entries_inside_lists_are_skipped():
    data = _profile_for(A)
    r = data["Results"][0]
    r["LoadOutInventory"]["XPInfo"].append(None)
    r["LoadOutInventory"]["XPInfo"].append({"ItemType": "/x", "XP": None})
    r["Missions"].append(None)
    data["Stats"] = None
    snap = parse_profile(data)
    assert any(i.item == "/x" and i.xp == 0 for i in snap.progression.items)


def test_an_unreadable_profile_is_kept_and_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import openwarframe.account.sync as sync

    s = Settings(home=tmp_path, account_id=A)
    monkeypatch.setattr(sync, "fetch_profile", lambda *a, **k: {"Results": [{"weird": True}]})
    monkeypatch.setattr(sync, "parse_profile", lambda *a, **k: (_ for _ in ()).throw(KeyError("Suits")))
    with pytest.raises(ProfileError, match="could not be read") as err:
        sync.sync_profile(s)
    kept = s.account_dir / "unreadable-profile.json"
    assert str(kept) in str(err.value) and json.loads(kept.read_text(encoding="utf-8"))["Results"]


def test_no_network_on_the_first_sync_is_a_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import openwarframe.account.sync as sync

    def offline(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(sync, "fetch_profile", offline)
    with pytest.raises(ProfileError, match="internet connection"):
        sync.sync_profile(Settings(home=tmp_path, account_id=A))


# -- polite HTTP ------------------------------------------------------------------------------


def _client(tmp_path: Path, responses: list[httpx.Response]) -> tuple[CachedClient, list]:
    calls: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return responses[min(len(calls), len(responses)) - 1]

    c = CachedClient(tmp_path, retries=3)
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c, calls


def test_a_429_is_retried_after_the_wait_it_asks_for(tmp_path: Path):
    c, calls = _client(
        tmp_path, [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={"ok": 1})]
    )
    assert c.get_json("https://x.invalid/a") == {"ok": 1}
    assert len(calls) == 2 and c.last_was_network
    c.get_json("https://x.invalid/a", max_age=3600)
    assert not c.last_was_network  # served from the cache: no request went out


def test_rate_limited_with_a_stale_copy_serves_the_copy(tmp_path: Path):
    c, _ = _client(tmp_path, [httpx.Response(200, json={"v": 1})])
    c.get_json("https://x.invalid/a")
    c2, calls = _client(tmp_path, [httpx.Response(429, headers={"Retry-After": "0"})])
    assert c2.get_json("https://x.invalid/a", max_age=0) == {"v": 1}
    assert len(calls) == 3 and c2.last_was_network


# -- the CLI explains instead of crashing -------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["summary"], "Run: openwarframe sync"),
        (["diff"], "needs two snapshots"),
        (["codex", "info"], "Run: openwarframe codex update"),
        (["codex", "item", "rhino"], "Run: openwarframe codex update"),
    ],
)
def test_cli_on_a_fresh_install_prints_the_next_step(
    argv: list[str], says: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    from openwarframe import cli

    monkeypatch.setenv("OPENWARFRAME_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["openwarframe", *argv])
    with pytest.raises(SystemExit) as exit_:
        cli.main()
    assert exit_.value.code == 1
    out = capsys.readouterr().out
    assert says in " ".join(out.split()) and "Traceback" not in out


def test_game_text_with_brackets_prints_as_is(capsys):
    from openwarframe import cli
    from openwarframe.account.store import diff_snapshots

    a = parse_profile(_profile_for(A), taken_at=datetime(2026, 11, 1, tzinfo=UTC))
    b = parse_profile(_profile_for(A, rhino_xp=2_000_000), taken_at=datetime(2026, 11, 2, tzinfo=UTC))
    b.progression.items[0].name = "Foo [/] [bold]bar"
    b.progression.items[0].mastered = True
    a.progression.items[0].mastered = False
    cli._print_diff(diff_snapshots(a, b))
    assert "Foo [/] [bold]bar" in capsys.readouterr().out


# -- exports carry on -------------------------------------------------------------------------


def test_a_locked_workbook_does_not_stop_the_other_formats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from openwarframe.exports import run as run_mod
    from test_guide import _report

    def locked(report, tables, path, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(run_mod, "write_xlsx", locked)
    results = run_mod.run_exports(
        _report(), tmp_path, ["xlsx", "json", "csv"], guide_pdf=False, guide_docx=False
    )
    kinds = [r.format for r in results]
    assert kinds == ["warning", "json", "csv"]
    assert "is open in another program" in results[0].detail
    assert (tmp_path / "account.json").exists()


def test_a_failed_market_download_is_not_reported_as_fresh(tmp_path: Path):
    from openwarframe.codex import CodexPayloads, build_codex
    from test_codex_build import _drops, _pe, _plus

    conn = sqlite3.connect(tmp_path / "c.sqlite")
    build_codex(conn, CodexPayloads(public_export=_pe(), plus=_plus(), drops=_drops(), market=[]))
    version = conn.execute("SELECT version FROM source_version WHERE source = 'warframe_market'").fetchone()[
        0
    ]
    conn.close()
    assert version == "unavailable"


def test_the_browser_window_server_waits_out_throttled_pings():
    from openwarframe.app import server

    assert server.IDLE_SECONDS >= 120  # hidden browser windows ping about once a minute
