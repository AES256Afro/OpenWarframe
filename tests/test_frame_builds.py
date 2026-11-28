"""Warframe builds: ability facts, mod stats, weights, effective health and the search."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from itertools import combinations
from pathlib import Path

import pytest

from openwarframe.builds import frames

ROOT = Path(__file__).parents[1]


def mod(name, lines, drain=4, rank=None):
    return frames.FrameMod("/F/" + name, name, drain, 0, [lines], frames.frame_exclusive_key(name))


def frame(**kw):
    abilities = kw.pop("abilities", None) or [
        {"key": 1, "ability": "One", "strength": True, "duration": True, "range": False, "energy": 25, "channeled": False},
        {"key": 2, "ability": "Two", "strength": True, "duration": False, "range": True, "energy": 50, "channeled": False},
        {"key": 4, "ability": "Four", "strength": True, "duration": False, "range": True, "energy": 25, "channeled": True},
    ]  # fmt: skip
    base = dict(name="Testframe", unique_name="/W", health=300.0, shields=300.0, armor=300.0, energy=150.0)
    base.update(kw)
    return frames.Frame(abilities=abilities, **base)


def test_mod_stats_and_variants():
    assert mod("Blind Rage", ["+99% Ability Strength", "-55% Ability Efficiency"]).stats() == {
        "strength": 0.99,
        "efficiency": -0.55,
    }
    assert (
        mod(
            "Adaptation", ["When Damaged:", "+10% Resistance to that Damage Type for 20s. Stacks up to 90%."]
        ).stats()
        == {}
    )
    assert frames.frame_exclusive_key("Umbral Intensify") == frames.frame_exclusive_key("Intensify")
    assert frames.frame_exclusive_key("Archon Vitality") == "Vitality"
    assert frames.frame_exclusive_key("Primed Continuity") == "Continuity"


def test_weights_follow_the_abilities_you_use():
    f = frame()
    w = frames.weights_for(f, None)
    # strength: 3 abilities; duration: 1 + 1 channeled; range: 2; efficiency: 3 cost + 1 channeled
    assert (w.strength, w.duration, w.range, w.efficiency) == (3, 2, 2, 4)
    w = frames.weights_for(f, [2])
    assert (w.strength, w.duration, w.range, w.efficiency) == (1, 0, 1, 1)
    assert frames.weights_for(f, None, "none").survivability == 0


def test_totals_and_effective_health():
    f = frame()
    t = frames.totals(f, [(mod("Vitality", ["+100% Health"]), 0), (mod("Steel Fiber", ["+100% Armor"]), 0)])
    # health 600, armor 600: 600 x (600 + 300) / 300 + 300 shields = 2100
    assert t["effective_health"] == pytest.approx(2100) and t["damage_reduction"] == pytest.approx(600 / 900)
    t = frames.totals(f, [(mod("Streamline", ["+130% Ability Efficiency"]), 0)])
    assert t["energy_cost"] == pytest.approx(0.25)  # efficiency caps at 175%: cost floor 25%


def test_search_matches_trying_every_combination():
    f = frame()
    pool = [
        (mod("Intensify", ["+30% Ability Strength"]), 0),
        (mod("Transient Fortitude", ["+55% Ability Strength", "-27.5% Ability Duration"]), 0),
        (mod("Blind Rage", ["+99% Ability Strength", "-55% Ability Efficiency"]), 0),
        (mod("Continuity", ["+30% Ability Duration"]), 0),
        (mod("Stretch", ["+45% Ability Range"]), 0),
        (mod("Overextended", ["+90% Ability Range", "-60% Ability Strength"]), 0),
        (mod("Streamline", ["+30% Ability Efficiency"]), 0),
        (mod("Fleeting Expertise", ["+60% Ability Efficiency", "-60% Ability Duration"]), 0),
        (mod("Vitality", ["+100% Health"]), 0),
        (mod("Steel Fiber", ["+100% Armor"]), 0),
        (mod("Umbral Intensify", ["+44% Ability Strength"]), 0),  # can't sit next to Intensify
    ]
    w = frames.weights_for(f, None)
    base = frames.totals(f, [])["effective_health"]
    found = frames.search(f, w, pool)
    best = max(  # every size up to 8: an empty slot beats a mod that only hurts
        frames.score(f, w, list(c), base)
        for k in range(1, 9)
        for c in combinations(pool, k)
        if len({m.exclusive for m, _ in c}) == k
    )
    assert frames.score(f, w, found, base) == pytest.approx(best)
    names = {m.name for m, _ in found}
    assert not {"Intensify", "Umbral Intensify"} <= names


def test_kb_file_is_consistent():
    data = json.loads((ROOT / "kb/builds/abilities.json").read_text(encoding="utf-8"))
    assert "CC BY-NC-SA" in data["license"] and data["last_verified"]
    by_name = {a["ability"] for a in data["abilities"]}
    warframes = [f for f in data["frames"] if f["unique_name"].startswith("/Lotus/Powersuits/")]
    assert len(warframes) > 100
    missing = [(f["frame"], a) for f in warframes for a in f["abilities"] if a not in by_name]
    assert len(missing) <= 6, missing  # Archwing and Octavia's Amp only
    saryn = next(f for f in data["frames"] if f["frame"] == "Saryn Prime")
    assert saryn["abilities"] == ["Spores", "Molt", "Toxic Lash", "Miasma"] and saryn["armor"] > 0
    f = frames.load_frame("/Lotus/Powersuits/Rhino/Rhino", data)
    assert [a["ability"] for a in f.abilities] == ["Rhino Charge", "Iron Skin", "Roar", "Rhino Stomp"]
    with pytest.raises(frames.NotAFrame):
        frames.load_frame("/Lotus/Nope", data)


def test_generator_reads_an_ability_template(tmp_path: Path):
    sys.path.insert(0, str(ROOT / "tools"))
    import ability_scaling

    t = ability_scaling.template(
        "{{AbilityU10.3\n| name = Miasma\n| energy = 75\n| strength = 110 / 150\n| range = 10 / 20 m\n"
        "| duration = 6 s\n| misc = 100%\n|info = text\n}}"
    )
    assert t["strength"] and t["range"] and t["duration"] and t["energy"] == "75"


def test_suggest_and_endpoint(tmp_path: Path):
    from openwarframe.app.server import AppState, page_source
    from openwarframe.codex.schema import SCHEMA
    from openwarframe.config import Settings

    con = sqlite3.connect(tmp_path / "codex.sqlite")
    con.executescript(SCHEMA)

    def add(uid, name, lines, drain=4):
        d = {
            "type": "WARFRAME",
            "compatName": "WARFRAME",
            "baseDrain": drain,
            "fusionLimit": 0,
            "levelStats": [{"stats": lines}],
        }
        con.execute(
            "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
            (uid, name, "Mod", None, None, None, None, json.dumps(d)),
        )

    add("/M/Intensify", "Intensify", ["+30% Ability Strength"])
    add("/M/Vitality", "Vitality", ["+440% Health"])
    con.commit()
    con.close()
    b = frames.suggest_frame(sqlite3.connect(tmp_path / "codex.sqlite"), "/Lotus/Powersuits/Saryn/SarynPrime")
    assert b["frame"] == "Saryn Prime" and {m["name"] for m in b["mods"]} == {"Intensify", "Vitality"}
    assert b["stats"]["strength"] == pytest.approx(1.3) and b["abilities"][3]["name"] == "Miasma"
    state = AppState(Settings(home=tmp_path))
    r = state.frame_build_for(
        "/Lotus/Powersuits/Saryn/SarynPrime", abilities=[4], survivability="none", owned_only=False
    )
    assert [a["used"] for a in r["abilities"]] == [False, False, False, True]
    assert "error" in state.frame_build_for(
        "/Lotus/Nope", abilities=None, survivability="some", owned_only=False
    )
    page = page_source()
    assert (
        "function frameBuildPanel(r)" in page
        and '"/api/frame-build?id="' in page
        and "function fChosen(id)" in page
    )
    assert not math.isnan(b["stats"]["effective_health"])


def aura(name, line, base=-2, max_rank=5):
    return frames.FrameMod("/A/" + name, name, base, max_rank, [[line]] * (max_rank + 1), name, aura=True)


def test_auras_add_capacity_and_count_own_stats():
    phys = aura("Physique", "Squad gains +20% Maximum Health")
    assert phys.stats() == {"health": pytest.approx(0.2)}
    assert phys.drain() == -7 and phys.aura_capacity() == 14  # double its drain, matching polarity
    assert aura("Stand United", "Squad receives +25% Armor").stats() == {"armor": pytest.approx(0.25)}
    assert aura(
        "Power Donation",
        "You lose <LOWER_IS_BETTER>30% Ability Strength\r\nSquadmates gain 30% Ability Strength",
        base=-4,
    ).stats() == {"strength": pytest.approx(-0.3)}
    assert aura("Corrosive Projection", "Enemies lose -18% Armor").stats() == {}
    f = frame()
    w = frames.weights_for(f, None, "some")
    pick = frames.pick_aura(f, w, [(aura("Corrosive Projection", "Enemies lose -18% Armor"), 5), (phys, 5)])
    assert pick[0].name == "Physique"  # helps your own health; same capacity otherwise
    big = aura("Steel Charge", "Squad receives +60% Melee Damage", base=-4)
    small = aura("Sprint Boost", "Squad receives +15% Sprint Speed")
    pick = frames.pick_aura(f, w, [(small, 5), (big, 5)])
    assert pick[0].name == "Steel Charge" and pick[0].aura_capacity(5) == 18  # no stat effect: most capacity


def test_exilus_slot_takes_one_utility_mod():
    gen = [(mod(f"G{i}", ["+10% Ability Strength"], drain=2), 0) for i in range(8)]
    drift = (
        frames.FrameMod(
            "/F/Cunning Drift", "Cunning Drift", 2, 0, [["+15% Ability Range"]], "Cunning Drift", utility=True
        ),
        0,
    )
    extra = (mod("G9", ["+10% Ability Strength"], drain=2), 0)
    assert frames._ok([*gen, drift])  # 8 general + 1 in the Exilus slot
    assert not frames._ok([*gen, extra])  # a 9th general mod has no slot
    assert frames.exilus_of([*gen, drift]) == drift
    assert frames.frame_exclusive_key("Umbral Fiber") == frames.frame_exclusive_key("Steel Fiber")


def test_suggest_reports_aura_and_exilus(tmp_path: Path):
    from openwarframe.codex.schema import SCHEMA

    con = sqlite3.connect(tmp_path / "c.sqlite")
    con.executescript(SCHEMA)

    def add(uid, name, lines, drain=4, kind="WARFRAME", utility=False, rank=0):
        d = {"type": kind, "compatName": kind, "baseDrain": drain, "fusionLimit": rank,
             "levelStats": [{"stats": lines}] * (rank + 1), "isUtility": utility}  # fmt: skip
        con.execute(
            "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
            (uid, name, "Mod", None, None, None, None, json.dumps(d)),
        )

    add("/M/Intensify", "Intensify", ["+30% Ability Strength"])
    add("/M/Drift", "Cunning Drift", ["+15% Ability Range"], utility=True)
    add("/A/Physique", "Physique", ["Squad gains +20% Maximum Health"], drain=-2, kind="AURA", rank=5)
    b = frames.suggest_frame(con, "/Lotus/Powersuits/Saryn/SarynPrime")
    assert b["aura"]["name"] == "Physique" and b["aura"]["capacity"] == 14 and b["capacity"] == 74
    assert [m["name"] for m in b["mods"] if m["exilus"]] == ["Cunning Drift"]
    assert b["stats"]["health"] == pytest.approx(365 * 1.2)


# -- Archon Shards and augments (wiki Archon_Shard, edited 2026-11-21) -----------------------


def test_shards_add_percent_to_mods_and_flat_after():
    f = frame()
    extra = frames.shard_effects(["strength", "health", "armor"], tauforged=False)
    assert extra == {"strength": 0.10, "health_flat": 150.0, "armor_flat": 150.0}
    t = frames.totals(f, [(mod("Vitality", ["+100% Health"]), 0)], extra)
    assert t["strength"] == pytest.approx(1.10)
    assert t["health"] == pytest.approx(300 * 2 + 150)  # flat after the mod's percentage
    assert t["armor"] == pytest.approx(450)
    assert frames.shard_effects(["duration"], tauforged=True) == {"duration": pytest.approx(0.15)}


def test_best_shards_follow_the_weights_and_your_shards():
    f = frame()
    tanky = frames.weights_for(f, [2], "tanky")
    picks = frames.best_shards(f, tanky, [], tauforged=False)
    assert len(picks) == 5
    # without Crimson shards, only Azure stats can be picked
    only_azure = frames.best_shards(
        f, frames.weights_for(f, None, "none"), [], False, {"Azure": 2, "Crimson": 0}
    )
    assert len(only_azure) <= 2 and all(frames.SHARD_STATS[x][0] == "Azure" for x in only_azure)
    assert frames.best_shards(f, tanky, [], False, {}) == []


def test_augments_load_and_lock_in(tmp_path: Path):
    from openwarframe.codex.schema import SCHEMA

    con = sqlite3.connect(tmp_path / "c.sqlite")
    con.executescript(SCHEMA)

    def add(uid, name, lines, compat="WARFRAME", drain=4, utility=False):
        d = {"type": "WARFRAME", "compatName": compat, "baseDrain": drain, "fusionLimit": 0,
             "levelStats": [{"stats": lines}], "isUtility": utility}  # fmt: skip
        con.execute(
            "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
            (uid, name, "Mod", None, None, None, None, json.dumps(d)),
        )

    for i in range(9):
        add(f"/M/S{i}", f"Strong{i}", ["+30% Ability Strength"])
    add(
        "/Saryn/Venom",
        "Venom Dose",
        ["Spores Augment: Hold to cast will grant allies more <DT_CORROSIVE_COLOR>Corrosive."],
        "Saryn",
        6,
    )
    add("/Saryn/Cloud", "Contagion Cloud", ["Toxic Lash Augment : Create toxic clouds."], "Saryn", 6)
    add("/Rhino/Roar", "Piercing Roar", ["Roar Augment: Roar gains range."], "Rhino", 6)
    augs = frames.load_augments(con, "Saryn Prime")  # augments name the base frame
    assert [(a.name, a.augment_for) for a in augs] == [
        ("Venom Dose", "Spores"),
        ("Contagion Cloud", "Toxic Lash"),
    ]
    assert augs[0].text == "Hold to cast will grant allies more Corrosive."
    b = frames.suggest_frame(con, "/Lotus/Powersuits/Saryn/SarynPrime", augments=["/Saryn/Venom"])
    names = [m["name"] for m in b["mods"]]
    assert "Venom Dose" in names and len(names) == 8  # 7 stat mods fill the rest
    assert {a["name"]: a["chosen"] for a in b["augments"]} == {"Venom Dose": True, "Contagion Cloud": False}
    assert next(m for m in b["mods"] if m["name"] == "Venom Dose")["augment"] == "Spores"
    # owned mode: an augment you don't have is still put in when you tick it, and marked
    b = frames.suggest_frame(
        con,
        "/Lotus/Powersuits/Saryn/SarynPrime",
        augments=["/Saryn/Cloud"],
        owned={"/M/S1": 0},
        shards="regular",
        owned_shards={},
    )
    cloud = next(m for m in b["mods"] if m["name"] == "Contagion Cloud")
    assert cloud["owned"] is False and b["shards"] == []


def test_page_has_shards_and_augments():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'data-fopt="shards"' in page and "data-faug" in page and "&shards=" in page
