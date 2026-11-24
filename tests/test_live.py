"""Reward helper: log tailing, event parsing, crop geometry, fuzzy matching, OCR."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from openwarframe.codex.schema import SCHEMA
from openwarframe.live import ocr
from openwarframe.live.eelog import EventParser, LogTailer, parse_lines, watch
from openwarframe.live.match import RewardCatalog, normalize, rank
from openwarframe.live.synthetic import reward_screen

# -- tailer -------------------------------------------------------------------------------


def _append(p: Path, data: bytes) -> None:
    with p.open("ab") as f:
        f.write(data)


def test_tailer_partial_lines_crlf_and_bad_bytes(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    p.write_bytes(b"0.001 Sys [Info]: old line\r\n")
    t = LogTailer(p)  # starts at the end
    assert t.poll() == []
    _append(p, b"1.000 Sys [Info]: first\r\n1.100 Sys [Info]: hal")
    assert t.poll() == ["1.000 Sys [Info]: first"]
    _append(p, b"f done \xff\xfe\r\n")
    assert t.poll() == ["1.100 Sys [Info]: half done ��"]
    assert t.poll() == []


def test_tailer_from_start(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    p.write_bytes(b"a\nb\n")
    assert LogTailer(p, from_start=True).poll() == ["a", "b"]


def test_tailer_missing_file_then_created(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    t = LogTailer(p)
    assert t.poll() == []
    p.write_bytes(b"0.1 Sys [Info]: hello\n")
    assert t.poll() == ["0.1 Sys [Info]: hello"]


def test_tailer_rotation_smaller_file(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    p.write_bytes(b"0.001 Sys [Diag]: build A\n" + b"9.000 Sys [Info]: filler\n" * 50)
    t = LogTailer(p)
    os.remove(p)  # game relaunch: file deleted and written again
    p.write_bytes(b"0.002 Sys [Diag]: build B\n")
    assert t.poll() == ["0.002 Sys [Diag]: build B"]
    assert t.reset and t.resets == 1
    _append(p, b"0.500 Sys [Info]: more\n")
    assert t.poll() == ["0.500 Sys [Info]: more"]
    assert not t.reset


def test_tailer_rotation_larger_file_detected_by_content(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    p.write_bytes(b"0.001 Sys [Diag]: run one\n")
    t = LogTailer(p)
    # truncate and rewrite in place with more data than before (same file id)
    with p.open("r+b") as f:
        f.truncate(0)
        f.write(b"0.001 Sys [Diag]: run two\n" + b"0.002 Sys [Info]: x\n" * 5)
    lines = t.poll()
    assert t.reset
    assert lines[0] == "0.001 Sys [Diag]: run two" and len(lines) == 6


def test_tailer_does_not_reset_on_growth_of_tiny_file(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    p.write_bytes(b"0.1 a\n")
    t = LogTailer(p)
    _append(p, b"0.2 " + b"b" * 200 + b"\n")
    assert len(t.poll()) == 1
    assert not t.reset


# -- parser -------------------------------------------------------------------------------

MISSION = """2540.750 Sys [Info]: Client loaded {"difficulty":0,"name":"SolNode129"} with MissionInfo:
{
    "missionType" : "MT_LANDSCAPE",
    "faction" : "FC_CORPUS",
    "location" : "SolNode129",
    "missionReward" : {
        "credits" : 0
    }
}
2540.800 Sys [Info]: next line""".splitlines()


def test_mission_loaded_from_multiline_json() -> None:
    evs = parse_lines(MISSION)
    assert [e.kind for e in evs] == ["mission_loaded"]
    e = evs[0]
    assert e.time == 2540.75
    assert e.data["node"] == "SolNode129"
    assert e.data["missionType"] == "MT_LANDSCAPE"
    assert e.data["faction"] == "FC_CORPUS"


def test_mission_loaded_at_end_of_input_and_broken_json() -> None:
    lines = [
        '10.0 Sys [Info]: Client loaded {"difficulty":1,"name":"SolNode1"} with MissionInfo:',
        "{",
        '    "missionType" : "MT_EXTERMINATION",',
        '    "faction" : "FC_GRINEER",',  # file ends mid-object
    ]
    (e,) = parse_lines(lines)
    assert (e.data["node"], e.data["missionType"], e.data["faction"]) == (
        "SolNode1",
        "MT_EXTERMINATION",
        "FC_GRINEER",
    )


def test_mission_loaded_without_head() -> None:
    lines = ["3211.239 Sys [Info]: Client loaded  with MissionInfo:", "{", '"location" : "SolNode5"', "}"]
    (e,) = parse_lines(lines)
    assert e.data["node"] == "SolNode5"


# Trimmed from the owner's EE.log, 4-player Lith fissure (Defense), build 2026.10.28.
# Session ids replaced. The second block is the relic *selection* screen between rounds.
FISSURE = """12815.410 Sys [Info]: VoidProjections: OpenVoidProjectionRewardScreenRMI
12815.411 Sys [Info]: Created /Lotus/Interface/ProjectionsCountdown.swf
12815.415 Script [Info]: ProjectionsCountdown.lua: Initialize timer true	5
12815.415 Sys [Info]: Created /Lotus/Interface/ProjectionRewardChoice.swf
12820.412 Script [Info]: ProjectionsCountdown.lua: Countdown timer expired
12820.412 Script [Info]: ProjectionsCountdown.lua: Relic timer closed
12820.412 Script [Info]: ProjectionRewardChoice.lua: Pause countdown done
12820.420 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized
12820.420 Sys [Info]: VoidProjections: GetVoidProjectionRewards
12820.563 Sys [Info]: VoidProjections: Client got reward info from aaaaaaaaaaaaaaaaaaaaaaaa
12820.587 Sys [Info]: VoidProjections: bbbbbbbbbbbbbbbbbbbbbbbb gets reward /Lotus/StoreItems/Types/Recipes/WarframeRecipes/CalibanPrimeChassisBlueprint
12820.879 Sys [Info]: VoidProjections: Client has reward info for all players now
12820.879 Script [Info]: ProjectionsCountdown.lua: Relic timer closed
12820.879 Script [Info]: ProjectionRewardChoice.lua: Got rewards
12820.879 Script [Info]: ProjectionRewardChoice.lua: Missing icon data!
12835.881 Script [Info]: ProjectionsCountdown.lua: Relic timer closed
12835.881 Script [Info]: ProjectionRewardChoice.lua: Selection countdown done
12835.881 Script [Info]: ProjectionRewardChoice.lua: Relic reward screen shut down
12839.335 Script [Info]: ProjectionsCountdown.lua: Relic timer closed
12850.941 Sys [Info]: Created /Lotus/Interface/ProjectionRewardChoice.swf
12850.943 Script [Info]: ProjectionRewardChoice.lua: Relic rewards initialized
12850.943 Script [Info]: ProjectionsCountdown.lua: Relic timer closed
12855.939 Script [Info]: ProjectionRewardChoice.lua: Reward choice force closed
12855.939 Script [Info]: ProjectionRewardChoice.lua: Relic reward screen shut down
12900.000 Net [Info]: MatchingService::EndSession""".splitlines()


def test_real_fissure_sequence() -> None:
    evs = parse_lines(FISSURE)
    assert [e.kind for e in evs] == ["reward_reported", "reward_screen_opened", "reward_screen_closed"]
    rep, opened, closed = evs
    assert rep.data == {
        "player": "bbbbbbbbbbbbbbbbbbbbbbbb",
        "item": "/Lotus/Types/Recipes/WarframeRecipes/CalibanPrimeChassisBlueprint",
    }
    assert opened.time == 12820.879  # "Got rewards", not the earlier "Pause countdown done"
    assert closed.time == 12835.881 and closed.data["marker"] == "Relic reward screen shut down"


def test_login_and_endsession_close() -> None:
    lines = [
        "11.729 Sys [Info]: Logged in SomeTenno",
        "500.0 Script [Info]: ProjectionRewardChoice.lua: Got rewards",
        "500.1 Script [Info]: ProjectionRewardChoice.lua: Got rewards",  # duplicate: ignored
        "510.0 Net [Info]: MatchingService::EndSession",
    ]
    evs = parse_lines(lines)
    assert [e.kind for e in evs] == ["login", "reward_screen_opened", "reward_screen_closed"]
    assert evs[0].data["name"] == "SomeTenno"
    assert evs[2].data["marker"] == "MatchingService::EndSession"


def test_new_mission_closes_open_reward_screen() -> None:
    lines = ["1.0 Script [Info]: ProjectionRewardChoice.lua: Got rewards", *MISSION]
    kinds = [e.kind for e in parse_lines(lines)]
    assert kinds == ["reward_screen_opened", "reward_screen_closed", "mission_loaded"]


def test_parser_reset_event() -> None:
    p = EventParser()
    p.feed("1.0 Script [Info]: ProjectionRewardChoice.lua: Got rewards")
    assert [e.kind for e in p.reset()] == ["log_reset"]
    assert not p.reward_open


def test_watch_follows_file(tmp_path: Path) -> None:
    p = tmp_path / "EE.log"
    p.write_bytes(b"0.1 Sys [Info]: start\n")
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        if calls["n"] == 2:
            _append(p, b"9.0 Script [Info]: ProjectionRewardChoice.lua: Got rewards\n")
        return calls["n"] > 3

    evs = list(watch(p, interval=0.01, should_stop=stop))
    assert [e.kind for e in evs] == ["reward_screen_opened"]


# -- geometry -----------------------------------------------------------------------------


def test_screen_scaling() -> None:
    assert ocr.screen_scaling(1920, 1080) == 1
    assert ocr.screen_scaling(2560, 1440) == pytest.approx(4 / 3)
    assert ocr.screen_scaling(3440, 1440) == pytest.approx(1440 / 1080)  # ultrawide: height decides
    assert ocr.screen_scaling(1920, 1200) == 1  # 16:10: width decides


def test_name_band_1080p_matches_wfinfo() -> None:
    b = ocr.name_band(1920, 1080, pad=0)
    # left = 960 - 968/2; top = 540 - (316-235+48); bottom = 540 - (316-235)/2
    assert (b.left, b.top, b.right, b.bottom) == (476, 411, 1444, 500)


@pytest.mark.parametrize("size", [(1920, 1080), (2560, 1440), (3840, 2160), (3440, 1440), (1280, 720)])
@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_slots_centered_and_equal(size: tuple[int, int], players: int) -> None:
    w, h = size
    boxes = ocr.slot_boxes(w, h, players)
    assert len(boxes) == players
    widths = {b.width for b in boxes}
    assert max(widths) - min(widths) <= 1
    mid = (boxes[0].left + boxes[-1].right) / 2
    assert abs(mid - w / 2) <= 1
    for a, b in zip(boxes, boxes[1:], strict=False):
        assert abs(a.right - b.left) <= 1
    assert all(0 <= b.left < b.right <= w and 0 <= b.top < b.bottom <= h for b in boxes)


def test_ui_scale_shrinks_band() -> None:
    full = ocr.name_band(1920, 1080, 1.0)
    small = ocr.name_band(1920, 1080, 0.75)
    assert small.width < full.width and small.top > full.top


def test_slot_boxes_rejects_bad_count() -> None:
    with pytest.raises(ValueError):
        ocr.slot_boxes(1920, 1080, 5)


def test_read_ui_scale(tmp_path: Path) -> None:
    cfg = tmp_path / "EE.cfg"
    assert ocr.read_ui_scale(cfg) == 1.0
    cfg.write_text("[Section]\nFlash.FlashDrawScale=0.85\n")
    assert ocr.read_ui_scale(cfg) == 0.85


# -- matching -----------------------------------------------------------------------------

P = "/Lotus/Types/Recipes"


@pytest.fixture
def catalog() -> RewardCatalog:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    items = [
        ("/Lotus/Powersuits/Saryn/SarynPrime", "Saryn Prime", "Warframe", None),
        (f"{P}/WarframeRecipes/SarynPrimeChassisComponent", "Saryn Prime Chassis", "Resource", 100),
        ("/Lotus/Weapons/Tenno/BurstonPrime", "Burston Prime", "Primary", None),
        (f"{P}/Weapons/WeaponParts/BurstonPrimeBarrel", "Burston Prime Barrel", "Resource", 45),
        ("/Lotus/Weapons/Tenno/LexPrime", "Lex Prime", "Secondary", None),
        (f"{P}/Weapons/WeaponParts/LexPrimeBarrel", "Lex Prime Barrel", "Resource", 15),
        ("/Lotus/Types/Items/MiscItems/Forma", "Forma", "Resource", None),
    ]
    for uid, name, cat, ducats in items:
        data = json.dumps({"primeSellingPrice": ducats} if ducats else {})
        conn.execute(
            "INSERT INTO item (unique_name, name, category, data) VALUES (?,?,?,?)", (uid, name, cat, data)
        )
    recipes = [
        (
            f"{P}/WarframeRecipes/SarynPrimeChassisBlueprint",
            f"{P}/WarframeRecipes/SarynPrimeChassisComponent",
        ),
        (f"{P}/WarframeRecipes/SarynPrimeBlueprint", "/Lotus/Powersuits/Saryn/SarynPrime"),
        (f"{P}/Weapons/BurstonPrimeBlueprint", "/Lotus/Weapons/Tenno/BurstonPrime"),
        (f"{P}/Weapons/LexPrimeBlueprint", "/Lotus/Weapons/Tenno/LexPrime"),
        (f"{P}/Components/FormaBlueprint", "/Lotus/Types/Items/MiscItems/Forma"),
    ]
    conn.executemany("INSERT INTO recipe (unique_name, result_item) VALUES (?,?)", recipes)
    conn.executemany(
        "INSERT INTO recipe_ingredient (recipe, item, count) VALUES (?,?,1)",
        [
            (f"{P}/WarframeRecipes/SarynPrimeBlueprint", f"{P}/WarframeRecipes/SarynPrimeChassisComponent"),
            (f"{P}/Weapons/BurstonPrimeBlueprint", f"{P}/Weapons/WeaponParts/BurstonPrimeBarrel"),
            (f"{P}/Weapons/LexPrimeBlueprint", f"{P}/Weapons/WeaponParts/LexPrimeBarrel"),
        ],
    )
    relic_old = "/Lotus/Types/Game/Projections/T1VoidProjectionOldBronze"
    relic_new = "/Lotus/Types/Game/Projections/T1VoidProjectionNewBronze"
    conn.executemany(
        "INSERT INTO relic (unique_name, name, tier) VALUES (?,?,?)",
        [(relic_old, "Lith S1", "Lith"), (relic_new, "Lith B9", "Lith")],
    )
    conn.executemany(
        "INSERT INTO relic_reward (relic, item, rarity) VALUES (?,?,?)",
        [
            (relic_old, f"{P}/WarframeRecipes/SarynPrimeChassisBlueprint", "RARE"),
            (relic_new, f"{P}/Weapons/WeaponParts/BurstonPrimeBarrel", "UNCOMMON"),
            (relic_new, f"{P}/Weapons/WeaponParts/LexPrimeBarrel", "COMMON"),
            (relic_new, f"{P}/Components/FormaBlueprint", "COMMON"),
        ],
    )
    conn.execute(
        "INSERT INTO node_reward (planet, place, rotation, item_name, item) VALUES ('Earth','x','A','Lith B9',?)",
        (relic_new,),
    )
    conn.execute(
        "INSERT INTO market_item (unique_name, slug, name) VALUES (?,?,?)",
        (
            f"{P}/WarframeRecipes/SarynPrimeChassisBlueprint",
            "saryn_prime_chassis_blueprint",
            "Saryn Prime Chassis Blueprint",
        ),
    )
    return RewardCatalog.from_codex(conn)


def test_catalog_names_and_facts(catalog: RewardCatalog) -> None:
    by = {e.name: e for e in catalog.entries}
    assert set(by) == {
        "Saryn Prime Chassis Blueprint",
        "Burston Prime Barrel",
        "Lex Prime Barrel",
        "Forma Blueprint",
    }
    saryn = by["Saryn Prime Chassis Blueprint"]
    assert saryn.vaulted and saryn.ducats == 100 and saryn.final_name == "Saryn Prime"
    assert saryn.slug == "saryn_prime_chassis_blueprint"
    assert not by["Burston Prime Barrel"].vaulted
    assert by["Burston Prime Barrel"].final_item == "/Lotus/Weapons/Tenno/BurstonPrime"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SARYN PRIME CHASSIS BLUEPRINT", "Saryn Prime Chassis Blueprint"),
        ("Saryn Pr1me Chass1s Blueprlnt", "Saryn Prime Chassis Blueprint"),
        ("Saryn Prime Chassis", "Saryn Prime Chassis Blueprint"),  # second line cut off
        ("Burston Prirne Barre1", "Burston Prime Barrel"),
        ("Lex Prime Barre|", "Lex Prime Barrel"),
        ("F0RMA BLUEPR1NT", "Forma Blueprint"),
        ("  forma\nblueprint ", "Forma Blueprint"),
    ],
)
def test_match_noisy(catalog: RewardCatalog, raw: str, expected: str) -> None:
    m = catalog.match(raw)
    assert m.entry is not None and m.entry.name == expected


@pytest.mark.parametrize("raw", ["", "   ", "Void Traces", "xq"])
def test_match_rejects_garbage(catalog: RewardCatalog, raw: str) -> None:
    assert catalog.match(raw).entry is None


def test_normalize() -> None:
    assert normalize(" Lex  Prime\nBarre|!") == "LEX PRIME BARREI"


def test_rank_order(catalog: RewardCatalog) -> None:
    ms = catalog.match_all(
        [
            "Forma Blueprint",
            "Lex Prime Barrel",
            "Saryn Prime Chassis Blueprint",
            "???",
            "Burston Prime Barrel",
        ]
    )
    prices = {"lex prime barrel": 9, "Burston Prime Barrel": 4}
    # nothing needed: vaulted Saryn first, then by platinum, then Forma, unknown last
    names = [r.match.entry.name if r.match.entry else None for r in rank(ms, prices=prices)]
    assert names == [
        "Saryn Prime Chassis Blueprint",
        "Lex Prime Barrel",
        "Burston Prime Barrel",
        "Forma Blueprint",
        None,
    ]
    # Burston Prime not mastered: its barrel jumps to the top
    ranked = rank(ms, prices=prices, needed_items={"/Lotus/Weapons/Tenno/BurstonPrime"})
    assert ranked[0].match.entry.name == "Burston Prime Barrel" and ranked[0].needed
    assert "needed for Burston Prime" in ranked[0].reason
    # ...unless the barrel is already in the inventory
    ranked = rank(
        ms,
        needed_items={"/Lotus/Weapons/Tenno/BurstonPrime"},
        owned_parts={f"{P}/Weapons/WeaponParts/BurstonPrimeBarrel": 1},
    )
    assert not any(r.needed for r in ranked)


def test_pick_layout_prefers_fully_matched(catalog: RewardCatalog) -> None:
    layouts = {
        4: ["Saryn Prime", "Chassis Blueprint Burston", "Prime Barrel Lex", "Prime Barrel"],
        3: ["Saryn Prime Chassis Blueprint", "Burston Prime Barrel", "Lex Prime Barrel"],
        2: ["Prime Chassis Blueprint Burston", "Barrel Lex Prime"],
        1: ["Burston Prime Barrel"],
    }
    n, ms = catalog.pick_layout(layouts)
    assert n == 3 and [m.entry.name for m in ms] == [
        "Saryn Prime Chassis Blueprint",
        "Burston Prime Barrel",
        "Lex Prime Barrel",
    ]


# -- OCR (Windows only) -------------------------------------------------------------------

needs_ocr = pytest.mark.skipif(not ocr.ocr_available(), reason="Windows OCR (winrt) not available")


@needs_ocr
@pytest.mark.parametrize("size", [(1920, 1080), (2560, 1440)])
def test_ocr_synthetic_screen(catalog: RewardCatalog, size: tuple[int, int]) -> None:
    from openwarframe.live.reward import analyze

    names = ["Saryn Prime Chassis Blueprint", "Burston Prime Barrel", "Forma Blueprint"]
    a = analyze(reward_screen(names, size), catalog)
    assert a.players == 3
    assert [m.entry.name for m in a.matches] == names
