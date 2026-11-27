"""Weapon builds: mod text parsing, the damage formulas (worked by hand), compatibility, search."""

from __future__ import annotations

import json
import sqlite3
from itertools import combinations
from pathlib import Path

import pytest

from openwarframe.builds import damage, mods, search
from openwarframe.builds.weapons import Gun, load_gun


def gun(**kw) -> Gun:
    base = dict(
        unique_name="/G", name="Testgun", slot="PRIMARY", holster="RIFLE", parent=None,
        damage={"impact": 100.0}, crit_chance=0.2, crit_multiplier=2.0, status_chance=0.1,
        fire_rate=10.0, multishot=1.0, magazine=30, reload=2.0,
    )  # fmt: skip
    base.update(kw)
    return Gun(**base)


def eff(**stats) -> mods.ModEffect:
    return mods.ModEffect(stats=dict(stats))


@pytest.mark.parametrize(
    ("line", "want"),
    [
        ("+165% Damage", ("damage", 1.65)),
        ("+90% <DT_FIRE_COLOR>Heat", ("heat", 0.9)),
        ("+120% <DT_IMPACT_COLOR>Impact", ("impact", 1.2)),
        ("x1.55 Damage to Grineer", ("bane:Grineer", 0.55)),
        ("x1.3 Damage to The Murmur", ("bane:Murmur", 0.3)),
        ("-20% Fire Rate", ("fire_rate", -0.2)),
        ("+60% Fire Rate (x2 for Bows)", ("fire_rate", 0.6)),
        ("-50% Accuracy", None),
        ("+1.5 Punch Through", None),
    ],
)
def test_parse_line(line, want):
    got = mods.parse_line(line)
    assert got is None if want is None else (got[0] == want[0] and abs(got[1] - want[1]) < 1e-9)


def test_conditional_effects_are_kept_apart():
    e = mods.parse_effect(["+80% Multishot", "On Kill:", "+30% Multishot for 20s. Stacks up to 5x."])
    assert e.stats == {"multishot": 0.8} and e.stacks == {"multishot": (0.3, 5)}
    e = mods.parse_effect(
        [
            "+80% Status Chance",
            "On Kill:",
            "+40% Direct Damage per Status Type affecting the target for 20s. Stacks up to 2x.",
        ]
    )
    assert e.stats == {"status_chance": 0.8} and e.stacks == {} and e.conditional
    e = mods.parse_effect(["+120% Critical Chance when Aiming for 12s"])
    assert e.stats == {} and e.conditional


def test_hand_worked_damage():
    g = gun()
    # 100 impact, Serration +165%: 265 per projectile; crit avg 1 + 0.2 x (2 - 1) = 1.2 -> 318
    r = damage.evaluate(g, damage.add_up([eff(damage=1.65)], stacks=False))
    assert r.per_shot == pytest.approx(318)
    # sustained: 318 x 10 x 30 / (10 x 2 + 30) = 1908
    assert r.sustained_dps == pytest.approx(1908)
    # Grineer take x1.5 from impact; Primed Bane of Grineer x1.55 on top
    t = damage.add_up([eff(damage=1.65), eff(**{"bane:Grineer": 0.55})], stacks=False)
    assert damage.evaluate(g, t, "Grineer").per_shot == pytest.approx(318 * 1.5 * 1.55)
    assert damage.evaluate(g, t, "Corpus").per_shot == pytest.approx(318)  # bane for another faction
    # crit and multishot: CC 0.2 x 3 = 0.6, CD 2 x 2 = 4 -> 1 + 0.6 x 3 = 2.8; multishot 1 x 1.9
    t = damage.add_up([eff(crit_chance=2.0, crit_damage=1.0, multishot=0.9)], stacks=False)
    assert damage.evaluate(g, t).per_shot == pytest.approx(100 * 2.8 * 1.9)


def test_elements_combine_in_slot_order_with_innate_last():
    g = gun(damage={"impact": 50.0, "toxin": 50.0})
    # electricity from a mod (slot 1) + innate toxin (last) -> corrosive, on the modded base
    t = damage.add_up([eff(damage=1.0), eff(electricity=0.9)], stacks=False)
    el = damage.element_damage(g, t, 2.0)
    assert set(el) == {"corrosive"} and el["corrosive"] == pytest.approx(100 * 2 * 0.9 + 50 * 2)
    # heat, cold, toxin in that order: heat+cold -> blast, toxin stays
    t = damage.add_up([eff(heat=0.6), eff(cold=0.6), eff(toxin=0.6)], stacks=False)
    el = damage.element_damage(gun(damage={"impact": 100.0}), t, 1.0)
    assert el == pytest.approx({"blast": 120.0, "toxin": 60.0})
    # an innate combined element never combines further
    el = damage.element_damage(
        gun(damage={"blast": 100.0}), damage.add_up([eff(heat=1.0)], stacks=False), 1.0
    )
    assert el == pytest.approx({"blast": 100.0, "heat": 100.0})


