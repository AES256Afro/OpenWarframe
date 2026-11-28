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
            "On Kill:",
            "+40% Weapon Recoil for 20s. Stacks up to 2x.",
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


# -- shields (wiki Shield, Damage/Magnetic_Damage, Damage/Toxin_Damage, Enemy_Level_Scaling) --


def test_health_and_shield_scaling():
    from openwarframe.builds.enemy import enemy_for, scale_health, scale_shields

    assert scale_health(700, 15, 15, "Corpus") == 700
    # q = 20 (below the blend): 1 + 0.015 x 20^2.12 and 1 + 0.02 x 20^1.76
    assert scale_health(700, 15, 35, "Corpus") == pytest.approx(700 * (1 + 0.015 * 20**2.12))
    assert scale_shields(250, 15, 35, "Corpus") == pytest.approx(250 * (1 + 0.02 * 20**1.76))
    # q = 120 (above the blend): the second curve; Steel Path x2.5
    e = enemy_for("Corpus", "sp")
    assert e.unit == "Corpus Tech" and e.armor == 0
    assert e.health == pytest.approx(700 * (1 + 13.4165 * 120**0.55) * 2.5)
    assert e.shields == pytest.approx(250 * (1 + 2 * 120**0.76) * 2.5)
    assert enemy_for("Grineer", "sp").shields == 0 and enemy_for("Grineer", "none").health == 0


def test_time_to_kill_phases():
    from openwarframe.builds.damage import _time_to_kill

    assert _time_to_kill(100, 0, 0, 0, 50) == 2  # no shields: health / dps
    # 100 shields at 50/s = 2 s, toxin 10/s meanwhile: 80 health left at 40/s -> 2 s more
    assert _time_to_kill(100, 100, 50, 10, 40) == pytest.approx(4)
    assert _time_to_kill(100, 1000, 1, 100, 100) == pytest.approx(1)  # toxin kills before shields break
    assert _time_to_kill(100, 100, 0, 0, 100) == float("inf")


def test_magnetic_and_toxin_against_shields():
    from openwarframe.builds.enemy import Enemy

    g = gun(damage={"magnetic": 100.0}, crit_chance=0.0, status_chance=1.0)
    t = damage.add_up([], stacks=False)
    r = damage.evaluate(g, t, None, enemy=Enemy(None, 0.0, health=1000.0, shields=1000.0))
    plain = damage.evaluate(g, t, None)
    # 6 procs/s x 6 s -> 10 Magnetic stacks: shields take x4.25
    assert r.magnetic_stacks == 10 and r.shield_dps == pytest.approx(plain.sustained_dps * 4.25)
    g = gun(damage={"toxin": 100.0}, crit_chance=0.0, status_chance=0.0)
    r = damage.evaluate(g, t, None, enemy=Enemy(None, 0.0, health=600.0, shields=10_000.0))
    assert r.shield_dps == 0 and r.time_to_kill == pytest.approx(1.0)  # 600/s straight to health


def test_corpus_search_is_optimal(tmp_path: Path):
    """Against Steel Path Corpus (shields, then much more health) the search still finds the best
    build. With one Cold mod, Viral beats Magnetic: since Update 36 shields are the smaller pool."""
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
    enemy = enemy_for("Corpus", "sp")
    found = search.search(g, pool, "Corpus", False, enemy)
    score, result, _ = search._score(g, found, "Corpus", False, enemy)
    best = max(search._score(g, list(c), "Corpus", False, enemy)[0] for c in combinations(pool, 8))
    assert score == pytest.approx(best)
    assert "viral" in result.by_type and 0 < result.time_to_kill < float("inf")


# -- melee (wiki Melee_Combo, Blood_Rush, Weeping_Wounds, Condition_Overload, Gladiator_Set) --


def melee(**kw):
    g = gun(slot="MELEE", holster="MELEE", magazine=1, reload=0.0, fire_rate=1.0, **kw)
    return g


