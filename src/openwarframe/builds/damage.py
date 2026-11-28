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

Against an enemy (see ``_against``): armor and its stripping by Corrosive and Heat, Viral,
Cold and the damage over time of Slash, Heat, Toxin, Electricity and Gas.
Melee heavy attacks (``heavy`` in the sums) are judged one attack at a time; see ``evaluate``.
Not modelled: weak points other than the head, Incarnon forms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import permutations

from .enemy import Enemy, armor_reduction
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
    "status_damage",
    "fire_rate",
    "magazine",
    "reload",
    # melee: mods that read the combo multiplier or the statuses on the target
    "combo_crit",
    "combo_status",
    "per_status_damage",
    # heavy attacks: Killing Blow, the doubled part of True Steel, wind-up mods; Melee Doughty
    "heavy_damage",
    "heavy_crit_chance",
    "windup_speed",
    "heavy_efficiency",
    "doughty",
    "bow_fire_rate",
    # headshots and weak points: Target Acquired / Meticulous Aim / Deadhead, Meticulous Aim's
    # body penalty, Acuity; context: aiming at heads, the head's multiplier and crit bonus
    "headshot_bonus",
    "body_damage",
    "weak_point_damage",
    "weak_point_crit",
    "lock_multishot",
    "headshot",
    "head_mult",
    "headcrit",  # "(x2 for Bows)" on fire rate mods: the extra half, bows only
    # context set by the search, not by mods: combo multiplier, Gladiator mods equipped,
    # status types other sources keep on the target
    "combo",
    "gladiator",
    "extra_status",
    "heavy",
)
DOUGHTY_CAP = 50.0  # wiki Melee_Doughty: bonus critical multiplier at most +50x
# how long each status lasts (s), for "how many status types are on the target"
STATUS_DURATION = {"corrosive": 8.0}
STATUS_TYPES = (
    "impact", "puncture", "slash", "heat", "cold", "electricity", "toxin",
    "blast", "radiation", "gas", "magnetic", "viral", "corrosive",
)  # fmt: skip
# damage over time per proc: share of modded base damage per tick (wiki Damage/<Type>_Damage)
DOT = {"slash": 0.35, "heat": 0.5, "toxin": 0.5, "electricity": 0.5, "gas": 0.5}
DOT_TICKS = 6  # one per second for 6 seconds


@dataclass
class Totals:
    sums: dict[str, float] = field(default_factory=dict)
    elements: list[tuple[str, float]] = field(default_factory=list)  # (element, %) in slot order
    physical: dict[str, float] = field(default_factory=dict)
    bane: dict[str, float] = field(default_factory=dict)
    head: dict[str, float] = field(default_factory=dict)  # counted only when aiming at heads


def add_up(effects: list[ModEffect], *, stacks: bool, fire_rate_locked: bool = False) -> Totals:
    """Sum mod effects. ``fire_rate_locked``: a Cannonade mod is on, fire rate mods do nothing."""
    t = Totals()
    for e in effects:
        stats = dict(e.stats)
        if stacks:
            for k, (per, n) in e.stacks.items():
                stats[k] = stats.get(k, 0.0) + per * n
        for k, v in stats.items():
            if k.startswith("head:"):
                k2 = k.split(":", 1)[1]
                t.head[k2] = t.head.get(k2, 0.0) + v
            elif k in NUMERIC:
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
        t.sums.pop("bow_fire_rate", None)
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


def _stack_multiplier(n: float, first: float, per: float) -> float:
    """Bonus at n stacks: ``first`` at the first stack, ``per`` for each further one; linear below 1."""
    if n <= 0:
        return 0.0
    return first * n if n < 1 else first + per * (n - 1)


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
    # against the enemy (armor, status); without an enemy these equal the plain numbers
    direct_dps: float = 0.0
    status_dps: float = 0.0
    total_dps: float = 0.0
    armor: float = 0.0  # after stripping
    armor_reduction: float = 0.0
    corrosive_stacks: float = 0.0
    viral_stacks: float = 0.0
    heat_uptime: float = 0.0
    cold_stacks: float = 0.0
    magnetic_stacks: float = 0.0
    shield_dps: float = 0.0  # damage per second to shields while they are up
    time_to_kill: float = 0.0  # seconds for one reference enemy (0: not judged on one)
    effective_dps: float = 0.0  # (shields + health) / time to kill; the score
    status_types: float = 0.0  # status types on the target, for Condition Overload
    heavy: bool = False  # per-shot and per-second numbers are for one heavy attack
    windup: float = 0.0  # heavy attack wind-up after mods, seconds
    headshot: bool = False  # every hit lands on the head
    location_mult: float = 1.0  # head multiplier with bonuses, or the body multiplier

    def as_dict(self) -> dict:
        # infinity (nothing gets through) isn't valid JSON: say "unknown" instead
        return {
            k: (None if isinstance(v, float) and math.isinf(v) else v)
            for k, v in ((k, getattr(self, k)) for k in self.__dataclass_fields__)
        }