def test_best_order_picks_the_combination_the_target_is_weak_to():
    g = gun(damage={"impact": 100.0})
    t = damage.add_up([eff(cold=0.9), eff(heat=0.9), eff(electricity=0.9), eff(toxin=0.9)], stacks=False)
    r, order = damage.best_order(g, t, "Grineer")
    assert "corrosive" in r.by_type  # electricity + toxin: Grineer take x1.5


def test_fits_and_clashes():
    def m(name, compat, slot="PRIMARY", **kw):
        return mods.GunMod(
            "/M/" + name,
            name,
            compat,
            slot,
            None,
            4,
            10,
            "RARE",
            [[]],
            exclusive=mods.exclusive_key(name),
            **kw,
        )

    rifle = mods.WeaponClass("PRIMARY", "RIFLE", None, "Braton Prime")
    bow = mods.WeaponClass("PRIMARY", "BOW", None, "Paris Prime")
    shotgun = mods.WeaponClass("PRIMARY", "SHOTGUN", None, "Hek")
    semi = mods.WeaponClass("PRIMARY", "RIFLE", None, "Latron", ("SEMI_AUTO",))
    assert mods.fits(m("Serration", "Rifle"), bow) and not mods.fits(m("Serration", "Rifle"), shotgun)
    assert mods.fits(m("Point Blank", "Shotgun"), shotgun) and not mods.fits(
        m("Hornet Strike", "Pistol", "SECONDARY"), rifle
    )
    cannonade = m("Semi-Rifle Cannonade", "Rifle", needs_tags=("SEMI_AUTO",))
    assert mods.fits(cannonade, semi) and not mods.fits(cannonade, rifle)
    assert mods.fits(
        m("Scattered Justice", "Hek"), mods.WeaponClass("PRIMARY", "SHOTGUN", None, "Vaykor Hek")
    )
    assert search.clash(m("Galvanized Chamber", "Rifle"), m("Split Chamber", "Rifle"))
    assert search.clash(m("Primed Cryo Rounds", "Rifle"), m("Cryo Rounds", "Rifle"))
    assert not search.clash(m("Serration", "Rifle"), m("Heavy Caliber", "Rifle"))


def test_forma_count():
    def p(drain):
        mod = mods.GunMod("/x", "x", "Rifle", "PRIMARY", None, drain, 0, "RARE", [[]])
        return search.Pick(mod, 0, mods.ModEffect(), None)

    assert search.forma_needed([p(10)] * 6) == 0  # 60 fits
    assert search.forma_needed([p(16)] * 4) == 1  # 64 -> polarize one: 56
    assert search.forma_needed([p(20)] * 8) is None  # 160 -> at best 80, never fits


def test_search_matches_trying_every_combination():
    g = gun(damage={"impact": 30.0, "puncture": 30.0, "slash": 40.0}, crit_chance=0.3, crit_multiplier=2.5)
    pool_mods = {
        "Serration": eff(damage=1.65), "Split Chamber": eff(multishot=0.9), "Point Strike": eff(crit_chance=1.5),
        "Vital Sense": eff(crit_damage=1.2), "Hellfire": eff(heat=0.9), "Cryo Rounds": eff(cold=0.9),
        "Infected Clip": eff(toxin=0.9), "Stormbringer": eff(electricity=0.9), "Speed Trigger": eff(fire_rate=0.6),
        "Magazine Warp": eff(magazine=0.3), "Rupture": eff(impact=1.2),
    }  # fmt: skip
    pool = [
        search.Pick(
            mods.GunMod("/" + n, n, "Rifle", "PRIMARY", None, 4, 10, "RARE", [[]], exclusive=n), 10, e, None
        )
        for n, e in pool_mods.items()
    ]
    found = search.search(g, pool, "Grineer", stacks=False)
    best = max(
        (search._score(g, list(c), "Grineer", False)[0] for c in combinations(pool, 8)),
    )
    assert search._score(g, found, "Grineer", False)[0] == pytest.approx(best)