def test_melee_mods_parse():
    assert mods.parse_line("+40% Critical Chance stacks with Combo Multiplier") == ("combo_crit", 0.4)
    assert mods.parse_line("+40% Status Chance per Combo Multiplier") == ("combo_status", 0.4)
    assert mods.parse_line("+80% Melee Damage per Status Type affecting the target") == (
        "per_status_damage",
        0.8,
    )
    assert mods.parse_line("+120% Melee Damage") == ("damage", 1.2)
    assert mods.parse_line("+220% Critical Chance (x2 for Heavy Attacks)") == ("crit_chance", 2.2)
    assert mods.parse_line("x1.33 Damage to Sentients")[0] == "bane:Sentient"


def test_combo_scaling_mods():
    g = melee(crit_chance=0.2, status_chance=0.2)
    t = damage.add_up([eff(combo_crit=0.4), eff(combo_status=0.4)], stacks=False)
    t.sums["combo"] = 12
    r = damage.evaluate(g, t)
    # crit: 0.2 x (1 + 0.4 x 11) = 1.08; status the same
    assert r.crit_chance == pytest.approx(1.08) and r.status_chance == pytest.approx(1.08)
    t.sums["combo"] = 1
    assert damage.evaluate(g, t).crit_chance == pytest.approx(0.2)  # no combo, no bonus
    # Gladiator set: +10% per set mod per combo step, with Blood Rush
    t = damage.add_up([eff(combo_crit=0.4)], stacks=False)
    t.sums.update(combo=12, gladiator=2)
    assert damage.evaluate(g, t).crit_chance == pytest.approx(0.2 * (1 + (0.4 + 0.2) * 11))
    # the combo never raises a normal hit's damage
    plain = damage.evaluate(g, damage.add_up([], stacks=False))
    t = damage.add_up([], stacks=False)
    t.sums["combo"] = 12
    assert damage.evaluate(g, t).per_shot == pytest.approx(plain.per_shot)


def test_condition_overload_counts_status_types():
    g = melee(damage={"impact": 100.0}, crit_chance=0.0, status_chance=0.0)
    t = damage.add_up([eff(damage=1.2), eff(per_status_damage=0.8)], stacks=False)
    t.sums["extra_status"] = 3  # three types kept up by abilities
    r = damage.evaluate(g, t)
    # 100 x (1 + 1.2 + 0.8 x 3): the same bonus as Pressure Point
    assert r.status_types == pytest.approx(3) and r.per_shot == pytest.approx(100 * (1 + 1.2 + 2.4))
    g.status_chance = 1.0  # impact procs every hit, 1 hit/s for 6 s: impact is (almost surely) up
    r = damage.evaluate(g, t)
    assert 3.99 < r.status_types <= 4.0


def test_berserker_fury_clashes_with_fury():
    def m(name):
        return mods.GunMod(
            "/M/" + name, name, "Melee", "MELEE", None, 4, 5, "RARE", [[]], exclusive=mods.exclusive_key(name)
        )

    assert search.clash(m("Berserker Fury"), m("Primed Fury")) and search.clash(
        m("Berserker Fury"), m("Fury")
    )
    assert mods.fits(m("Pressure Point"), mods.WeaponClass("MELEE", "MELEE", None, "Galatine Prime"))
    assert not mods.fits(m("Pressure Point"), mods.WeaponClass("PRIMARY", "RIFLE", None, "Braton"))


def test_melee_suggest(tmp_path: Path):
    from openwarframe.codex.schema import SCHEMA

    con = sqlite3.connect(tmp_path / "m.sqlite")
    con.executescript(SCHEMA)
    w = {"name": "Testsword", "productCategory": "Melee", "damagePerShot": [0, 0, 100] + [0] * 17,
         "criticalChance": 0.25, "criticalMultiplier": 2, "procChance": 0.25, "fireRate": 1.0}  # fmt: skip
    con.execute(
        "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
        ("/S", "Testsword", "Melee", "Melee", 0, None, None, json.dumps(w)),
    )
    con.execute("INSERT INTO weapon_class VALUES ('/S', 'MELEE', NULL, '[]')")

    def add(uid, name, line):
        d = {
            "type": "MELEE",
            "compatName": "Melee",
            "baseDrain": 4,
            "fusionLimit": 0,
            "rarity": "RARE",
            "levelStats": [{"stats": [line]}],
        }
        con.execute(
            "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
            (uid, name, "Mod", None, None, None, None, json.dumps(d)),
        )

    add("/M/BR", "Blood Rush", "+40% Critical Chance stacks with Combo Multiplier")
    add("/M/TS", "True Steel", "+120% Critical Chance (x2 for Heavy Attacks)")
    add("/M/PP", "Pressure Point", "+120% Melee Damage")
    b = search.suggest(con, "/S", combo=12, level="none")
    assert {m["name"] for m in b["mods"]} == {"Blood Rush", "True Steel", "Pressure Point"}
    assert b["stats"]["crit_chance"] == pytest.approx(0.25 * (1 + 1.2 + 0.4 * 11))
    assert any("12x combo" in n for n in b["notes"])
    b1 = search.suggest(con, "/S", combo=1, level="none")
    assert b1["stats"]["crit_chance"] == pytest.approx(0.25 * 2.2)


