"""Find the mods that give a gun the most sustained damage against a target.

Greedy fill of the 8 slots, then swaps until no single swap helps. Damage is close to a
product of independent factors (base damage, multishot, crit, elements, fire rate), so this
finds the same build as trying every combination on the weapons checked in the tests, in a
fraction of the time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .arcanes import HEAVY_ONLY, STATUS_TRIGGERED, WEAPON_SCORED, load_weapon_arcanes, weapon_effect
from .damage import Result, Totals, add_up, best_order
from .enemy import Enemy, enemy_for
from .mods import ELEMENTS, GunMod, ModEffect, fits, load_gun_mods
from .weapons import Gun, load_gun

SLOTS = 8  # general slots
EXILUS_SLOTS = 1  # one more, for an exilus-capable mod only (isUtility)


def _slots_ok(picks) -> bool:
    """At most 8 general mods plus one exilus-capable mod."""
    return len(picks) <= SLOTS + EXILUS_SLOTS and sum(1 for p in picks if not p.mod.utility) <= SLOTS


CAPACITY = 60  # with an Orokin Catalyst / Orokin Reactor equivalent
# melee: a stance in a slot of matching polarity adds 10 capacity (5 otherwise), like an aura
STANCE_CAPACITY = 10
# pairs the game won't equip together beyond "same mod, other variant" (wiki infoboxes)
CONFLICTS = {
    frozenset(("Berserker Fury", "Fury")),
    frozenset(("Berserker Fury", "Primed Fury")),
    frozenset(("Galvanized Chamber", "Split Chamber")),
    frozenset(("Galvanized Chamber", "Split Flights")),
    frozenset(("Split Chamber", "Split Flights")),
    frozenset(("Galvanized Diffusion", "Barrel Diffusion")),
    frozenset(("Galvanized Hell", "Hell's Chamber")),
    frozenset(("Galvanized Aptitude", "Rifle Aptitude")),
    frozenset(("Galvanized Savvy", "Shotgun Savvy")),
    frozenset(("Galvanized Shot", "Sure Shot")),
    frozenset(("Galvanized Scope", "Argon Scope")),
    frozenset(("Galvanized Crosshairs", "Hydraulic Crosshairs")),
    frozenset(("Galvanized Acceleration", "Fatal Acceleration")),
}


@dataclass
class Pick:
    mod: GunMod
    rank: int
    effect: ModEffect
    owned: bool | None  # None: no inventory loaded


def clash(a: GunMod, b: GunMod) -> bool:
    if a.unique_name == b.unique_name or a.exclusive == b.exclusive:
        return True
    return frozenset((a.name, b.name)) in CONFLICTS or frozenset((a.exclusive, b.exclusive)) in CONFLICTS


def _score(
    gun: Gun, picks: list[Pick], target: str | None, stacks: bool, enemy: Enemy | None = None
) -> tuple[float, Result, list[int]]:
    locked = any(p.mod.locks_fire_rate for p in picks)
    t = add_up([p.effect for p in picks], stacks=stacks, fire_rate_locked=locked)
    if gun.slot == "MELEE":
        t.sums["combo"] = gun.combo
        t.sums["gladiator"] = sum(1 for p in picks if p.mod.name.startswith("Gladiator "))
        t.sums["heavy"] = 1.0 if gun.heavy else 0.0
    t.sums["extra_status"] = gun.extra_status
    for k, v in gun.arcane.items():  # the weapon arcane: its element goes after the mods'
        if k in ELEMENTS:
            t.elements.append((k, v))
        else:
            t.sums[k] = t.sums.get(k, 0.0) + v
    r, order = best_order(gun, t, target, enemy)
    return r.effective_dps, r, order


def forma_needed(picks: list[Pick]) -> int | None:
    """Slots to polarize (Forma) so the mods fit in 60; None if they can't fit at all.

    A slot whose polarity matches the mod halves its drain (rounded up). Polarize the
    costliest mods first.
    """
    cap = CAPACITY + (STANCE_CAPACITY if any(p.mod.slot == "MELEE" for p in picks) else 0)
    drains = sorted((p.mod.drain(p.rank) for p in picks), reverse=True)
    total = sum(drains)
    n = 0
    for d in drains:
        if total <= cap:
            return n
        total -= d - (d + 1) // 2
        n += 1
    return n if total <= cap else None


def _fits_capacity(picks: list[Pick]) -> bool:
    return forma_needed(picks) is not None


def candidates(gun: Gun, mods: list[GunMod], owned: dict[str, int] | None) -> list[Pick]:
    """Mods that fit, at max rank (or the best rank you own when ``owned`` is given)."""
    out = []
    for m in mods:
        if not fits(m, gun.cls):
            continue
        if owned is not None:
            if m.unique_name not in owned:
                continue
            rank = min(owned[m.unique_name], m.max_rank)
        else:
            rank = m.max_rank
        e = m.effect(rank)
        if not e.stats and not e.stacks:
            continue  # nothing the damage model counts
        out.append(Pick(m, rank, e, None if owned is None else True))
    return out


def search(
    gun: Gun, pool: list[Pick], target: str | None, stacks: bool, enemy: Enemy | None = None
) -> list[Pick]:
    chosen: list[Pick] = []
    while len(chosen) < SLOTS + EXILUS_SLOTS:
        base = _score(gun, chosen, target, stacks, enemy)[0] if chosen else 0.0
        best, gain = None, 0.0
        for p in pool:
            if (
                any(clash(p.mod, c.mod) for c in chosen)
                or not _fits_capacity([*chosen, p])
                or not _slots_ok([*chosen, p])
            ):
                continue
            s = _score(gun, [*chosen, p], target, stacks, enemy)[0]
            if s - base > gain + 1e-9:
                best, gain = p, s - base
        if best is None:
            break
        chosen.append(best)
    elemental = _best_per_element(pool)
    improved = True
    while improved:
        improved = False
        cur = _score(gun, chosen, target, stacks, enemy)[0]
        for trial in _neighbours(chosen, pool, elemental):
            if not _slots_ok(trial) or not _fits_capacity(trial) or _clashes(trial):
                continue
            s = _score(gun, trial, target, stacks, enemy)[0]
            if s > cur * (1 + 1e-6):
                chosen, cur, improved = trial, s, True
    return chosen


ELEMENT_KEYS = (
    "heat",
    "cold",
    "electricity",
    "toxin",
    "blast",
    "radiation",
    "gas",
    "magnetic",
    "viral",
    "corrosive",
)


def _best_per_element(pool: list[Pick]) -> list[Pick]:
    """The strongest mod for each element: pairs of these can form a combined element."""
    best: dict[str, Pick] = {}
    for p in pool:
        for k in ELEMENT_KEYS:
            v = p.effect.stats.get(k, 0.0)
            if v and (k not in best or v > best[k].effect.stats.get(k, 0.0)):
                best[k] = p
    return list({id(p): p for p in best.values()}.values())


def _clashes(picks: list[Pick]) -> bool:
    return any(clash(a.mod, b.mod) for i, a in enumerate(picks) for b in picks[i + 1 :])


def _neighbours(chosen: list[Pick], pool: list[Pick], elemental: list[Pick]):
    """Builds one move away: add or swap one mod, or put in two elemental mods at once.

    Two at once matters: a combined element (Corrosive = Toxin + Electricity) only pays off
    when both halves are in, and either half alone can score worse than what it replaces.
    """
    room = len(chosen) < SLOTS + EXILUS_SLOTS
    for p in pool:
        if p in chosen:
            continue
        if room:
            yield [*chosen, p]
        for i in range(len(chosen)):
            yield [*chosen[:i], p, *chosen[i + 1 :]]
    pairs = [
        (a, b)
        for i, a in enumerate(elemental)
        for b in elemental[i + 1 :]
        if a not in chosen and b not in chosen
    ]
    n = len(chosen)
    for a, b in pairs:
        free = SLOTS + EXILUS_SLOTS - n
        if free >= 2:
            yield [*chosen, a, b]
        if free >= 1:
            for i in range(n):
                yield [*chosen[:i], *chosen[i + 1 :], a, b]
        for i in range(n):
            for k in range(i + 1, n):
                rest = [c for x, c in enumerate(chosen) if x not in (i, k)]
                yield [*rest, a, b]


def _why(p: Pick) -> str:
    melee = p.mod.slot == "MELEE"
    labels = {
        "fire_rate": "attack speed" if melee else "fire rate",
        "combo_crit": "crit chance per combo multiplier",
        "combo_status": "status chance per combo multiplier",
        "per_status_damage": "damage per status type on the target",
    }
    bits = []
    for k, v in p.effect.stats.items():
        if k.startswith("bane:"):
            bits.append(f"x{1 + v:.2f} {k.split(':', 1)[1]} damage")
        else:
            bits.append(f"{'+' if v >= 0 else ''}{round(v * 100)}% {labels.get(k, k.replace('_', ' '))}")
    for k, (per, n) in p.effect.stacks.items():
        bits.append(
            f"+{round(per * 100)}% {labels.get(k, k.replace('_', ' '))} per on-kill stack (up to {n})"
        )
    return ", ".join(bits)


def suggest(
    conn: sqlite3.Connection,
    uid: str,
    *,
    target: str | None = None,
    owned: dict[str, int] | None = None,
    stacks: bool = True,
    level: str = "sp",
    stripped: bool = False,
    combo: float = 12.0,
    extra_status: float = 0.0,
    attack: str = "normal",
    arcane: str | None = None,
) -> dict:
    """The suggested build for one gun or melee weapon, ready for the app.

    ``extra_status`` counts status types other sources (abilities, your other weapons, the squad)
    keep on the target, for Condition Overload and the Galvanized mods.

    Melee: ``combo`` is the combo multiplier (1 to 12) that Blood Rush, Weeping Wounds and the
    Gladiator set read; ``attack``: "heavy" judges one heavy attack at that combo instead of
    normal hits.

    ``arcane``: the weapon arcane's name; None picks the best of the ones that can be scored,
    "none" leaves the slot empty.

    ``level``: none (no armor), normal (level 35) or sp (Steel Path, level 135); ``stripped``:
    the enemy's armor is already gone (abilities, squad).
    """
    gun = load_gun(conn, uid)
    gun.extra_status = max(0.0, min(16.0, float(extra_status)))
    if gun.slot == "MELEE":
        gun.combo = max(1.0, min(13.0, float(combo)))
        gun.heavy = attack == "heavy" and gun.heavy_mult > 0
    mods = load_gun_mods(conn)
    target = None if target in (None, "", "none") else target
    enemy = enemy_for(target, level, stripped)
    pool = candidates(gun, mods, owned)
    chosen = search(gun, pool, target, stacks, enemy)
    arcanes = load_weapon_arcanes(conn, gun.slot, gun.holster)
    picked = _pick_arcane(gun, arcanes, arcane, chosen, target, stacks, enemy, owned)
    if picked and gun.arcane:
        chosen = search(gun, pool, target, stacks, enemy)  # the arcane can change the best mods
        if not _arcane_triggers(picked, _score(gun, chosen, target, stacks, enemy)[1]):
            gun.arcane = {}
            chosen = search(gun, pool, target, stacks, enemy)
            picked = None if arcane is None else picked
    score, result, order = _score(gun, chosen, target, stacks, enemy)
    saved, gun.arcane = gun.arcane, {}
    unmodded = _score(gun, [], target, stacks, enemy)[1]
    gun.arcane = saved
    # put elemental mods in the order that gives the best combination, others first
    el_picks = [p for p in chosen if any(k in p.effect.stats for k in _ELEMENT_KEYS)]
    others = [p for p in chosen if p not in el_picks]
    t = add_up(
        [p.effect for p in chosen], stacks=stacks, fire_rate_locked=any(p.mod.locks_fire_rate for p in chosen)
    )
    el_order = _picks_in_element_order(el_picks, t, order)
    ordered = others + el_order
    upgrade = None
    if owned is not None:
        full = candidates(gun, mods, None)
        better = search(gun, full, target, stacks, enemy)
        gain_best = None
        for p in better:
            if p.mod.unique_name in owned:
                continue
            # into a free slot, or in place of one of the mods you have
            options = [chosen] if len(chosen) < SLOTS + EXILUS_SLOTS else []
            options += [chosen[:i] + chosen[i + 1 :] for i in range(len(chosen))]
            for rest in options:
                if (
                    any(clash(p.mod, c.mod) for c in rest)
                    or not _fits_capacity([*rest, p])
                    or not _slots_ok([*rest, p])
                ):
                    continue
                s = _score(gun, [*rest, p], target, stacks, enemy)[0]
                if s > score * 1.001 and (gain_best is None or s > gain_best[1]):
                    gain_best = (p, s)
        if gain_best:
            upgrade = {"name": gain_best[0].mod.name, "gain": f"+{round((gain_best[1] / score - 1) * 100)}%"}
    drain = sum(p.mod.drain(p.rank) for p in chosen)
    utility = [p for p in ordered if p.mod.utility]
    exilus = min(utility, key=lambda p: p.mod.drain(p.rank)) if utility else None
    forma = forma_needed(chosen) or 0
    cap = CAPACITY + (STANCE_CAPACITY if gun.slot == "MELEE" else 0)
    if gun.heavy:
        ranked = "Ranked by the damage of one heavy attack, direct hit plus its status damage over time" + (
            ""
            if enemy.level is None
            else f", to a level {enemy.level} {enemy.unit}"
            + (
                f" ({round(enemy.armor):,} armor{', already stripped' if enemy.stripped else ''})"
                if enemy.armor
                else ""
            )
        )
    elif enemy.level is None:
        ranked = "Ranked by damage per second against a target without armor or shields"
    else:
        pools = [f"{round(enemy.health):,} health"]
        if enemy.shields:
            pools.append(f"{round(enemy.shields):,} shields")
        if enemy.armor:
            pools.append(f"{round(enemy.armor):,} armor" + (", already stripped" if enemy.stripped else ""))
        ranked = (
            f"Ranked by time to kill a level {enemy.level} {enemy.unit} ({', '.join(pools)}): shields first "
            "(Toxin goes straight to health), then health; direct hits plus status damage over time, with "
            "Corrosive and Heat stripping armor, Magnetic raising shield damage and Viral raising health damage"
        )
    notes = [
        ranked + ".",
        "Not counted: shield regeneration and the Magnetic shield-break burst, headshots and weak points, "
        "Rivens, Incarnon forms; Heat is counted per proc, though in long fights its stacks keep growing.",
        f"Mod drain {drain} against {cap} capacity with an Orokin Catalyst"
        + (" and a stance in a matching slot" if gun.slot == "MELEE" else "")
        + (
            f": polarize {forma} slot{'s' if forma != 1 else ''} with Forma to match the costliest mods."
            if forma
            else "."
        ),
    ]
    if gun.slot != "MELEE" and any("per_status_damage" in p.effect.stats for p in chosen):
        notes.append(
            f"{result.status_types:.1f} status types on the target for the damage per status type"
            + (f" ({gun.extra_status:g} from other sources)" if gun.extra_status else "")
            + "."
        )
    if gun.slot == "MELEE":
        notes.append(
            f"Melee is judged at a {gun.combo:g}x combo multiplier (Blood Rush, Weeping Wounds and the Gladiator "
            f"set read it; it doesn't raise normal attack damage)"
            + (
                f", with {result.status_types:.1f} status types on the target for Condition Overload"
                + (f" ({gun.extra_status:g} from other sources)" if gun.extra_status else "")
                if any("per_status_damage" in p.effect.stats for p in chosen)
                else ""
            )
            + (
                f". A heavy attack deals x{gun.heavy_mult:g} this weapon's normal damage, times the combo "
                f"multiplier, and spends the combo; the time to build it again isn't counted. Wind-up "
                f"{result.windup:.2f} s (attack speed doesn't change it)."
                if gun.heavy
                else ". Damage per second uses the weapon's attack speed; real hits per second depend on the "
                "stance, so compare builds of this weapon rather than with guns."
            )
        )
    if picked is not None:
        notes.append(
            f"Arcane: {picked.name}"
            + (
                (" at full stacks." if "tack" in picked.text() or "up to" in picked.text() else ".")
                if gun.arcane
                else " is shown but not counted: its effect depends on things the model doesn't track."
            )
        )
    if stacks and any(p.effect.stacks for p in chosen):
        notes.append("On-kill stacks are counted at their maximum, as in steady fighting.")
    cond = sorted({c for p in chosen for c in p.effect.conditional})
    if cond:
        notes.append("Not counted: " + "; ".join(cond[:4]) + ("…" if len(cond) > 4 else ""))
    return {
        "weapon": gun.name,
        "slot": gun.slot,
        "target": target,
        "mods": [
            {
                "id": p.mod.unique_name,
                "name": p.mod.name,
                "rank": p.rank,
                "max_rank": p.mod.max_rank,
                "drain": p.mod.drain(p.rank),
                "owned": p.owned,
                "exilus": p is exilus,
                "why": _why(p),
            }
            for p in ordered
        ],
        "stats": result.as_dict(),
        "unmodded": unmodded.as_dict(),
        "elements": sorted(((k, v) for k, v in result.by_type.items()), key=lambda kv: -kv[1]),
        "upgrade": upgrade,
        "forma": forma,
        "attack": "heavy" if gun.heavy else "normal",
        "can_heavy": gun.heavy_mult > 0,
        "arcane": (
            {
                "id": picked.unique_name,
                "name": picked.name,
                "text": picked.text(),
                "counted": bool(gun.arcane),
            }
            if picked
            else None
        ),
        "arcane_options": [{"name": a.name, "scored": a.name in WEAPON_SCORED} for a in arcanes],
        "notes": notes,
    }


_ELEMENT_KEYS = (
    "heat",
    "cold",
    "electricity",
    "toxin",
    "blast",
    "radiation",
    "gas",
    "magnetic",
    "viral",
    "corrosive",
)


def _picks_in_element_order(el_picks: list[Pick], t: Totals, order: list[int]) -> list[Pick]:
    """Elemental mods in the slot order the best combination needs."""
    wanted = [t.elements[i][0] for i in order]
    out, left = [], list(el_picks)
    for el in wanted:
        for p in left:
            if el in p.effect.stats:
                out.append(p)
                left.remove(p)
                break
    return out + left


def _arcane_triggers(a, result: Result) -> bool:
    """Status-triggered arcanes (Primary Blight: Toxin) need that element in the build itself."""
    el = STATUS_TRIGGERED.get(a.name)
    return el is None or result.by_type.get(el, 0.0) > 0


def _pick_arcane(gun: Gun, arcanes, wanted: str | None, chosen, target, stacks, enemy, owned=None):
    """Set ``gun.arcane`` and return the arcane: the one named, or the best scored one (of the
    ones you own, when ``owned`` is given)."""
    gun.arcane = {}
    if wanted == "none" or not arcanes:
        return None
    if wanted:
        for a in arcanes:
            if a.name == wanted or a.unique_name == wanted:
                gun.arcane = weapon_effect(a) if a.name in WEAPON_SCORED or weapon_effect(a) else {}
                if a.name in HEAVY_ONLY and not gun.heavy:
                    gun.arcane = {}
                return a
        return None
    base = _score(gun, chosen, target, stacks, enemy)[0]
    best, best_s = None, base * 1.001
    for a in arcanes:
        if a.name not in WEAPON_SCORED or (a.name in HEAVY_ONLY and not gun.heavy):
            continue
        if owned is not None and a.unique_name not in owned:
            continue
        eff = weapon_effect(a)
        if not eff:
            continue
        gun.arcane = eff
        sc, r, _ = _score(gun, chosen, target, stacks, enemy)
        if sc > best_s and _arcane_triggers(a, r):
            best, best_s = a, sc
    gun.arcane = weapon_effect(best) if best else {}
    return best