def evaluate(
    gun: Gun,
    t: Totals,
    target: str | None = None,
    element_order: list[int] | None = None,
    enemy: Enemy | None = None,
) -> Result:
    if element_order is not None:
        t = Totals(t.sums, [t.elements[i] for i in element_order], t.physical, t.bane, t.head)
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
    # melee (wiki Blood_Rush, Weeping_Wounds, Gladiator_Set): combo-scaling bonuses add
    # bonus x (combo multiplier - 1) to the crit or status mod total
    steps = max(0.0, s.get("combo", 1.0) - 1)
    heavy = bool(s.get("heavy")) and gun.heavy_mult > 0
    crit_bonus = (
        s.get("crit_chance", 0.0) + (s.get("combo_crit", 0.0) + 0.10 * s.get("gladiator", 0.0)) * steps
    )
    head = bool(s.get("headshot"))
    if head:
        crit_bonus += s.get("weak_point_crit", 0.0)  # Acuity: with Point Strike (wiki)
    if heavy:
        # wiki Heavy_Attack: Killing Blow joins the base damage bonus; True Steel's "x2 for Heavy
        # Attacks" and Melee Animosity add to the crit chance bonus
        crit_bonus += s.get("heavy_crit_chance", 0.0)
    cc = max(0.0, gun.crit_chance * (1 + crit_bonus))
    cd = max(1.0, gun.crit_multiplier * (1 + s.get("crit_damage", 0.0)))
    # Acuity: "Multishot cannot be modified"
    ms = gun.multishot if s.get("lock_multishot") else max(0.0, gun.multishot * (1 + s.get("multishot", 0.0)))
    sc = max(0.0, gun.status_chance * (1 + s.get("status_chance", 0.0) + s.get("combo_status", 0.0) * steps))
    bow = s.get("bow_fire_rate", 0.0) if gun.holster == "BOW" else 0.0
    fr = max(0.05, gun.fire_rate * (1 + s.get("fire_rate", 0.0) + bow))
    mag = max(1, round(gun.magazine * (1 + s.get("magazine", 0.0))))
    reload = gun.reload / max(0.05, 1 + s.get("reload", 0.0))
    uptime = mag / (fr * reload + mag) if reload > 0 else 1.0
    if heavy and s.get("heavy_damage"):
        f = (base_mult + s["heavy_damage"]) / base_mult
        by_type = {k: v * f for k, v in by_type.items()}
        base_mult += s["heavy_damage"]
        per_projectile = sum(v * mods.get(k, 1.0) for k, v in by_type.items())
    if s.get("doughty"):
        # Melee Doughty (wiki, 2026-11): +1.0x critical multiplier per 10% Puncture status
        # chance, rounded to 0.1, at most +50x
        share = by_type.get("puncture", 0.0) / (sum(by_type.values()) or 1.0)
        cd += min(DOUGHTY_CAP, round(s["doughty"] * sc * share * 10, 1))
    status_types = 0.0
    if s.get("per_status_damage"):
        # Condition Overload (wiki, 2026-10-12): +x per status type on the target, in the same
        # bonus as Pressure Point. Types this weapon keeps up (chance at least one proc is still
        # running), plus those other sources keep there.
        total_dmg = sum(by_type.values()) or 1.0
        procs = ms * sc * fr * uptime
        status_types = min(
            16.0,
            s.get("extra_status", 0.0)
            + sum(
                1 - math.exp(-procs * by_type.get(k, 0.0) / total_dmg * STATUS_DURATION.get(k, 6.0))
                for k in STATUS_TYPES
            ),
        )  # at most 16 statuses on one enemy
        factor = (base_mult + s["per_status_damage"] * status_types) / base_mult
        by_type = {k: v * factor for k, v in by_type.items()}
        base_mult *= factor
        per_projectile = sum(v * mods.get(k, 1.0) for k, v in by_type.items())
    windup = 0.0
    if heavy:
        # one heavy attack: weapon-type multiplier x combo multiplier (the combo is spent);
        # its status chance per hit is the weapon's, and it counts as one attack
        h = gun.heavy_mult * max(1.0, s.get("combo", 1.0))
        by_type = {k: v * h for k, v in by_type.items()}
        base_mult *= h
        per_projectile *= h
        fr, uptime = 1.0, 1.0
        windup = gun.windup / max(0.05, 1 + s.get("windup_speed", 0.0))
    # where the hit lands (wiki Enemy_Body_Parts, Critical_Hit, read 2026-11-28): a head takes
    # (head multiplier + 1.5 x Acuity's weak point damage) x (1 + headshot bonuses), and a crit
    # there gets x2 on top of the crit multiplier; Meticulous Aim's penalty hits the body
    if head:
        loc = (s.get("head_mult", 3.0) + 1.5 * s.get("weak_point_damage", 0.0)) * (
            1 + s.get("headshot_bonus", 0.0)
        )
    else:
        loc = max(0.0, 1 + s.get("body_damage", 0.0))
    headcrit = head and bool(s.get("headcrit", 1.0))
    per_shot = per_projectile * ms * (1 + cc * ((2 * cd if headcrit else cd) - 1)) * bane * loc
    burst = per_shot * fr
    sustained = burst * uptime
    extra = {}
    if enemy is not None:
        extra = _against(
            gun, t, by_type, mods, bane, cc, cd, ms, sc, fr, uptime, base_mult, enemy, heavy, loc, headcrit
        )
    else:
        extra = {"direct_dps": sustained, "total_dps": sustained, "effective_dps": sustained}
    return Result(
        per_shot=per_shot,
        burst_dps=burst,
        sustained_dps=sustained,
        crit_chance=cc,
        crit_multiplier=cd,
        status_chance=sc,
        procs_per_second=ms * sc * fr * uptime,
        multishot=ms,
        fire_rate=fr,
        magazine=mag,
        reload=reload,
        by_type=by_type,
        status_types=status_types,
        heavy=heavy,
        windup=windup,
        headshot=head,
        location_mult=loc,
        **extra,
    )