def test_page_offers_melee_options():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'r.category==="Melee"' in page and 'data-bopt="combo"' in page and "&xstatus=" in page


def test_weapon_exilus_slot():
    def pick(name, utility=False, **stats):
        m = mods.GunMod(
            "/M/" + name, name, "Rifle", "PRIMARY", None, 2, 0, "RARE", [[]], exclusive=name, utility=utility
        )
        return search.Pick(m, 0, eff(**stats), None)

    general = [pick(f"G{i}", damage=0.1) for i in range(8)]
    util = pick("Exilus Damage", utility=True, damage=0.05)
    assert search._slots_ok([*general, util]) and not search._slots_ok([*general, pick("G9", damage=0.1)])
    g = gun(status_chance=0.5)
    found = search.search(g, [*general, util], None, False)
    assert len(found) == 9 and util in found  # the 9th slot takes the exilus-capable mod


# -- heavy attacks (wiki Heavy_Attack) and weapon arcanes (wiki Arcane_Enhancement) ----------


def test_heavy_attack_mods_parse():
    e = mods.parse_effect(["+120% Critical Chance (x2 for Heavy Attacks)"])
    # x2 on heavies: the second half only counts on heavy attacks
    assert e.stats == {"crit_chance": 1.2, "heavy_crit_chance": 1.2}
    e = mods.parse_effect(["+120% Melee Damage on Heavy Attack", "+60% Heavy Attack Wind Up Speed"])
    assert e.stats == {"heavy_damage": 1.2, "windup_speed": 0.6}


def test_heavy_attack_damage():
    g = melee(damage={"slash": 100.0}, crit_chance=0.0, status_chance=0.0, heavy_mult=6.0, windup=1.1)
    t = damage.add_up([eff(heavy_damage=1.2, windup_speed=0.6), eff(damage=1.0)], stacks=False)
    t.sums["combo"] = 12
    normal = damage.evaluate(g, t)
    assert normal.per_shot == pytest.approx(200) and not normal.heavy  # Killing Blow: heavies only
    t.sums["heavy"] = 1
    r = damage.evaluate(g, t)
    # 100 x (1 + 1.0 + 1.2) x 6 (heavy multiplier) x 12 (combo, spent)
    assert r.heavy and r.per_shot == pytest.approx(100 * 3.2 * 6 * 12)
    assert r.windup == pytest.approx(1.1 / 1.6)
    # True Steel's doubled half and Melee Animosity count on heavies only
    g.crit_chance = 0.2
    t = damage.add_up([mods.parse_effect(["+120% Critical Chance (x2 for Heavy Attacks)"])], stacks=False)
    assert damage.evaluate(g, t).crit_chance == pytest.approx(0.2 * 2.2)
    t.sums["heavy"] = 1
    assert damage.evaluate(g, t).crit_chance == pytest.approx(0.2 * 3.4)


def test_heavy_hit_meets_full_armor():
    from openwarframe.builds.enemy import Enemy, armor_reduction

    g = melee(damage={"impact": 100.0}, crit_chance=0.0, status_chance=1.0, heavy_mult=5.0)
    t = damage.add_up([eff(corrosive=1.0)], stacks=False)
    t.sums["heavy"] = 1
    r = damage.evaluate(g, t, enemy=Enemy(None, 1000.0))
    # its own Corrosive proc lands after the hit
    assert r.direct_dps == pytest.approx(r.per_shot * (1 - armor_reduction(1000.0)))


