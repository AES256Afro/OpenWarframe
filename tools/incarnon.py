"""Build kb/builds/incarnon.json: Incarnon form stats and evolution perks for builds.

Input: kb/builds/incarnon_wiki.json, what was read off each weapon's Warframe Wiki page
(infobox "Incarnon Form" attack, Evolution I to V) on 2026-11-28. The wiki is CC BY-NC-SA 3.0
(https://wiki.warframe.com, Weird Gloop); OpenWarframe never fetches it while running.

The game data has no Incarnon stats (an Incarnon Genesis item carries only a one-line
description), so these numbers come from the wiki. Perk effects are written out by hand below:
the page text mixes per-variant columns and conditions, and only effects that hold steady in a
fight are scored. A list value is one number per variant, in the order of ``VARIANTS``.

Effect keys:
  bd       base damage added per projectile (both forms)
  bcc/bcd  base crit chance / base crit multiplier added before mods
  bsc      base status chance added before mods, as the Incarnon-form total; the game splits it
           over the base multishot (Boar: +96% in Incarnon form, +12% per pellet on 8 pellets)
  fcc/fsc  crit / status chance added after mods (Zariman weapons: "added after mods as a flat
           value"); status split over base multishot the same way
  bms      base multishot added;  bmag: base magazine added (normal attack only)
  noncrit  expected extra damage on non-critical hits (50% chance for +2000% -> 10)
  lowcrit  [below, x]: +x base crit multiplier while crit chance is below ``below``
  double_in_form: the perk's numbers double in Incarnon form
  stacks   effects that build up in steady fighting, counted with on-kill stacks
  other keys work like mod stats (fire_rate, multishot, reload, per_status_damage, ...)

    uv run python tools/incarnon.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
RAW = ROOT / "kb" / "builds" / "incarnon_wiki.json"
OUT = ROOT / "kb" / "builds" / "incarnon.json"

GENESIS = {
    "Boar", "Boltor", "Braton", "Burston", "Dera", "Dread", "Gorgon", "Latron", "Miter", "Paris",
    "Soma", "Strun", "Sybaris", "Torid", "Vectis", "Angstrum", "Atomos", "Ballistica", "Bronco",
    "Cestra", "Despair", "Dual Toxocyst", "Furis", "Gammacor", "Kunai", "Lato", "Lex", "Sicarus",
    "Stug", "Vasto", "Zylok", "Ack & Brunt", "Anku", "Bo", "Ceramic Dagger", "Destreza",
    "Dual Ichor", "Furax", "Hate", "Magistar", "Nami Solo", "Obex", "Okina", "Sibear", "Skana",
}  # fmt: skip
# variant columns of each Evolution table, in page order
VARIANTS = {
    "Boar": ["Boar", "Boar Prime"],
    "Boltor": ["Boltor", "Telos Boltor", "Boltor Prime"],
    "Braton": ["Braton", "MK1-Braton", "Braton Vandal", "Braton Prime"],
    "Burston": ["Burston", "Burston Prime"],
    "Dera": ["Dera", "Dera Vandal"],
    "Gorgon": ["Gorgon", "Gorgon Wraith", "Prisma Gorgon"],
    "Latron": ["Latron", "Latron Wraith", "Latron Prime"],
    "Paris": ["Paris", "MK1-Paris", "Paris Prime"],
    "Soma": ["Soma", "Soma Prime"],
    "Strun": ["Strun", "MK1-Strun", "Strun Wraith", "Strun Prime"],
    "Sybaris": ["Sybaris", "Dex Sybaris", "Sybaris Prime"],
    "Vectis": ["Vectis", "Vectis Prime"],
    "Angstrum": ["Angstrum", "Prisma Angstrum"],
    "Ballistica": ["Ballistica", "Rakta Ballistica", "Ballistica Prime"],
    "Bronco": ["Bronco", "Bronco Prime"],
    "Furis": ["Furis", "MK1-Furis"],
    "Gammacor": ["Gammacor", "Synoid Gammacor"],
    "Kunai": ["Kunai", "MK1-Kunai"],
    "Lato": ["Lato", "Lato Vandal", "Lato Prime"],
    "Lex": ["Lex", "Lex Prime"],
    "Sicarus": ["Sicarus", "Sicarus Prime"],
    "Vasto": ["Vasto", "Vasto Prime"],
    "Zylok": ["Zylok", "Zylok Prime"],
    "Bo": ["Bo", "MK1-Bo", "Bo Prime"],
    "Destreza": ["Destreza", "Destreza Prime"],
    "Furax": ["Furax", "MK1-Furax", "Furax Wraith"],
    "Magistar": ["Magistar", "Sancti Magistar"],
    "Obex": ["Obex", "Prisma Obex"],
    "Okina": ["Okina", "Okina Prime"],
    "Skana": ["Skana", "Prisma Skana", "Skana Prime"],
}
# which infobox attack is the Incarnon form, and which AoE attacks add to it
FORM_PICK = {"Onos": (1, [2]), "Stug": (1, []), "Laetum": (0, [1]), "Zylok": (0, [1])}
# forms left unscored, with the reason shown in the app
FORM_SKIP = {
    "Vectis": "the wiki's infobox (5 Cold) and its Incarnon text (150 Cold) disagree",
}
# melee Incarnon forms: what Evolution I adds while the form is up
MELEE_FORM = {
    "Praedos": {"fire_rate": 0.4},
    "Innodem": {"fire_rate": 0.4},
    "Thalys": {"fire_rate": 0.4},
    "Ruvox": {},
    "Magistar": {"damage": 1.0, "windup_speed": 0.5},
    "Sibear": {"damage": 1.0, "windup_speed": 0.5},
}
MELEE_FORM_DEFAULT = {"damage": 1.0}  # Genesis melee: "+100% Melee Damage" (Skana: additive)

EFFECTS: dict[str, dict[str, dict]] = {
    "Boar": {
        "Reified Bane": {"bd": 10}, "Fortress Salvo": {"bd": 16},
        "Elemental Balance": {"bsc": 0.96}, "Critical Parallel": {"bcc": 0.20, "bcd": 0.5},
        "Survivor's Edge": {"bcc": 0.10, "bsc": 0.48},
    },
    "Boltor": {
        "Hunter's Mantra": {"bd": [18, 4, 4]}, "Crimson Overture": {"bd": [12, 0, 0]},
        "Extended Volley": {"bmag": 20}, "Rapid Reinforcement": {"reload": 0.6},
        "Elemental Balance": {"bsc": [0.20, 0.20, 0.18]},
        "Survivor's Edge": {"bcc": [0.08, 0.04, 0.10], "bsc": [0.08, 0.04, 0.10]},
        "Commodore's Fortune": {"bcc": [0.12, 0.06, 0.14]},
    },
    "Braton": {
        "Daring Reverie": {"bd": [24, 28, 12, 4]},
        "Munitions Grit": {"bd": [14, 20, 8, 2], "multishot": 0.2},
        "Critical Parallel": {"bcc": [0.16, 0.18, 0.16, 0.18], "bcd": [0.4, 0.5, 0.4, 0.2]},
        "Prelude of Might": {"lowcrit": [0.5, [3.4, 3.3, 3.0, 3.0]]},
        "Survivor's Edge": {"bcc": [0.10, 0.12, 0.10, 0.10], "bsc": [0.12, 0.12, 0.12, 0.14]},
    },
    "Burston": {
        "Forceful Finality": {"bd": 42}, "Fortress Salvo": {"bd": 42}, "Extended Volley": {"bmag": 21},
        "Absolute Valor": {"bcc": 0.22}, "Fatal Affliction": {"per_status_damage": 0.40},
    },
    "Dera": {
        "Crimson Overture": {"bd": [8, 6]}, "Paragon Essence": {"bd": [6, 4]},
        "Extended Volley": {"bmag": [22, 30]},
        "Deathtrap Trigger": {"bcc": 0.14, "bcd": [0.6, 0.4]}, "Elemental Balance": {"bsc": [0.18, 0.14]},
    },
    "Dread": {
        "Hitman's Opportunity": {"bd": 70}, "Stalker's Resentment": {"bd": 50},
        "Survivor's Edge": {"bcc": 0.10, "bsc": 0.10}, "Elemental Balance": {"bsc": 0.24},
        "Zeroed In": {"bcd": 1.0},
    },
    "Gorgon": {
        "Hunter's Mantra": {"bd": [10, 5, 5]}, "Hoplite Virtue": {"bd": [10, 5, 5]},
        "Rapid Reinforcement": {"reload": 0.5},
        "Survivor's Edge": {"bcc": [0.08, 0.08, 0.02], "bsc": [0.09, 0.06, 0.06]},
        "Elemental Balance": {"bsc": [0.16, 0.14, 0.12]}, "Absolute Valor": {"bcc": [0.14, 0.14, 0.06]},
    },
    "Latron": {
        "Riddled Target": {"bd": [48, 12, 6]}, "Swift Punishment": {"bd": [48, 12, 6]},
        "Extended Volley": {"bmag": 15}, "Deadhead": {"headshot_bonus": 1.0},
        "Critical Parallel": {"bcc": [0.30, 0.24, 0.24], "bcd": [0.6, 0.2, 0.2]},
    },
    "Miter": {
        "Swift Sawblades": {"bd": 77}, "Plentiful Mayhem": {"bd": 57},
        "Commodore's Fortune": {"bcc": 0.22}, "Critical Parallel": {"bcc": 0.12, "bsc": 0.12},
    },
    "Paris": {
        "Deadly Pace": {"bd": [40, 50, 20]}, "Guardian's Might": {"bd": [40, 50, 20]},
        "Elemental Balance": {"bsc": 0.60}, "Striking Succession": {"stacks": {"bd": 60}},
    },
    "Soma": {
        "Fortress Salvo": {"bd": 12}, "Fortifying Bloodshed": {"bd": 10},
        "Rapid Reinforcement": {"reload": 0.5}, "Fresh Havoc": {"bd": 12},
        "Fatal Affliction": {"per_status_damage": 0.40}, "Zeroed In": {"bcd": 0.6},
    },
    "Strun": {
        "Tenno Targeting": {"bd": [54, 68, 24, 2]},
        "Blazing Barrel": {"bd": [54, 68, 24, 2], "stacks": {"bms": 0.25}},
        "Rapid Reinforcement": {"reload": 0.6},
        "Elemental Balance": {"bsc": [1.32, 1.10, 1.00, 1.36]},
        "Commodore's Fortune": {"bcc": [0.16, 0.10, 0.12, 0.12]},
        "Brutal Edge": {"bcc": [0.04, 0.02, 0.04, 0.04], "bsc": [0.48, 0.20, 0.48, 0.48]},
    },
    "Sybaris": {
        "Well Rehearsed": {"bd": [20, 15, 15]},
        "Blazing Barrel": {"bd": [20, 15, 15], "stacks": {"multishot": 0.5}},
        "Extended Volley": {"bmag": [8, 10, 12]},
        "Elemental Dominance": {"bsc": [0.15, 0.15, 0.08], "double_in_form": 1},
        "Reaver's Rapture": {"stacks": {"damage": 0.8}},
        "Survivor's Edge": {"bcc": 0.05, "bsc": 0.10},
    },
    "Torid": {
        "Final Fusillade": {"bd": 51}, "Plentiful Mayhem": {"bd": 31}, "Extended Volley": {"bmag": 9},
        "Commodore's Fortune": {"bcc": 0.20}, "Survivor's Edge": {"bcc": 0.15, "bsc": 0.15},
        "Elemental Balance": {"bsc": 0.34},
    },
    "Vectis": {
        "Inciting Incident": {"bd": [100, 200]}, "Lone Enforcer": {"bd": [75, 150]},
        "Rapid Reinforcement": {"reload": 0.6}, "Deadhead": {"headshot_bonus": 0.25},
        "Critical Parallel": {"bcc": [0.10, 0.08], "bcd": 0.5},
    },
    "Felarx": {
        "Brutal Edge": {"fcc": 0.10, "fsc": 0.10}, "Racking Wrath": {"fcc": -0.10, "fsc": 0.20},
        "Devastating Attrition": {"noncrit": 10.0},
    },
    "Phenmor": {
        "Rapid Wrath": {"fire_rate": 0.20},
        "Survivor's Edge": {"fcc": 0.10, "fsc": 0.10}, "Elemental Excess": {"fcc": -0.10, "fsc": 0.20},
        "Devouring Attrition": {"noncrit": 10.0},
    },
    "Praedos": {"Whirling Flurry": {"fire_rate": 0.20}, "Kinetic Harmony": {"windup_speed": 1.0}},
    "Angstrum": {
        "Haven Foray": {"bd": 50}, "Paladin Virtue": {"bd": 75}, "Rapid Reinforcement": {"reload": 0.5},
        "Critical Parallel": {"bcc": [0.14, 0.10], "bcd": 0.2},
        "Survivor's Edge": {"bcc": [0.09, 0.06], "bsc": [0.09, 0.06]},
        "Fatal Affliction": {"per_status_damage": 0.40},
    },
    "Atomos": {
        "Paladin Virtue": {"bd": 24}, "Hoplite Virtue": {"bd": 24},
        "Elemental Balance": {"bsc": 0.20}, "Commodore's Fortune": {"bcc": 0.19},
        "Survivor's Edge": {"bcc": 0.10, "bsc": 0.10},
    },
    "Ballistica": {
        "Headcracker": {"bd": [30, 10, 3]}, "Prolific Perforation": {"bd": [30, 10, 3]},
        "Rapid Reinforcement": {"reload": 0.5},
        "Elemental Balance": {"bsc": [0.20, 0.20, 0.72]},
        "Survivor's Edge": {"bcc": [0.10, 0.08, 0.07], "bsc": [0.10, 0.08, 0.28]},
        "Critical Parallel": {"bcc": [0.15, 0.14, 0.12], "bcd": 1.0},
    },
    "Bronco": {
        "Speeding Bullet": {"bd": [36, 30]}, "Infused Shots": {"bd": [20, 16]},
        "Extended Volley": {"bmag": 2}, "Commodore's Fortune": {"bcc": 0.20}, "Rain of Lead": {"bms": 2},
    },
    "Cestra": {
        "Steadfast Grit": {"bd": 10}, "Fortress Salvo": {"bd": 10}, "Rapid Reinforcement": {"reload": 0.5},
        "Survivor's Edge": {"bcc": 0.18}, "Deathtrap Trigger": {"bcd": 2.0},
    },
    "Despair": {
        "Fatal Affliction": {"bd": 50, "per_status_damage": 0.40}, "Stalker's Vendetta": {"bd": 60},
        "Rapid Reinforcement": {"reload": 1.0}, "Elemental Balance": {"bsc": 0.24},
        "Survivor's Edge": {"bcc": 0.12, "bsc": 0.12}, "Critical Parallel": {"bcc": 0.18, "bcd": 0.4},
    },
    "Dual Toxocyst": {
        "Carnage Reign": {"bd": 60, "per_status_damage": 0.33},
        "Fevered Frenzy": {"bd": 50, "stacks": {"multishot": 1.0}},
        "Commodore's Fortune": {"bcc": 0.20},
    },
    "Furis": {
        "Haven Foray": {"bd": [28, 34]}, "Stormburst": {"bd": [28, 34]}, "Extended Volley": {"bmag": 25},
        "Prelude of Might": {"lowcrit": [0.4, 3.0]}, "Elemental Balance": {"bsc": [0.28, 0.39]},
    },
    "Gammacor": {
        "Sage's Resolve": {"bd": 10}, "Infused Shots": {"bd": 6}, "Extended Volley": {"bmag": 40},
        "Critical Parallel": {"bcc": [0.20, 0.10], "bcd": 0.2},
        "Survivor's Edge": {"bcc": [0.12, 0.06], "bsc": [0.10, 0.06]},
        "Elemental Balance": {"bsc": [0.20, 0.10]},
    },
    "Kunai": {
        "Swift Conclusion": {"bd": [70, 80]}, "Sage's Resolve": {"bd": [80, 70]},
        "Extended Volley": {"bmag": 10}, "Rapid Reinforcement": {"reload": 0.5},
        "Accelerating Volley": {"stacks": {"fire_rate": 1.0}},
        "Survivor's Edge": {"bcc": 0.12, "bsc": 0.12},
    },
    "Lato": {
        "Haven Foray": {"bd": [40, 22, 2]}, "Reified Bane": {"bd": [30, 12, 2], "stacks": {"bd": [30, 30, 24]}},
        "Survivor's Edge": {"bcc": [0.20, 0.06, 0.04], "bsc": [0.12, 0.12, 0.10]},
        "Carnage Reign": {"per_status_damage": 0.40},
    },
    "Lex": {
        "Hoplite Virtue": {"bd": [80, 20]}, "Trusty Sidearm": {"bd": [80, 20]}, "Extended Volley": {"bmag": 10},
        "Elemental Balance": {"bsc": [0.40, 0.30]}, "Critical Parallel": {"bcc": [0.20, 0.19], "bcd": 0.4},
    },
    "Sicarus": {
        "Feigned Retreat": {"bd": [50, 40]}, "King's Gambit": {"bd": [50, 40]},
        "Rapid Reinforcement": {"reload": 0.5}, "Extended Volley": {"bmag": [9, 12]},
        "Commodore's Fortune": {"bcc": [0.18, 0.14]},
        "Survivor's Edge": {"bcc": [0.12, 0.09], "bsc": [0.12, 0.09]},
    },
    "Stug": {
        "Blazing Barrel": {"bd": 175, "stacks": {"multishot": 0.5}}, "Overcharge Blast": {"bd": 300},
        "Rapid Reinforcement": {"reload": 0.5}, "Survivor's Edge": {"bcc": 0.15, "bsc": 0.15},
        "Deathtrap Trigger": {"bcc": 0.25, "bcd": 1.5},
        "Elemental Dominance": {"bsc": 0.20, "double_in_form": 1},
    },
    "Vasto": {
        "Lone Gun": {"bd": [66, 24]}, "Deathtrap Trigger": {"bd": [66, 24]}, "Extended Volley": {"bmag": 6},
        "Commodore's Fortune": {"bcc": [0.16, 0.18]}, "Survivor's Edge": {"bcc": 0.10, "bsc": 0.10},
    },
    "Zylok": {
        "Precision's Payoff": {"bd": [76, 30]},
        "Mauler's Magazine": {"bd": [76, 30], "stacks": {"bcd": 2.0}},
        "Extended Volley": {"bmag": [12, 18]}, "Rapid Reinforcement": {"reload": 0.5},
        "Survivor's Edge": {"bcc": [0.20, 0.22], "bsc": [0.20, 0.16]},
        "Commodore's Fortune": {"bcc": [0.32, 0.30]}, "Fatal Affliction": {"per_status_damage": 0.40},
    },
    "Laetum": {
        "Rapid Wrath": {"fire_rate": 0.20}, "Caput Mortuum": {"headshot_bonus": 0.5},
        "Elemental Excess": {"fcc": -0.10, "fsc": 0.20}, "Devouring Attrition": {"noncrit": 10.0},
    },
    "Onos": {
        "Rapid Wrath": {"fire_rate": 0.25}, "Rapid Reinforcement": {"reload": 0.3},
        "Elemental Excess": {"fcc": -0.10, "fsc": 0.20},
    },
    "Ack & Brunt": {
        "Templar's Wrath": {"bd": 150}, "Shieldmaiden's Rush": {"bd": 150}, "Swift Break": {"windup_speed": 0.7},
        "Absolute Valor": {"bcc": 0.17}, "Versatile Creed": {"bcc": 0.09, "bsc": 0.09},
    },
    "Anku": {
        "Edge of Justice": {"bd": 50, "fire_rate": 0.4}, "Guardian's Promise": {"bd": 50},
        "Swift Break": {"windup_speed": 0.6}, "Absolute Dominion": {"bsc": 0.20},
        "Subtle Force": {"bcc": 0.06, "bsc": 0.14}, "Absolute Valor": {"bcc": 0.12},
    },
    "Bo": {
        "Stalwart Oak": {"bd": [110, 90, 34]}, "Swordsman's Flourish": {"bd": [100, 85, 30]},
        "Subtle Force": {"bcc": [0.12, 0.15, 0.06], "bsc": [0.12, 0.15, 0.06]},
        "Absolute Dominion": {"bsc": [0.34, 0.38, 0.30]},
    },
    "Ceramic Dagger": {
        "Gun and Blade": {"bd": 100}, "Breacher's Opportunity": {"bd": 120},
        "Absolute Dominion": {"bsc": 0.30}, "Absolute Valor": {"bcc": 0.30},
    },
    # Destreza and Obex: the wiki says their Evolution II base damage doesn't work
    "Destreza": {"Absolute Dominion": {"bsc": [0.20, 0.16]}, "Critical Forte": {"bcd": [1.2, 0.6]}},
    "Dual Ichor": {
        "Alchemist's Wrath": {"bd": 90}, "Ronin's Rush": {"bd": 90}, "Swift Break": {"windup_speed": 1.0},
        "Absolute Valor": {"bsc": 0.34},
    },
    "Furax": {
        "Swordsman's Flourish": {"bd": [110, 100, 65]}, "Kill Joy": {"bd": [90, 80, 55]},
        "Absolute Dominion": {"bsc": [0.24, 0.22, 0.14]},
    },
    "Hate": {
        "Swordsman's Flourish": {"bd": 30}, "Stalker's Legacy": {"bd": 30}, "Swift Break": {"windup_speed": 0.6},
        "Absolute Valor": {"bcc": 0.10}, "Absolute Dominion": {"bsc": 0.20},
        "Subtle Force": {"bcc": 0.06, "bsc": 0.10},
    },
    "Magistar": {
        "Crushing Verdict": {"bd": [100, 20]}, "Edge Of Justice": {"bd": [100, 20], "fire_rate": 0.4},
        "Swift Break": {"windup_speed": 0.3}, "Subtle Force": {"bcc": 0.08, "bsc": 0.08},
        "Critical Parallel": {"bcc": [0.16, 0.12], "bcd": [1.0, 0.2]},
    },
    "Nami Solo": {
        "Brigand's Frenzy": {"bd": 80}, "Master's Flourish": {"bd": 80}, "Swift Break": {"windup_speed": 0.5},
        "Absolute Valor": {"bcc": 0.21}, "Versatile Creed": {"bcc": 0.14, "bsc": 0.14},
        "Absolute Dominion": {"bsc": 0.30},
    },
    "Obex": {
        "Subtle Force": {"bcc": 0.10, "bsc": [0.18, 0.12]}, "Absolute Dominion": {"bsc": [0.28, 0.20]},
        "Critical Coefficient": {"bcd": 0.6, "double_in_form": 1},
    },
    "Okina": {
        "Seeing Red": {"bd": [60, 20]}, "Synergist Surety": {"bd": [60, 20], "stacks": {"status_damage": [0.40, 0.30]}},
        "Commodore's Fortune": {"bcc": [0.12, 0.06]}, "Alchemy of War": {"bsc": [0.16, 0.12]},
        "Survivor's Edge": {"bcc": [0.06, 0.02], "bsc": [0.10, 0.08]},
    },
    "Sibear": {
        "Master's Shatter": {"bd": 20}, "Thane's Wrath": {"bd": 20}, "Kinetic Harmony": {"windup_speed": 0.6},
        "Absolute Valor": {"bcc": 0.25},
    },
    "Skana": {
        "Guardian's Promise": {"bd": [100, 100, 10]}, "Wartime Nerve": {"bd": [90, 90, 10]},
        "Swift Break": {"windup_speed": 0.5},
        "Survivor's Edge": {"bcc": [0.12, 0.12, 0.02], "bsc": [0.10, 0.10, 0.04]},
        "Elemental Excess": {"bsc": [0.20, 0.20, 0.10]}, "Absolute Valor": {"bcc": [0.25, 0.25, 0.04]},
    },
    "Innodem": {"Bladed Harmony": {"fire_rate": 0.25}},
    "Ruvox": {"Lethal Impetus": {"stacks": {"fire_rate": 0.45}}},
    "Thalys": {"Whirling Flurry": {"fire_rate": 0.20}},
}  # fmt: skip


def _pct(v) -> float | None:
    if v in (None, ""):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return None if not m else float(m.group()) / (100 if "%" in str(v) else 1)


def _damage(d) -> dict[str, float]:
    return {k.lower(): float(v) for k, v in (d or {}).items() if isinstance(v, (int, float)) and v}


def form_of(w: dict) -> dict | None:
    forms = [
        f
        for f in w.get("forms") or []
        if f.get("variant") in (None, "all") or "Prime" not in str(f["variant"])
    ]
    if not forms or not forms[0].get("damage"):
        return None
    main, extra = FORM_PICK.get(w["weapon"], (0, []))
    f = forms[main]
    damage = _damage(f["damage"])
    radial: dict[str, float] = {}
    if f.get("radial") and f["radial"].get("damage") and f.get("projectile_type") != "AoE":
        radial = _damage(f["radial"]["damage"])
    for i in extra:
        for k, v in _damage(forms[i].get("damage")).items():
            radial[k] = radial.get(k, 0.0) + v
    return {
        "damage": damage,
        "radial": radial,
        "crit_chance": _pct(f.get("crit_chance")),
        "crit_multiplier": _pct(f.get("crit_multiplier")),
        "status_chance": _pct(f.get("status_chance")),
        "fire_rate": _pct(f.get("fire_rate")),
        "multishot": float(f.get("multishot") or 1),
        "charges": f.get("charges"),
        "trigger": f.get("trigger"),
        "note": f.get("notes") or "",
    }


def main() -> None:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    weapons = {}
    for name, w in sorted(raw.items()):
        effects = EFFECTS.get(name, {})
        perks = []
        names = set()
        for evo in w.get("evolutions") or []:
            for p in evo.get("perks") or []:
                names.add(p["name"])
                perks.append(
                    {
                        "tier": evo["tier"],
                        "name": p["name"],
                        "text": " ".join(p.get("lines") or []),
                        "note": p.get("note") or "",
                        "effect": effects.get(p["name"], {}),
                    }
                )
        missing = set(effects) - names
        if missing:
            raise SystemExit(f"{name}: effects for perks not on the page: {sorted(missing)}")
        melee = w.get("slot") == "melee"
        entry = {
            "page": w["page"],
            "slot": {"primary": "PRIMARY", "secondary": "SECONDARY", "melee": "MELEE"}[w["slot"]],
            "genesis": name in GENESIS,
            "variants": VARIANTS.get(name, [name]),
            "charge": w.get("charge"),
            "evo1": w.get("evo1") or "",
            "perks": perks,
        }
        if melee:
            entry["melee_form"] = MELEE_FORM.get(name, MELEE_FORM_DEFAULT)
        elif name in FORM_SKIP:
            entry["form_skip"] = FORM_SKIP[name]
        else:
            entry["form"] = form_of(w)
        weapons[name] = entry
    # Soma Prime: the only per-variant form figure on the page (EVO1: 3% status per pellet)
    weapons["Soma"]["form_variants"] = {"Soma Prime": {"status_chance": 0.03}}
    OUT.write_text(
        json.dumps(
            {
                "source": "Warframe Wiki (https://wiki.warframe.com), each weapon's page: Incarnon form "
                "infobox and Evolution table",
                "license": "CC BY-NC-SA 3.0; numbers and short paraphrases, see docs/LEGAL.md",
                "last_verified": "2026-11-28",
                "weapons": weapons,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(weapons)} weapons -> {OUT}")


if __name__ == "__main__":
    main()