def _against(
    gun,
    t,
    by_type,
    mods,
    bane,
    cc,
    cd,
    ms,
    sc,
    fr,
    uptime,
    base_mult,
    enemy,
    heavy=False,
    loc=1.0,
    headcrit=False,
) -> dict:
    """Damage to one enemy while firing steadily: armor and its stripping, shields, Viral,
    Magnetic, Cold, and the damage over time of Slash, Heat, Toxin, Electricity and Gas.

    Proc type follows each type's share of the weapon's damage (before faction modifiers);
    stacks are proc rate x duration, capped (Corrosive 10 for 8 s; Viral, Magnetic 10 and
    Cold 9 for 6 s). Heat strips 50% while a Heat proc is active. Each DoT proc deals 6 ticks.

    Shields take every type except Toxin (hits and ticks go to health), without armor and with
    the Magnetic bonus; health takes damage reduced by armor and raised by Viral. With health and
    shields set, the score is the time to kill: shields first (Toxin hurts health meanwhile),
    then health.

    ``heavy``: one heavy attack instead of steady fire. Its own procs land after its hit, so the
    hit meets full armor; the procs (one of each, not stacks built up over time) count for its
    damage over time. "Per second" numbers are then per heavy attack.

    ``loc``: the head or body multiplier, on hits and on damage over time; ``headcrit``: crits on
    the head get x2 on the crit multiplier (hits only: the wiki doesn't give it to ticks).
    """
    total = sum(by_type.values()) or 1.0
    procs = ms * sc * fr * uptime
    rate = {k: procs * v / total for k, v in by_type.items()}
    # stacks = proc rate x duration; one heavy attack leaves its procs once
    dur = (lambda d: 1.0) if heavy else (lambda d: d)
    n_corr = min(10.0, rate.get("corrosive", 0.0) * dur(8))
    n_viral = min(10.0, rate.get("viral", 0.0) * dur(6))
    n_mag = min(10.0, rate.get("magnetic", 0.0) * dur(6))
    n_cold = min(9.0, rate.get("cold", 0.0) * dur(6))
    heat_up = 1 - math.exp(-rate.get("heat", 0.0) * dur(6))
    corr_strip = 0.26 * n_corr if n_corr < 1 else 0.20 + 0.06 * n_corr
    full_armor = 0.0 if enemy.stripped else enemy.armor
    armor = full_armor * (1 - 0.5 * heat_up) * (1 - corr_strip)
    dr = armor_reduction(armor)
    viral = 1 + _stack_multiplier(n_viral, 1.0, 0.25)
    magnetic = 1 + _stack_multiplier(n_mag, 1.0, 0.25)
    crit = 1 + cc * (cd + _stack_multiplier(n_cold, 0.10, 0.05) - 1)
    hc = 2.0 if headcrit else 1.0
    hit_dr, hit_viral, hit_mag, hit_crit = (
        (armor_reduction(full_armor), 1.0, 1.0, 1 + cc * (hc * cd - 1))
        if heavy
        else (dr, viral, magnetic, 1 + cc * (hc * (cd + _stack_multiplier(n_cold, 0.10, 0.05)) - 1))
    )
    # direct hits per second by type, before armor, Viral or Magnetic
    hits = {k: v * mods.get(k, 1.0) * ms * hit_crit * bane * loc * fr * uptime for k, v in by_type.items()}
    # damage over time per second by type: modded base x bane twice x that element's mod bonus
    base = gun.total * base_mult * bane
    elem: dict[str, float] = {}
    for el, pct in t.elements:
        elem[el] = elem.get(el, 0.0) + pct
    sd = 1 + t.sums.get("status_damage", 0.0)
    dots = {}
    for k, c in DOT.items():
        r = rate.get(k, 0.0)
        if r:
            tick = c * base * (1 + elem.get(k, 0.0)) * bane * sd * crit * loc
            # Slash bleed is Cinematic damage: no faction modifier, no armor
            dots[k] = r * DOT_TICKS * tick * (1.0 if k == "slash" else mods.get(k, 1.0))
    # to health: armor reduces everything but Slash bleed; Viral raises everything
    to_health = {k: v * (1 - hit_dr) * hit_viral for k, v in hits.items()}
    for k, v in dots.items():
        to_health[k] = to_health.get(k, 0.0) + v * (1.0 if k == "slash" else 1 - dr) * viral
    health_dps = sum(to_health.values())
    direct = sum(v * (1 - hit_dr) * hit_viral for v in hits.values())
    dot_total = health_dps - direct
    # to shields: everything but Toxin, no armor, Magnetic bonus; Toxin meanwhile hits health
    shield_dps = sum(v for k, v in hits.items() if k != "toxin") * hit_mag
    shield_dps += sum(v for k, v in dots.items() if k != "toxin") * magnetic
    bypass = to_health.get("toxin", 0.0)
    ttk, effective = 0.0, health_dps
    if enemy.health:
        ttk = _time_to_kill(enemy.health, enemy.shields, shield_dps, bypass, health_dps)
        effective = (enemy.health + enemy.shields) / ttk if ttk else 0.0
    return {
        "direct_dps": direct,
        "status_dps": dot_total,
        "total_dps": health_dps,
        "armor": armor,
        "armor_reduction": dr,
        "corrosive_stacks": n_corr,
        "viral_stacks": n_viral,
        "heat_uptime": heat_up,
        "cold_stacks": n_cold,
        "magnetic_stacks": n_mag,
        "shield_dps": shield_dps if enemy.shields else 0.0,
        "time_to_kill": ttk,
        "effective_dps": effective,
    }