def _db(tmp_path: Path) -> sqlite3.Connection:
    from openwarframe.codex.schema import SCHEMA

    con = sqlite3.connect(tmp_path / "c.sqlite")
    con.executescript(SCHEMA)
    gun_data = {
        "name": "Testgun", "productCategory": "LongGuns", "damagePerShot": [100] + [0] * 19,
        "criticalChance": 0.2, "criticalMultiplier": 2, "procChance": 0.1, "fireRate": 10,
        "multishot": 1, "magazineSize": 30, "reloadTime": 2, "trigger": "AUTO",
    }  # fmt: skip
    con.execute(
        "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
        ("/G", "Testgun", "Primary", "LongGuns", 0, None, None, json.dumps(gun_data)),
    )
    con.execute("INSERT INTO weapon_class VALUES ('/G', 'RIFLE', NULL, '[]')")

    def mod(uid, name, stats, compat="Rifle", drain=4):
        d = {"type": "PRIMARY", "compatName": compat, "baseDrain": drain, "fusionLimit": len(stats) - 1,
             "rarity": "RARE", "levelStats": [{"stats": s} for s in stats]}  # fmt: skip
        con.execute(
            "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
            (uid, name, "Mod", None, None, None, None, json.dumps(d)),
        )

    mod("/M/Serration", "Serration", [["+15% Damage"], ["+165% Damage"]])
    mod("/M/Split", "Split Chamber", [["+15% Multishot"], ["+90% Multishot"]])
    mod("/M/Hell", "Hell's Chamber", [["+120% Multishot"]], compat="Shotgun")
    mod("/M/Bane", "Primed Bane of Grineer", [["x1.55 Damage to Grineer"]])
    mod("/M/Expert/Fake", "Serration", [["+999% Damage"]])  # unreleased copy: ignored
    return con


def test_suggest_end_to_end(tmp_path: Path):
    con = _db(tmp_path)
    b = search.suggest(con, "/G", target="Grineer")
    names = [m["name"] for m in b["mods"]]
    assert set(names) == {"Serration", "Split Chamber", "Primed Bane of Grineer"}  # no shotgun mod
    # 100 x 2.65 x 1.9 x 1.2 crit x 1.5 impact vs Grineer x 1.55 bane
    assert b["stats"]["per_shot"] == pytest.approx(100 * 2.65 * 1.9 * 1.2 * 1.5 * 1.55)
    # only my mods: without Split Chamber, and it's named as the best one to get
    b = search.suggest(con, "/G", target="Grineer", owned={"/M/Serration": 1, "/M/Bane": 0})
    assert {m["name"] for m in b["mods"]} == {"Serration", "Primed Bane of Grineer"}
    assert b["upgrade"]["name"] == "Split Chamber" and b["upgrade"]["gain"] == "+90%"
    assert any("not counted" in n.lower() for n in b["notes"])


def test_not_a_gun(tmp_path: Path):
    con = _db(tmp_path)
    from openwarframe.builds.weapons import NotAGun

    with pytest.raises(NotAGun):
        load_gun(con, "/M/Serration")
    con.execute("DROP TABLE weapon_class")
    with pytest.raises(NotAGun, match="Update the game data"):
        load_gun(con, "/G")


def test_endpoint_and_page(tmp_path: Path, monkeypatch):
    from openwarframe.app.server import AppState, page_source
    from openwarframe.config import Settings

    con = _db(tmp_path)
    con.commit()
    con.close()
    (tmp_path / "c.sqlite").rename(tmp_path / "codex.sqlite")
    state = AppState(Settings(home=tmp_path))
    b = state.build_for("/G", target="Corpus", owned_only=False, stacks=True)
    assert b["weapon"] == "Testgun" and len(b["mods"]) == 2  # bane doesn't help against Corpus
    assert "error" in state.build_for("/M/Serration", target=None, owned_only=False, stacks=True)
    page = page_source()
    assert "function buildPanel(r)" in page and '"/api/build?id="' in page


# -- armor and status (wiki Armor, Enemy_Level_Scaling, Damage/<Type>_Damage) ---------------


def test_armor_scaling_and_reduction():
    from openwarframe.builds.enemy import armor_reduction, enemy_for, scale_armor

    assert scale_armor(500, 8, 8) == 500
    # q = 27: f1 = 1 + 0.005 x 27^1.75; below the 70-80 blend
    assert scale_armor(500, 8, 35) == pytest.approx(500 * (1 + 0.005 * 27**1.75))
    assert scale_armor(500, 8, 135) == 2700  # capped
    assert scale_armor(10, 1, 1) == 200  # floor
    assert armor_reduction(2700) == pytest.approx(0.9) and armor_reduction(300) == pytest.approx(0.3)
    assert armor_reduction(0) == 0
    assert enemy_for("Grineer", "sp").armor == 2700 and enemy_for("Corpus", "sp").armor == 0
    assert enemy_for("Grineer", "none").armor == 0 and enemy_for("Grineer", "sp", stripped=True).stripped


