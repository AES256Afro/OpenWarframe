"""Incarnon forms and evolution perks, from kb/builds/incarnon.json (Warframe Wiki facts,
gathered by tools/incarnon.py; the game data has no Incarnon stats).

A gun's Incarnon form is its own attack: the form's damage, crit, status, fire rate and
multishot replace the weapon's, mods apply as usual, and the form fires from its charges
without reloading. An area part of the attack (Braton's Heat burst) is added to the hit at full
strength. A melee Incarnon form keeps the weapon's attack and adds Evolution I's bonus
(+100% melee damage on Genesis weapons, attack speed on Praedos, Innodem and Thalys).

Evolution perks change base stats (counted before mods), or add after mods (Zariman crit and
status), or work like mods; see tools/incarnon.py for the keys.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache

from .weapons import Gun


@lru_cache(maxsize=1)
def _weapons() -> dict:
    from ..guide.kb import kb_dir

    try:
        return json.loads((kb_dir() / "builds" / "incarnon.json").read_text(encoding="utf-8"))["weapons"]
    except (OSError, ValueError, KeyError):
        return {}


def lookup(name: str) -> tuple[str, dict, int] | None:
    """(family, entry, variant index) for a weapon that has an Incarnon form or Genesis. Only the
    variants each page lists: Akimbo and Dual versions (Dex Furis) can't take a Genesis."""
    key = name.casefold()
    for fam, w in _weapons().items():
        names = [v.casefold() for v in w["variants"]]
        if key in names:
            return fam, w, names.index(key)
    return None


def _at(v, i: int):
    return v[min(i, len(v) - 1)] if isinstance(v, list) else v


def perk_effect(p: dict, vi: int) -> dict:
    """A perk's numbers for one variant."""
    out = {}
    for k, v in p.get("effect", {}).items():
        if k == "stacks":
            out[k] = {kk: _at(vv, vi) for kk, vv in v.items()}
        elif k == "lowcrit":
            out[k] = [v[0], _at(v[1], vi)]
        else:
            out[k] = _at(v, vi)
    return out


def _pct(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{round(v * 100, 1):g}%"


def describe(effect: dict) -> str:
    """What the build counts for a perk, for one variant (effect from ``perk_effect``)."""
    labels = {
        "fire_rate": "fire rate / attack speed",
        "per_status_damage": "damage per status type",
        "headshot_bonus": "headshot multiplier",
        "windup_speed": "heavy attack wind-up speed",
        "status_damage": "status damage",
    }
    bits = []
    for k, v in effect.items():
        if k == "bd":
            bits.append(f"+{v:g} base damage per projectile")
        elif k == "bcc":
            bits.append(f"{_pct(v)} base crit chance")
        elif k == "bcd":
            bits.append(f"+{v:g}x base crit multiplier")
        elif k == "bsc":
            bits.append(f"{_pct(v)} base status chance (Incarnon form; split over multishot)")
        elif k == "fcc":
            bits.append(f"{_pct(v)} crit chance after mods")
        elif k == "fsc":
            bits.append(f"{_pct(v)} status chance after mods")
        elif k == "bms":
            bits.append(f"+{v:g} base multishot")
        elif k == "bmag":
            bits.append(f"+{v:g} magazine")
        elif k == "noncrit":
            bits.append(f"x{1 + v:g} on non-critical hits (expected)")
        elif k == "lowcrit":
            bits.append(f"+{v[1]:g}x base crit multiplier below {round(v[0] * 100)}% crit chance")
        elif k == "double_in_form":
            bits.append("doubled in Incarnon form")
        elif k == "stacks":
            bits.append("at full stacks: " + describe(v))
        else:
            bits.append(f"{_pct(v)} {labels.get(k, k.replace('_', ' '))}")
    return ", ".join(bits)


def tiers(entry: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for p in entry["perks"]:
        out.setdefault(int(p["tier"]), []).append(p)
    return out


def can_form(entry: dict) -> bool:
    return entry["slot"] == "MELEE" or bool(entry.get("form"))


def apply(gun: Gun, entry: dict, vi: int, *, form: bool, perks: list[dict], stacks: bool) -> Gun:
    """A copy of ``gun`` with the Incarnon form (when ``form``) and the chosen perks."""
    g = copy.deepcopy(gun)
    bonus: dict[str, float] = {}

    def add(k: str, v: float) -> None:
        bonus[k] = bonus.get(k, 0.0) + v

    if form and entry["slot"] == "MELEE":
        for k, v in entry.get("melee_form", {}).items():
            add(k, v)
    elif form and entry.get("form"):
        f = entry["form"]
        extra = (entry.get("form_variants") or {}).get(g.name, {})
        g.damage = dict(f["damage"])
        for k, v in f.get("radial", {}).items():  # the area part, at full strength
            g.damage[k] = g.damage.get(k, 0.0) + v
        g.crit_chance = f["crit_chance"] or 0.0
        g.crit_multiplier = f["crit_multiplier"] or 1.0
        g.status_chance = extra.get("status_chance", f["status_chance"] or 0.0)
        g.fire_rate = f["fire_rate"] or g.fire_rate
        g.multishot = f["multishot"] or 1.0
        g.magazine, g.reload = int(f.get("charges") or 100), 0.0  # fires from charges, no reload
    ms = max(1.0, g.multishot)
    for p in perks:
        e = perk_effect(p, vi)
        if not form:
            e.pop("double_in_form", None)
        dbl = 2.0 if e.pop("double_in_form", None) else 1.0
        st = e.pop("stacks", {}) if stacks else {}
        e.pop("stacks", None)
        for k, v in [*e.items(), *st.items()]:
            if k == "bd":
                total = g.total or 1.0
                g.damage = {t: d * (total + v) / total for t, d in g.damage.items()}
            elif k == "bcc":
                g.crit_chance += v * dbl
            elif k == "bcd":
                g.crit_multiplier += v * dbl
            elif k == "bsc":
                g.status_chance += v * dbl / ms
            elif k == "fcc":
                add("flat_crit_chance", v)
            elif k == "fsc":
                add("flat_status_chance", v / ms)
            elif k == "bms":
                g.multishot += v
            elif k == "bmag":
                if not form:
                    g.magazine += int(v)
            elif k == "lowcrit":
                add("lowcrit_below", v[0])
                add("lowcrit_cd", v[1])
            else:
                add(k, v * dbl)
    g.bonus = bonus
    return g