def test_doughty_adds_to_the_crit_multiplier():
    g = melee(damage={"puncture": 50.0, "impact": 50.0}, crit_chance=0.2, status_chance=1.0)
    t = damage.add_up([], stacks=False)
    t.sums["doughty"] = 1.0
    # 100% status x 50% Puncture = 50% Puncture status chance: +1.0x per 10% -> +5.0x
    assert damage.evaluate(g, t).crit_multiplier == pytest.approx(2.0 + 5.0)


def test_weapon_arcane_effects():
    from openwarframe.builds.arcanes import Arcane, weapon_effect

    def a(name, text):
        return weapon_effect(Arcane("/A/" + name, name, 0, [text]))

    assert a("Primary Merciless", "On Kill:\n+30% Damage for 4s. Stacks up to 12x.") == pytest.approx(
        {"damage": 3.6}
    )
    assert a(
        "Primary Blight",
        "On Toxin Status Effect:\n+3.6% Critical Damage and +1.8% Multishot for 12s. Stacks up to 40x.",
    ) == pytest.approx({"crit_damage": 1.44, "multishot": 0.72})
    assert a(
        "Melee Animosity", "+42% Critical Chance on your next Heavy Attack, up to 420%"
    ) == pytest.approx({"heavy_crit_chance": 4.2})


def test_stance_adds_melee_capacity():
    def pick(slot, drain):
        m = mods.GunMod("/M/" + str(drain) + slot, f"M{drain}{slot}", "x", slot, None, drain, 0, "RARE", [[]])
        return search.Pick(m, 0, eff(damage=0.1), None)

    picks = [pick("MELEE", 14) for _ in range(4)] + [pick("MELEE", 15)]  # 71 drain
    assert search.forma_needed(picks) == 1  # 71 > 60 + 10 (stance): one Forma
    picks = [pick("MELEE", 14) for _ in range(5)]  # 70
    assert search.forma_needed(picks) == 0
    guns = [pick("PRIMARY", 14) for _ in range(5)]
    assert search.forma_needed(guns) == 2  # 60 without a stance: 70 -> 63 -> 56


def test_heavy_suggest_with_arcane(tmp_path: Path):
    from openwarframe.codex.schema import SCHEMA

    con = sqlite3.connect(tmp_path / "h.sqlite")
    con.executescript(SCHEMA)
    w = {"name": "Testblade", "productCategory": "Melee", "damagePerShot": [0, 0, 100] + [0] * 17, "totalDamage": 100,
         "heavyAttackDamage": 600, "windUp": 1.0, "criticalChance": 0.3, "criticalMultiplier": 2,
         "procChance": 0.2, "fireRate": 1.0}  # fmt: skip
    con.execute(
        "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
        ("/B", "Testblade", "Melee", "Melee", 0, None, None, json.dumps(w)),
    )
    con.execute("INSERT INTO weapon_class VALUES ('/B', 'MELEE', NULL, '[]')")
    for uid, name, line in [
        ("/M/KB", "Killing Blow", "+120% Melee Damage on Heavy Attack"),
        ("/M/PP", "Pressure Point", "+120% Melee Damage"),
    ]:
        d = {"type": "MELEE", "compatName": "Melee", "baseDrain": 4, "fusionLimit": 0, "rarity": "RARE",
             "levelStats": [{"stats": [line]}]}  # fmt: skip
        con.execute(
            "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
            (uid, name, "Mod", None, None, None, None, json.dumps(d)),
        )
    arc = {"levelStats": [{"stats": ["+42% Critical Chance on your next Heavy Attack, up to 420%"]}]}
    con.execute(
        "INSERT INTO item VALUES (?,?,?,?,?,?,?,?)",
        ("/A/An", "Melee Animosity", "Arcane", None, None, None, None, json.dumps(arc)),
    )
    b = search.suggest(con, "/B", combo=12, level="none")
    assert b["attack"] == "normal" and b["can_heavy"] and b["arcane"] is None  # Animosity: heavies only
    assert {m["name"] for m in b["mods"]} == {"Pressure Point"}  # Killing Blow does nothing here
    h = search.suggest(con, "/B", combo=12, level="none", attack="heavy")
    assert h["attack"] == "heavy" and h["arcane"]["name"] == "Melee Animosity" and h["arcane"]["counted"]
    assert {m["name"] for m in h["mods"]} == {"Pressure Point", "Killing Blow"}
    assert h["stats"]["crit_chance"] == pytest.approx(0.3 * (1 + 4.2))
    assert h["stats"]["per_shot"] == pytest.approx(100 * 3.4 * 6 * 12 * (1 + 0.3 * 5.2 * 1))
    n = search.suggest(con, "/B", combo=12, level="none", attack="heavy", arcane="none")
    assert n["arcane"] is None and n["arcane_options"] == [{"name": "Melee Animosity", "scored": True}]


