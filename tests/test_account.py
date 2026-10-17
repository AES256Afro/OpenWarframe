"""Profile parsing, snapshot storage and diffs on a synthetic profile. No network."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from openwarframe.account import SnapshotStore, diff_snapshots, parse_profile
from openwarframe.account.parse import category_from_path, mastery_for, max_rank, rank_from_xp
from openwarframe.account.summary import summarize
from openwarframe.config import Settings, load_settings, save_settings
from openwarframe.sources.account.profile import profile_url, validate_account_id

RHINO = "/Lotus/Powersuits/Rhino/RhinoPrime"
BRATON = "/Lotus/Weapons/Tenno/Rifle/Braton"


def _profile(rhino_xp: int = 900_000, braton_xp: int = 200_000, nodes=None, standing=1000):
    return {
        "Results": [
            {
                "AccountId": {"$oid": "5" * 24},
                "DisplayName": "Tester",
                "PlayerLevel": 12,
                "GuildName": "Clan",
                "GuildTier": 1,
                "Created": {"$date": {"$numberLong": "1360056976824"}},
                "LoadOutInventory": {
                    "XPInfo": [{"ItemType": RHINO, "XP": rhino_xp}, {"ItemType": BRATON, "XP": braton_xp}],
                    "Suits": [{"ItemType": RHINO}],
                    "LongGuns": [{"ItemType": BRATON}],
                },
                "LoadOutPreset": {"FocusSchool": "AP_POWER"},
                "Missions": nodes if nodes is not None else [{"Tag": "SolNode94", "Completes": 3}],
                "Affiliations": [{"Tag": "ArbitersSyndicate", "Standing": standing, "Title": 1}],
                "DailyAffiliation": 16000,
                "PlayerSkills": {"LPS_GUNNERY": 3},
                "ChallengeProgress": [{"Name": "Apply4Mods", "Progress": 1}],
            }
        ],
        "Stats": {"TimePlayedSec": 7200.0, "MissionsCompleted": 10, "GuildName": "Clan"},
    }


def test_mastery_math():
    assert rank_from_xp(900_000, suit=True) == 30
    assert rank_from_xp(450_000, suit=False) == 30
    assert rank_from_xp(200_000, suit=False) == 20
    assert rank_from_xp(2_000_000, suit=True) == 30  # capped at 30 by default
    assert rank_from_xp(2_000_000, suit=True, cap=40) == 40
    assert mastery_for(30, True) == 6000 and mastery_for(30, False) == 3000
    assert category_from_path("/Lotus/Powersuits/Archwing/Odonata") == "Archwing"
    assert category_from_path("/Lotus/Weapons/Tenno/Melee/Skana") == "Melee"


def test_max_rank_rules():
    assert max_rank("Skana Prime", "Melee") == 30
    assert max_rank("Excalibur Prime", "Warframe") == 30
    assert max_rank("Carrier", "Companion") == 30
    for name in ("Kuva Bramma", "Tenet Arca Plasmor", "Coda Hema", "Dual Coda Torxica", "Paracesis"):
        assert max_rank(name, "Primary") == 40, name
    assert max_rank("Bonewidow", "Necramech") == 40
    assert max_rank("Kunai", "Secondary", "/Lotus/Weapons/Tenno/Pistols/Kunai/Kunai") == 30
    assert (
        max_rank("KuvaNukor", "Secondary", "/Lotus/Weapons/Grineer/KuvaLich/Secondaries/Nukor/KuvaNukor")
        == 40
    )


def _xp_profile(entries: list[tuple[str, int]]) -> dict:
    data = _profile()
    data["Results"][0]["LoadOutInventory"]["XPInfo"] = [{"ItemType": t, "XP": xp} for t, xp in entries]
    return data


def test_rank_cap_in_parse():
    kuva = "/Lotus/Weapons/Grineer/KuvaLich/Secondaries/Nukor/KuvaNukor"
    mech = "/Lotus/Powersuits/EntratiMech/ThanoTech"
    kdrive = "/Lotus/Types/Vehicles/Hoverboard/HoverboardParts/PartComponents/HoverboardCorpusB/HoverboardCorpusBDeck"
    snap = parse_profile(
        _xp_profile(
            [(BRATON, 900_000), (kuva, 900_000), (RHINO, 2_000_000), (mech, 2_000_000), (kdrive, 1015)]
        )
    )
    got = {i.item: (i.category, i.rank, i.mastery_xp) for i in snap.progression.items}
    assert got[BRATON] == ("Primary", 30, 3000)  # normal weapon caps at 30
    assert got[kuva][1:] == (40, 4000)  # Kuva weapon reaches 40
    assert got[RHINO] == ("Warframe", 30, 6000)  # frame caps at 30
    assert got[mech] == ("Necramech", 40, 8000)  # Necramech reaches 40
    assert got[kdrive] == ("K-Drive", 1, 200)  # K-Drive levels like a frame
    assert snap.progression.mastery_xp_from_items == 3000 + 4000 + 6000 + 8000 + 200


def test_parse_profile_without_codex():
    snap = parse_profile(_profile(), platform="pc", taken_at=datetime(2026, 10, 16, tzinfo=UTC))
    p = snap.progression
    assert p.mastery_rank == 12
    rhino = next(i for i in p.items if i.item == RHINO)
    assert rhino.category == "Warframe" and rhino.rank == 30 and rhino.mastered and rhino.mastery_xp == 6000
    braton = next(i for i in p.items if i.item == BRATON)
    assert braton.category == "Primary" and braton.rank == 20 and not braton.mastered
    assert p.mastery_xp_from_items == 8000
    assert p.nodes[0].node == "SolNode94" and p.nodes[0].completes == 3
    assert p.affiliations[0].name == "Arbiters" and p.daily_affiliations["Default"] == 16000
    assert p.loadout.warframe == RHINO and p.loadout.focus_school == "AP_POWER"
    assert snap.identity.display_name == "Tester" and snap.identity.account_id == "5" * 24
    assert snap.identity.created_at.year == 2013
    assert "progression" in snap.coverage
    anon = snap.anonymized()
    assert anon.identity.display_name is None and anon.raw == {} and "GuildName" not in anon.stats
    sm = summarize(snap)
    assert sm.mastery_rank == 12 and sm.play_time_h == 2.0 and sm.nodes_done == 1
    assert {c.category: (c.mastered, c.leveling) for c in sm.categories} == {
        "Warframe": (1, 0),
        "Primary": (0, 1),
    }


def test_store_and_diff(tmp_path: Path):
    store = SnapshotStore(tmp_path / "snaps")
    a = parse_profile(_profile(braton_xp=200_000), taken_at=datetime(2026, 10, 15, tzinfo=UTC))
    b = parse_profile(
        _profile(
            braton_xp=450_000,
            nodes=[{"Tag": "SolNode94", "Completes": 4, "Tier": 1}, {"Tag": "SolNode1", "Completes": 1}],
            standing=5000,
        ),
        taken_at=datetime(2026, 10, 16, tzinfo=UTC),
    )
    pa, pb = store.save(a), store.save(b)
    assert [p.name for p in store.list()] == [pa.name, pb.name]
    assert store.latest().taken_at == b.taken_at
    assert store.load("previous").taken_at == a.taken_at
    assert store.load("2026-10-16").taken_at == b.taken_at

    d = diff_snapshots(store.load("previous"), store.load("latest"))
    assert not d.is_empty()
    assert d.newly_mastered == ["Braton"]
    assert d.new_nodes == ["SolNode1 (?)"]
    assert d.new_steel_path_nodes == ["SolNode94 (?)"]
    assert d.standing == [("Arbiters", 4000)]
    assert diff_snapshots(a, a).is_empty()


def test_profile_url_and_config(tmp_path: Path, monkeypatch):
    assert validate_account_id("ABCDEF0123456789ABCDEF01".lower()) == "abcdef0123456789abcdef01"
    assert profile_url("a" * 24, "ps4").startswith("http://content-ps4.warframe.com/")
    monkeypatch.setenv("OPENWARFRAME_HOME", str(tmp_path / "home"))
    s = load_settings()
    assert s.account_id is None
    s.account_id, s.platform = "b" * 24, "xb1"
    save_settings(s)
    s2 = load_settings()
    assert (s2.account_id, s2.platform) == ("b" * 24, "xb1")
    assert isinstance(s2, Settings)
