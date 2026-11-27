"""Damage of a gun with a set of mods, following the wiki's current formulas.

Sources (wiki.warframe.com, read 2026-11-27; see docs/BUILDS.md for quotes and dates):
Damage/Calculation, Damage, Critical_Hit, Status_Effect, Faction_Damage_Bonus,
Damage/Overview_Table (Update 36 faction modifiers), Reload.

Per projectile:
  base      = weapon damage x (1 + sum of base damage mods)          Serration, Heavy Caliber
  physical  = base share of that type x (1 + physical mod)           only types the gun has
  elemental = base total x elemental mod %                            per mod, then combined
Elements combine in mod order (innate elements last; an innate element moves to the slot of
a mod with the same element); an innate combined element never combines further.
Per shot = sum over types (damage x faction modifier) x multishot x (1 + CC x (CD - 1)) x bane.
Sustained DPS = per shot x fire rate x mag / (fire rate x reload + mag).

Not modelled: armor and its stripping, damage over time from status, headshots and weak
points, Riven mods, arcanes, Incarnon forms. Status is reported (chance and procs per
second), not counted in DPS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

from .mods import ELEMENTS, PHYSICAL, ModEffect
from .weapons import Gun

PRIMARY_ELEMENTS = ("heat", "cold", "electricity", "toxin")
COMBINE = {
    frozenset(("cold", "heat")): "blast",
    frozenset(("electricity", "heat")): "radiation",
    frozenset(("heat", "toxin")): "gas",
    frozenset(("cold", "electricity")): "magnetic",
    frozenset(("cold", "toxin")): "viral",
    frozenset(("electricity", "toxin")): "corrosive",
}
# Damage/Overview_Table, as of Update 36: x1.5 vulnerable, x0.5 resistant
FACTION_MODIFIERS: dict[str, dict[str, float]] = {
    "Grineer": {"impact": 1.5, "corrosive": 1.5},
    "Kuva Grineer": {"impact": 1.5, "corrosive": 1.5, "heat": 0.5},
    "Corpus": {"puncture": 1.5, "magnetic": 1.5},
    "Corpus Amalgam": {"electricity": 1.5, "magnetic": 1.5, "blast": 0.5},
    "Infested": {"slash": 1.5, "heat": 1.5},
    "Infested Deimos": {"blast": 1.5, "gas": 1.5, "viral": 0.5},
    "Orokin": {"puncture": 1.5, "viral": 1.5, "radiation": 0.5},
    "Sentient": {"cold": 1.5, "radiation": 1.5, "corrosive": 0.5},
    "Narmer": {"slash": 1.5, "toxin": 1.5, "magnetic": 0.5},
    "Murmur": {"electricity": 1.5, "radiation": 1.5, "viral": 0.5},
    "Zariman": {"void": 1.5},
    "Scaldra": {"impact": 1.5, "corrosive": 1.5, "gas": 0.5},
    "Techrot": {"gas": 1.5, "magnetic": 1.5, "cold": 0.5},
    "Anarchs": {"impact": 1.5, "electricity": 1.5, "radiation": 0.5},
}
# bane mods that work on a target faction ("Damage to Grineer" also hits Kuva Grineer)
BANE_FOR = {
    "Grineer": "Grineer",
    "Kuva Grineer": "Grineer",
    "Corpus": "Corpus",
    "Corpus Amalgam": "Corpus",
    "Infested": "Infested",
    "Infested Deimos": "Infested",
    "Orokin": "Orokin",
    "Murmur": "Murmur",
}
NUMERIC = (
    "damage",
    "multishot",
    "crit_chance",
    "crit_damage",
    "status_chance",
    "fire_rate",
    "magazine",
    "reload",
)


@dataclass
class Totals:
    sums: dict[str, float] = field(default_factory=dict)
    elements: list[tuple[str, float]] = field(default_factory=list)  # (element, %) in slot order
    physical: dict[str, float] = field(default_factory=dict)
    bane: dict[str, float] = field(default_factory=dict)


def add_up(effects: list[ModEffect], *, stacks: bool, fire_rate_locked: bool = False) -> Totals:
    """Sum mod effects. ``fire_rate_locked``: a Cannonade mod is on, fire rate mods do nothing."""
    t = Totals()
    for e in effects:
        stats = dict(e.stats)
        if stacks:
            for k, (per, n) in e.stacks.items():
                stats[k] = stats.get(k, 0.0) + per * n
        for k, v in stats.items():
            if k in NUMERIC:
                t.sums[k] = t.sums.get(k, 0.0) + v
            elif k in ELEMENTS:
                t.elements.append((k, v))
            elif k in PHYSICAL:
                t.physical[k] = t.physical.get(k, 0.0) + v
            elif k.startswith("bane:"):
                f = k.split(":", 1)[1]
                t.bane[f] = t.bane.get(f, 0.0) + v
    if fire_rate_locked:
        t.sums.pop("fire_rate", None)
    return t


def element_damage(gun: Gun, t: Totals, base_mult: float) -> dict[str, float]:
    """Elemental damage per projectile after combining, in the order the game uses."""
    base_total = gun.total * base_mult
    added: dict[str, float] = {}
    order: list[str] = []
    for el, pct in t.elements:
        added[el] = added.get(el, 0.0) + base_total * pct
        if el not in order:
            order.append(el)
    innate = {k: v * base_mult for k, v in gun.damage.items() if k in ELEMENTS}
    # innate primaries go last unless a mod has the same element (then they join that slot)
    for el in sorted((k for k in innate if k in PRIMARY_ELEMENTS), key=PRIMARY_ELEMENTS.index):
        added[el] = added.get(el, 0.0) + innate[el]
        if el not in order:
            order.append(el)
    out: dict[str, float] = {
        k: v for k, v in innate.items() if k not in PRIMARY_ELEMENTS
    }  # innate combined stay
    primaries = [e for e in order if e in PRIMARY_ELEMENTS]
    for e in order:
        if e not in PRIMARY_ELEMENTS:  # a combined element from a mod
            out[e] = out.get(e, 0.0) + added[e]
    while len(primaries) >= 2:
        a, b = primaries.pop(0), primaries.pop(0)
        c = COMBINE[frozenset((a, b))]
        out[c] = out.get(c, 0.0) + added[a] + added[b]
    for e in primaries:
        out[e] = out.get(e, 0.0) + added[e]
    return out


@dataclass
class Result:
    per_shot: float
    burst_dps: float
    sustained_dps: float
    crit_chance: float
    crit_multiplier: float
    status_chance: float
    procs_per_second: float
    multishot: float
    fire_rate: float
    magazine: int
    reload: float
    by_type: dict[str, float]  # per projectile, before faction modifiers

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def evaluate(
    gun: Gun, t: Totals, target: str | None = None, element_order: list[int] | None = None
) -> Result:
    if element_order is not None:
        t = Totals(t.sums, [t.elements[i] for i in element_order], t.physical, t.bane)
    s = t.sums
    base_mult = 1 + s.get("damage", 0.0)
    by_type: dict[str, float] = {}
    for k in PHYSICAL:
        if gun.damage.get(k):
            by_type[k] = gun.damage[k] * base_mult * (1 + t.physical.get(k, 0.0))
    for k, v in element_damage(gun, t, base_mult).items():
        by_type[k] = by_type.get(k, 0.0) + v
    for k in ("void", "tau"):
        if gun.damage.get(k):
            by_type[k] = by_type.get(k, 0.0) + gun.damage[k] * base_mult
    mods = FACTION_MODIFIERS.get(target or "", {})
    per_projectile = sum(v * mods.get(k, 1.0) for k, v in by_type.items())
    bane = 1 + t.bane.get(BANE_FOR.get(target or "", ""), 0.0)
    cc = max(0.0, gun.crit_chance * (1 + s.get("crit_chance", 0.0)))
    cd = max(1.0, gun.crit_multiplier * (1 + s.get("crit_damage", 0.0)))
    ms = max(0.0, gun.multishot * (1 + s.get("multishot", 0.0)))
    sc = max(0.0, gun.status_chance * (1 + s.get("status_chance", 0.0)))
    fr = max(0.05, gun.fire_rate * (1 + s.get("fire_rate", 0.0)))
    mag = max(1, round(gun.magazine * (1 + s.get("magazine", 0.0))))
    reload = gun.reload / max(0.05, 1 + s.get("reload", 0.0))
    per_shot = per_projectile * ms * (1 + cc * (cd - 1)) * bane
    burst = per_shot * fr
    sustained = burst * mag / (fr * reload + mag) if reload > 0 else burst
    return Result(
        per_shot=per_shot,
        burst_dps=burst,
        sustained_dps=sustained,
        crit_chance=cc,
        crit_multiplier=cd,
        status_chance=sc,
        procs_per_second=ms * sc * fr * (mag / (fr * reload + mag) if reload > 0 else 1),
        multishot=ms,
        fire_rate=fr,
        magazine=mag,
        reload=reload,
        by_type=by_type,
    )


def best_order(gun: Gun, t: Totals, target: str | None) -> tuple[Result, list[int]]:
    """Try every slot order of the elemental mods (it decides what combines) and keep the best."""
    n = len(t.elements)
    if n <= 1:
        return evaluate(gun, t, target), list(range(n))
    best: tuple[Result, list[int]] | None = None
    seen: set[tuple[str, ...]] = set()
    for perm in permutations(range(n)):
        key = tuple(t.elements[i][0] for i in perm)
        if key in seen:
            continue
        seen.add(key)
        r = evaluate(gun, t, target, list(perm))
        if best is None or r.sustained_dps > best[0].sustained_dps:
            best = (r, list(perm))
    assert best is not None
    return best