def test_page_offers_heavy_and_arcane_options():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'data-bopt="attack"' in page and "data-barc" in page and "&arcane=" in page


def test_bows_get_double_from_bow_fire_rate_mods():
    e = mods.parse_effect(["+60% Fire Rate (x2 for Bows)"])
    assert e.stats == {"fire_rate": 0.6, "bow_fire_rate": 0.6}
    t = damage.add_up([e], stacks=False)
    assert damage.evaluate(gun(fire_rate=1.0, holster="BOW"), t).fire_rate == pytest.approx(2.2)
    assert damage.evaluate(gun(fire_rate=1.0, holster="RIFLE"), t).fire_rate == pytest.approx(1.6)


def test_galvanized_damage_per_status_type():
    # wiki Galvanized_Aptitude: +40% per status type per stack, with Serration, like Condition Overload
    e = mods.parse_effect(
        [
            "+80% Status Chance",
            "On Kill:\n+40% Direct Damage per Status Type affecting the target for 20s. Stacks up to 2x.",
        ]
    )
    assert e.stacks == {"per_status_damage": (0.4, 2)} and e.stats == {"status_chance": 0.8}
    g = gun(damage={"impact": 100.0}, crit_chance=0.0, status_chance=0.0)
    t = damage.add_up([e, eff(damage=1.65)], stacks=True)
    t.sums["extra_status"] = 3
    # 100 x (1 + 1.65 + 0.8 x 3)
    assert damage.evaluate(g, t).per_shot == pytest.approx(100 * (1 + 1.65 + 2.4))
    t.sums["extra_status"] = 40  # no more than 16 statuses on one enemy
    assert damage.evaluate(g, t).status_types == pytest.approx(16)


def test_weapon_arcane_only_from_inventory(tmp_path: Path):
    from openwarframe.builds.arcanes import Arcane

    g = melee(damage={"slash": 100.0}, crit_chance=0.3, heavy_mult=6.0)
    g.heavy = True
    arcs = [
        Arcane("/A/An", "Melee Animosity", 0, ["+42% Critical Chance on your next Heavy Attack, up to 420%"])
    ]
    assert search._pick_arcane(g, arcs, None, [], None, False, None).name == "Melee Animosity"
    assert search._pick_arcane(g, arcs, None, [], None, False, None, owned={}) is None and g.arcane == {}


# -- headshots and weak points (wiki Enemy_Body_Parts, Critical_Hit, Primary_Acuity) -----------


def test_headshot_mods_parse():
    e = mods.parse_effect(
        ["+350% Weak Point Damage", "+350% Weak Point Critical Chance. Multishot cannot be modified."]
    )
    assert e.stats == {"weak_point_damage": 3.5, "weak_point_crit": 3.5, "lock_multishot": 1.0}
    assert mods.parse_effect(["+60% to Headshot Multiplier"]).stats == {"headshot_bonus": 0.6}
    e = mods.parse_effect(["+105% Headshot Damage", "-45% Bodyshot Damage"])
    assert e.stats == {"headshot_bonus": 1.05, "body_damage": -0.45}
    # scopes: on weak point hit / kill, "when Aiming" taken as met; kept apart for head aim only
    e = mods.parse_effect(
        [
            "On Weak Point Hit:\r\n+120% Critical Chance when Aiming for 12s\r\nOn Weak Point Kill:\r\n"
            "+40% Critical Chance when Aiming for 12s. Stacks up to 5x."
        ]
    )
    assert e.stats == {"head:crit_chance": 1.2} and e.stacks == {"head:crit_chance": (0.4, 5)}
    assert mods.parse_effect(["On Headshot:\r\n40% chance for Infinite Ammo for 2s"]).conditional


