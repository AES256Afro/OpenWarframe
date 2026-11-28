"""The enemy a build is judged against: faction, level and armor.

Armor scaling, from wiki.warframe.com/w/Enemy_Level_Scaling (edited 2026-07-29), with
q = level - base level:

    f1 = 1 + 0.005 q^1.75          f2 = 1 + 0.4 q^0.75
    t  = clamp((q - 70) / 10, 0, 1),  s = t^2 (3 - 2t)
    armor = base armor x (f1 + (f2 - f1) s), at least 200 and at most 2700

The Steel Path adds 100 levels and no armor (Update 36). The armored unit is a Heavy Gunner
(500 armor at level 8, Module:Enemies/data/grineer, edited 2026-11-26), the usual reference
for "how armored is this mission". Corpus are judged on a Corpus Tech (shields, no armor),
Infested on a Toxic Ancient (no armor; its own Toxin resistance isn't applied), other factions
on an unarmored unit with a Heavy Gunner's health. Health and shields scale with level too, and
the Steel Path multiplies both by 2.5.
"""

from __future__ import annotations

from dataclasses import dataclass

ARMOR_CAP = 2700.0
ARMOR_FLOOR = 200.0
HEAVY_ARMOR, HEAVY_LEVEL = 500.0, 8
# a typical level for each choice in the app (Steel Path: +100 levels)
LEVELS = {"none": None, "normal": 35, "sp": 135}
# factions whose typical heavy units are armored (Heavy Gunner style)
ARMORED = {"Grineer", "Kuva Grineer", "Scaldra", "Orokin", "Narmer", "Anarchs", None}


def _blend(q: float, c1: float, e1: float, c2: float, e2: float) -> float:
    """1 + c1 q^e1 below 70 levels over base, 1 + c2 q^e2 above 80, smoothly blended between."""
    f1 = 1 + c1 * q**e1
    f2 = 1 + c2 * q**e2
    t = min(1.0, max(0.0, (q - 70) / 10))
    s = t * t * (3 - 2 * t)
    return f1 + (f2 - f1) * s


def scale_armor(base: float, base_level: int, level: int) -> float:
    q = max(0, level - base_level)
    return min(ARMOR_CAP, max(ARMOR_FLOOR, base * _blend(q, 0.005, 1.75, 0.4, 0.75)))


# health and shield curves per faction (Enemy_Level_Scaling, edited 2026-07-29)
HEALTH_CURVES = {
    "Grineer": (0.015, 2.12, 10.7332, 0.72),
    "Corpus": (0.015, 2.12, 13.4165, 0.55),
    "Infested": (0.0225, 2.12, 16.0998, 0.72),
}
SHIELD_CURVES = {"Corpus": (0.02, 1.76, 2.0, 0.76)}
STEEL_PATH_HEALTH = STEEL_PATH_SHIELDS = 2.5  # The_Steel_Path, edited 2026-10-14


def scale_health(base: float, base_level: int, level: int, curve: str) -> float:
    return base * _blend(max(0, level - base_level), *HEALTH_CURVES[curve])


def scale_shields(base: float, base_level: int, level: int, curve: str) -> float:
    return base * _blend(max(0, level - base_level), *SHIELD_CURVES[curve])


def armor_reduction(armor: float) -> float:
    """Share of damage armor stops: 0.9 x sqrt(armor / 2700) (wiki Armor, edited 2026-09-28)."""
    if armor <= 0:
        return 0.0
    if armor > ARMOR_CAP:
        return armor / (armor + 300)
    return 0.9 * (armor / ARMOR_CAP) ** 0.5


@dataclass
class Enemy:
    faction: str | None  # None: no faction modifiers
    armor: float  # before any stripping
    stripped: bool = False  # armor already removed by abilities or the squad
    level: int | None = None
    health: float = 0.0  # 0: judge by damage per second only (no time to kill)
    shields: float = 0.0
    unit: str = ""
    # headshots (wiki Enemy_Body_Parts, read 2026-11-28): head multiplier, and whether crits on
    # the head get the extra x2 (Corpus humanoids, most Murmur and Techrot don't)
    head_mult: float = 3.0
    headcrit: bool = True


# reference units (Module:Enemies/data/*): (name, health, shields, armor, base level, health curve)
UNITS = {
    "armored": ("Heavy Gunner", 300.0, 0.0, HEAVY_ARMOR, HEAVY_LEVEL, "Grineer"),  # grineer, 2026-11-26
    "Corpus": ("Corpus Tech", 700.0, 250.0, 0.0, 15, "Corpus"),  # corpus, 2026-07-18
    "Corpus Amalgam": ("Corpus Tech", 700.0, 250.0, 0.0, 15, "Corpus"),
    "Infested": ("Toxic Ancient", 400.0, 0.0, 0.0, 1, "Infested"),  # infestation, 2026-09-13
    "Infested Deimos": ("Toxic Ancient", 400.0, 0.0, 0.0, 1, "Infested"),
    "other": ("Heavy Gunner (no armor)", 300.0, 0.0, 0.0, HEAVY_LEVEL, "Grineer"),
}


# heads that aren't the usual 3x with crit bonus
HEADS = {
    "Murmur": (1.5, False),
    "Techrot": (1.5, False),
    "Corpus": (3.0, False),
    "Corpus Amalgam": (3.0, False),
}


def enemy_for(faction: str | None, level_choice: str = "sp", stripped: bool = False) -> Enemy:
    level = LEVELS.get(level_choice, LEVELS["sp"])
    head_mult, headcrit = HEADS.get(faction or "", (3.0, True))
    if level is None:
        return Enemy(faction, 0.0, stripped, None, head_mult=head_mult, headcrit=headcrit)
    key = "armored" if faction in ARMORED else faction if faction in UNITS else "other"
    name, health, shields, armor, base_level, curve = UNITS[key]
    sp = level_choice == "sp"
    hp = scale_health(health, base_level, level, curve) * (STEEL_PATH_HEALTH if sp else 1)
    sh = (
        scale_shields(shields, base_level, level, "Corpus") * (STEEL_PATH_SHIELDS if sp else 1)
        if shields
        else 0.0
    )
    ar = scale_armor(armor, base_level, level) if armor else 0.0
    return Enemy(faction, ar, stripped, level, hp, sh, name, head_mult, headcrit)