def _time_to_kill(
    health: float, shields: float, shield_dps: float, bypass_dps: float, health_dps: float
) -> float:
    """Seconds to empty shields, then health. Damage that skips shields (Toxin) lands on health
    while the shields are still up. Returns infinity when nothing gets through."""
    if shields <= 0:
        return health / health_dps if health_dps > 0 else math.inf
    if shield_dps <= 0:
        return health / bypass_dps if bypass_dps > 0 else math.inf
    t1 = shields / shield_dps
    if bypass_dps * t1 >= health:
        return health / bypass_dps
    left = health - bypass_dps * t1
    return t1 + (left / health_dps if health_dps > 0 else math.inf)


def best_order(
    gun: Gun, t: Totals, target: str | None, enemy: Enemy | None = None
) -> tuple[Result, list[int]]:
    """Try every slot order of the elemental mods (it decides what combines) and keep the best."""
    n = len(t.elements)
    if n <= 1:
        return evaluate(gun, t, target, enemy=enemy), list(range(n))
    best: tuple[Result, list[int]] | None = None
    seen: set[tuple[str, ...]] = set()
    for perm in permutations(range(n)):
        key = tuple(t.elements[i][0] for i in perm)
        if key in seen:
            continue
        seen.add(key)
        r = evaluate(gun, t, target, list(perm), enemy=enemy)
        if best is None or r.effective_dps > best[0].effective_dps:
            best = (r, list(perm))
    assert best is not None
    return best
