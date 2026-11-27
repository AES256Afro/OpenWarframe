"""Find the mods that give a gun the most sustained damage against a target.

Greedy fill of the 8 slots, then swaps until no single swap helps. Damage is close to a
product of independent factors (base damage, multishot, crit, elements, fire rate), so this
finds the same build as trying every combination on the weapons checked in the tests, in a
fraction of the time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .damage import Result, Totals, add_up, best_order
from .enemy import Enemy, enemy_for
from .mods import GunMod, ModEffect, fits, load_gun_mods
from .weapons import Gun, load_gun

SLOTS = 8
CAPACITY = 60  # with an Orokin Catalyst / Orokin Reactor equivalent
# pairs the game won't equip together beyond "same mod, other variant" (wiki infoboxes)
CONFLICTS = {
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
    r, order = best_order(gun, t, target, enemy)
    return r.total_dps, r, order


def forma_needed(picks: list[Pick]) -> int | None:
    """Slots to polarize (Forma) so the mods fit in 60; None if they can't fit at all.

    A slot whose polarity matches the mod halves its drain (rounded up). Polarize the
    costliest mods first.
    """
    drains = sorted((p.mod.drain(p.rank) for p in picks), reverse=True)
    total = sum(drains)
    n = 0
    for d in drains:
        if total <= CAPACITY:
            return n
        total -= d - (d + 1) // 2
        n += 1
    return n if total <= CAPACITY else None


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
    while len(chosen) < SLOTS:
        base = _score(gun, chosen, target, stacks, enemy)[0] if chosen else 0.0
        best, gain = None, 0.0
        for p in pool:
            if any(clash(p.mod, c.mod) for c in chosen) or not _fits_capacity([*chosen, p]):
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
            if not _fits_capacity(trial) or _clashes(trial):
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
    room = len(chosen) < SLOTS
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
        free = SLOTS - n
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
    bits = []
    for k, v in p.effect.stats.items():
        label = k.split(":", 1)[1] + " damage" if k.startswith("bane:") else k.replace("_", " ")
        bits.append(
            f"{'+' if v >= 0 else ''}{round(v * 100)}% {label}"
            if not k.startswith("bane:")
            else f"x{1 + v:.2f} {label}"
        )
    for k, (per, n) in p.effect.stacks.items():
        bits.append(f"+{round(per * 100)}% {k.replace('_', ' ')} per on-kill stack (up to {n})")
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
) -> dict:
    """The suggested build for one gun, ready for the app.

    ``level``: none (no armor), normal (level 35) or sp (Steel Path, level 135); ``stripped``:
    the enemy's armor is already gone (abilities, squad).
    """
    gun = load_gun(conn, uid)
    mods = load_gun_mods(conn)
    target = None if target in (None, "", "none") else target
    enemy = enemy_for(target, level, stripped)
    pool = candidates(gun, mods, owned)
    chosen = search(gun, pool, target, stacks, enemy)
    score, result, order = _score(gun, chosen, target, stacks, enemy)
    unmodded = _score(gun, [], target, stacks, enemy)[1]
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
            options = [chosen] if len(chosen) < SLOTS else []
            options += [chosen[:i] + chosen[i + 1 :] for i in range(len(chosen))]
            for rest in options:
                if any(clash(p.mod, c.mod) for c in rest) or not _fits_capacity([*rest, p]):
                    continue
                s = _score(gun, [*rest, p], target, stacks, enemy)[0]
                if s > score * 1.001 and (gain_best is None or s > gain_best[1]):
                    gain_best = (p, s)
        if gain_best:
            upgrade = {"name": gain_best[0].mod.name, "gain": f"+{round((gain_best[1] / score - 1) * 100)}%"}
    drain = sum(p.mod.drain(p.rank) for p in chosen)
    forma = forma_needed(chosen) or 0
    who = f"{target} " if target else ""
    if enemy.level is None:
        foe = "a target without armor"
    else:
        foe = f"level {enemy.level} {who}enemies" + (
            f" with {round(enemy.armor):,} armor" + (" (already stripped)" if enemy.stripped else "")
            if enemy.armor
            else " (no armor)"
        )
    notes = [
        f"Ranked by damage per second to health against {foe}: direct hits plus damage over time from "
        "status, with Corrosive and Heat stripping armor and Viral raising health damage.",
        "Not counted: shields, headshots and weak points, Rivens, arcanes, Incarnon forms; Heat is counted "
        "per proc, though in long fights its stacks keep growing.",
        f"Mod drain {drain} against {CAPACITY} capacity with an Orokin Catalyst"
        + (
            f": polarize {forma} slot{'s' if forma != 1 else ''} with Forma to match the costliest mods."
            if forma
            else "."
        ),
    ]
    if target in ("Corpus", "Corpus Amalgam"):
        notes.append(
            "Corpus rely on shields, which aren't modelled yet: Magnetic (more damage to shields) and Toxin "
            "(skips shields) are worth more against them than these numbers show."
        )
    if stacks and any(p.effect.stacks for p in chosen):
        notes.append("On-kill stacks are counted at their maximum, as in steady fighting.")
    cond = sorted({c for p in chosen for c in p.effect.conditional})
    if cond:
        notes.append("Not counted: " + "; ".join(cond[:4]) + ("…" if len(cond) > 4 else ""))
    return {
        "weapon": gun.name,
        "target": target,
        "mods": [
            {
                "id": p.mod.unique_name,
                "name": p.mod.name,
                "rank": p.rank,
                "max_rank": p.mod.max_rank,
                "drain": p.mod.drain(p.rank),
                "owned": p.owned,
                "why": _why(p),
            }
            for p in ordered
        ],
        "stats": result.as_dict(),
        "unmodded": unmodded.as_dict(),
        "elements": sorted(((k, v) for k, v in result.by_type.items()), key=lambda kv: -kv[1]),
        "upgrade": upgrade,
        "forma": forma,
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
