"""The enemy a build is judged against: faction, level and armor.

Armor scaling, from wiki.warframe.com/w/Enemy_Level_Scaling (edited 2026-07-29), with
q = level - base level:

    f1 = 1 + 0.005 q^1.75          f2 = 1 + 0.4 q^0.75
    t  = clamp((q - 70) / 10, 0, 1),  s = t^2 (3 - 2t)
    armor = base armor x (f1 + (f2 - f1) s), at least 200 and at most 2700

The Steel Path adds 100 levels and no armor (Update 36). The armored unit is a Heavy Gunner
(500 armor at level 8, Module:Enemies/data/grineer, edited 2026-11-26), the usual reference
for "how armored is this mission". Factions whose common units carry no armor (Corpus rely on
shields, most Infested have none) are judged without armor; shields aren't modelled.
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


def scale_armor(base: float, base_level: int, level: int) -> float:
    q = max(0, level - base_level)
    f1 = 1 + 0.005 * q**1.75
    f2 = 1 + 0.4 * q**0.75
    t = min(1.0, max(0.0, (q - 70) / 10))
    s = t * t * (3 - 2 * t)
    return min(ARMOR_CAP, max(ARMOR_FLOOR, base * (f1 + (f2 - f1) * s)))


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


def enemy_for(faction: str | None, level_choice: str = "sp", stripped: bool = False) -> Enemy:
    level = LEVELS.get(level_choice, LEVELS["sp"])
    if level is None or faction not in ARMORED:
        return Enemy(faction, 0.0, stripped, level)
    return Enemy(faction, scale_armor(HEAVY_ARMOR, HEAVY_LEVEL, level), stripped, level)