def test_armor_cuts_direct_damage_and_slash_bleeds_through():
    from openwarframe.builds.enemy import Enemy

    g = gun(damage={"slash": 100.0}, crit_chance=0.0, status_chance=0.0)
    t = damage.add_up([], stacks=False)
    plain = damage.evaluate(g, t, None)
    armored = damage.evaluate(g, t, None, enemy=Enemy(None, 2700.0))
    assert armored.direct_dps == pytest.approx(plain.sustained_dps * 0.1)  # 90% stopped
    assert armored.status_dps == 0  # no status chance, no procs
    # 100% status, all slash: 1 proc per shot, 10 shots/s x uptime 30/50 = 6 procs/s
    g.status_chance = 1.0
    r = damage.evaluate(g, t, None, enemy=Enemy(None, 2700.0))
    # each bleed: 6 ticks x 0.35 x 100 base, no armor -> 210 per proc
    assert r.status_dps == pytest.approx(6 * 210)
    # stripped armor: direct hits land in full
    assert damage.evaluate(g, t, None, enemy=Enemy(None, 2700.0, stripped=True)).direct_dps == pytest.approx(
        plain.sustained_dps
    )


def test_corrosive_and_viral_stacks():
    from openwarframe.builds.enemy import Enemy

    g = gun(damage={"corrosive": 100.0}, crit_chance=0.0, status_chance=1.0)
    r = damage.evaluate(g, damage.add_up([], stacks=False), None, enemy=Enemy(None, 1000.0))
    # 6 procs/s x 8 s -> 10 stacks (capped): armor x 0.2
    assert r.corrosive_stacks == 10 and r.armor == pytest.approx(200)
    g = gun(damage={"viral": 100.0}, crit_chance=0.0, status_chance=1.0)
    r = damage.evaluate(g, damage.add_up([], stacks=False), None, enemy=Enemy(None, 0.0))
    plain = damage.evaluate(g, damage.add_up([], stacks=False), None)
    assert r.viral_stacks == 10 and r.direct_dps == pytest.approx(plain.sustained_dps * 4.25)  # +325%


def test_dot_uses_bane_twice_and_the_element_bonus():
    from openwarframe.builds.enemy import Enemy

    g = gun(damage={"impact": 100.0}, crit_chance=0.0, status_chance=1.0)
    t = damage.add_up([eff(heat=1.0), eff(**{"bane:Grineer": 0.3})], stacks=False)
    r = damage.evaluate(g, t, "Grineer", enemy=Enemy("Grineer", 0.0))
    # heat is half the damage (100 of 200): 3 heat procs/s; tick = 0.5 x 100 x 1.3 x (1 + 1.0) x 1.3
    tick = 0.5 * 100 * 1.3 * 2.0 * 1.3
    assert r.status_dps == pytest.approx(3 * 6 * tick)


def test_status_build_against_steel_path_grineer():
    """A status weapon against armored Steel Path Grineer: the search finds the best build (the
    same as trying every combination), and it is Viral plus Heat, the usual Steel Path pick."""
    from openwarframe.builds.enemy import enemy_for

    g = gun(damage={"impact": 30.0, "puncture": 30.0, "slash": 40.0}, crit_chance=0.05, status_chance=0.6)
    pool_mods = {
        "Serration": eff(damage=1.65), "Split Chamber": eff(multishot=0.9), "Hellfire": eff(heat=0.9),
        "Cryo Rounds": eff(cold=0.9), "Infected Clip": eff(toxin=0.9), "Stormbringer": eff(electricity=0.9),
        "Rifle Aptitude": eff(status_chance=0.9), "Speed Trigger": eff(fire_rate=0.6), "Vital Sense": eff(crit_damage=1.2),
    }  # fmt: skip
    pool = [
        search.Pick(
            mods.GunMod("/" + n, n, "Rifle", "PRIMARY", None, 4, 10, "RARE", [[]], exclusive=n), 10, e, None
        )
        for n, e in pool_mods.items()
    ]
    enemy = enemy_for("Grineer", "sp")
    found = search.search(g, pool, "Grineer", False, enemy)
    score, result, _ = search._score(g, found, "Grineer", False, enemy)
    best = max(search._score(g, list(c), "Grineer", False, enemy)[0] for c in combinations(pool, 8))
    assert score == pytest.approx(best)
    assert "viral" in result.by_type and "heat" in result.by_type
    assert result.viral_stacks > 5 and result.heat_uptime > 0.9 and result.status_dps > 0