def _head(t, head_mult=3.0, headcrit=True):
    t.sums.update(headshot=1.0, head_mult=head_mult, headcrit=float(headcrit))
    return t


def test_headshot_damage():
    g = gun(damage={"impact": 100.0}, crit_chance=0.5, crit_multiplier=2.0, multishot=1.0)
    body = damage.evaluate(g, damage.add_up([], stacks=False))
    assert body.per_shot == pytest.approx(100 * 1.5)
    # head x3; crit headshots x2 on the crit multiplier: 1 + 0.5 x (2 x 2 - 1) = 2.5
    assert damage.evaluate(g, _head(damage.add_up([], stacks=False))).per_shot == pytest.approx(100 * 3 * 2.5)
    # no headcrit (Corpus humanoids): 3 x 1.5
    r = damage.evaluate(g, _head(damage.add_up([], stacks=False), headcrit=False))
    assert r.per_shot == pytest.approx(100 * 3 * 1.5)
    # wiki Primary_Acuity: 1.3 x (3 + 1.5 x 3.5) = 10.725 with Deadhead's +30%
    t = _head(damage.add_up([eff(weak_point_damage=3.5), eff(headshot_bonus=0.3)], stacks=False))
    assert damage.evaluate(g, t).location_mult == pytest.approx(10.725)
    # Meticulous Aim's penalty applies to body shots only
    t = damage.add_up([eff(headshot_bonus=1.05, body_damage=-0.45)], stacks=False)
    assert damage.evaluate(g, t).per_shot == pytest.approx(150 * 0.55)
    assert damage.evaluate(g, _head(t)).location_mult == pytest.approx(3 * 2.05)


def test_acuity_crit_and_multishot_lock():
    g = gun(damage={"impact": 100.0}, crit_chance=0.2, multishot=1.0)
    t = damage.add_up(
        [
            mods.parse_effect(["+350% Weak Point Critical Chance. Multishot cannot be modified."]),
            eff(crit_chance=1.5, multishot=1.2),
        ],
        stacks=False,
    )
    assert damage.evaluate(g, t).multishot == pytest.approx(1.0)  # locked
    assert damage.evaluate(g, t).crit_chance == pytest.approx(0.2 * 2.5)  # body: no weak point crit
    assert damage.evaluate(g, _head(t)).crit_chance == pytest.approx(0.2 * (1 + 1.5 + 3.5))


def test_head_effects_only_when_aiming_at_heads():
    g = gun(damage={"impact": 100.0}, crit_chance=0.2)
    scope = mods.parse_effect(["On Weak Point Hit:\r\n+135% Critical Chance when Aiming for 9s"])
    m = mods.GunMod("/M/AS", "Argon Scope", "Rifle", "PRIMARY", None, 4, 0, "RARE", [[]])
    picks = [search.Pick(m, 0, scope, None)]
    assert search._score(g, picks, None, False)[1].crit_chance == pytest.approx(0.2)
    g.head = True
    assert search._score(g, picks, None, False)[1].crit_chance == pytest.approx(0.2 * 2.35)


def test_head_only_arcanes():
    from openwarframe.builds.arcanes import Arcane, weapon_effect

    text = "On Weak Point Kill:\n+120% Damage for 24s. Stacks up to 3x.\n+30% to Headshot Multiplier\n-50% Weapon Recoil\n+30% to Headshot Multiplier"
    dh = Arcane("/A/DH", "Primary Deadhead", 0, [text])
    assert weapon_effect(dh) == pytest.approx({"damage": 3.6, "headshot_bonus": 0.3})
    g = gun(damage={"impact": 100.0})
    assert search._pick_arcane(g, [dh], None, [], None, False, None) is None  # body shots: not offered
    g.head = True
    assert search._pick_arcane(g, [dh], None, [], None, False, None).name == "Primary Deadhead"


def test_page_offers_aim():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'data-bopt="aim"' in page and "&aim=" in page
