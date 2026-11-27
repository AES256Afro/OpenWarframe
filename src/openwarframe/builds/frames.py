"""Warframe builds: mods that balance Strength, Duration, Range, Efficiency and survivability.

A frame's abilities don't share one damage formula, so this doesn't calculate kills. It uses
facts instead: which stats each ability scales with (kb/builds/abilities.json, from the
Warframe Wiki's ability pages), the abilities you say you use, and each mod's numbers from the
game data. A stat is worth as much as the number of your abilities that use it.

Score (higher is better), each stat as a multiplier of the frame's base (1.0 = 100%):

    sum over Strength, Duration, Range:  weight x ln(stat)
    Efficiency:                          weight x -ln(energy cost), cost = 2 - efficiency,
                                         efficiency capped at 175% (cost floor 25%)
    survivability:                       weight x ln(effective health / unmodded)

Logarithms make each doubling worth the same, so no single stat is pushed without limit and a
negative mod (Overextended's -60% Strength) costs what it should. Effective health =
health x (armor + 300) / 300 + shields (wiki Armor: Tenno damage reduction = armor / (armor + 300)).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .mods import _CONDITION, SKIP_PATHS, exclusive_key

SLOTS = 8
CAPACITY = 60  # Orokin Reactor at rank 30
EFFICIENCY_CAP = 1.75
FLOOR = 0.1  # keeps ln() finite when a mod drives a stat near zero
STATS = {
    "Ability Strength": "strength",
    "Ability Duration": "duration",
    "Ability Range": "range",
    "Ability Efficiency": "efficiency",
    "Health": "health",
    "Armor": "armor",
    "Shield Capacity": "shields",
    "Energy Max": "energy",
    "Casting Speed": "casting",
}
_PCT = re.compile(r"^(?P<v>[+-]?\d+(?:\.\d+)?)% (?P<what>.+)$")
SURVIVABILITY = {"none": 0.0, "some": 1.0, "tanky": 2.5}


@dataclass
class FrameMod:
    unique_name: str
    name: str
    base_drain: int
    max_rank: int
    ranks: list[list[str]]
    exclusive: str

    def stats(self, rank: int | None = None) -> dict[str, float]:
        r = self.max_rank if rank is None else max(0, min(rank, self.max_rank))
        out: dict[str, float] = {}
        conditional = False
        for raw in self.ranks[r] if r < len(self.ranks) else []:
            for line in str(raw).split("\n"):
                line = line.strip()
                if _CONDITION.search(line) and line.endswith(":"):
                    conditional = True
                    continue
                m = _PCT.match(line)
                if conditional or not m or _CONDITION.search(line):
                    continue
                k = STATS.get(m["what"].strip())
                if k:
                    out[k] = out.get(k, 0.0) + float(m["v"]) / 100
        return out

    def drain(self, rank: int | None = None) -> int:
        return self.base_drain + (self.max_rank if rank is None else rank)


def frame_exclusive_key(name: str) -> str:
    return exclusive_key(name).removeprefix("Umbral ").removeprefix("Archon ")


def load_frame_mods(conn: sqlite3.Connection) -> list[FrameMod]:
    out = []
    for uid, name, data in conn.execute("SELECT unique_name, name, data FROM item WHERE category = 'Mod'"):
        if any(p in uid for p in SKIP_PATHS) or ("/Expert/" in uid and not name.startswith("Primed ")):
            continue
        try:
            d = json.loads(data or "{}")
        except ValueError:
            continue
        if (
            d.get("type") != "WARFRAME"
            or d.get("compatName") not in ("WARFRAME", None)
            or not d.get("levelStats")
        ):
            continue
        m = FrameMod(
            uid,
            name,
            int(d.get("baseDrain") or 0),
            int(d.get("fusionLimit") or 0),
            [list(x.get("stats") or []) for x in d["levelStats"]],
            frame_exclusive_key(name),
        )
        if m.stats():
            out.append(m)
    return out


# -- the ability facts -----------------------------------------------------------------------


def kb_abilities() -> dict:
    from ..guide.kb import kb_dir

    return json.loads((Path(kb_dir()) / "builds" / "abilities.json").read_text(encoding="utf-8"))


@dataclass
class Frame:
    name: str
    unique_name: str
    health: float
    shields: float
    armor: float
    energy: float
    abilities: list[dict] = field(default_factory=list)  # key order


class NotAFrame(ValueError):
    pass


def load_frame(uid: str, data: dict | None = None) -> Frame:
    data = data or kb_abilities()
    by_name = {a["ability"]: a for a in data["abilities"]}
    for f in data["frames"]:
        if f["unique_name"] == uid:
            abilities = [by_name[a] for a in f["abilities"] if a in by_name]
            if not abilities:
                break
            return Frame(
                f["frame"],
                uid,
                f.get("health", 300.0),
                f.get("shield", 300.0),
                f.get("armor", 200.0),
                f.get("energy", 150.0),
                abilities,
            )
    raise NotAFrame("No ability data for this Warframe yet.")


# -- scoring and search --------------------------------------------------------------------------


@dataclass
class Weights:
    strength: float = 0.0
    duration: float = 0.0
    range: float = 0.0
    efficiency: float = 0.0
    survivability: float = 1.0


def weights_for(frame: Frame, chosen: list[int] | None, survivability: str = "some") -> Weights:
    """How much each stat matters: how many of the abilities you use scale with it.

    Efficiency counts every ability that costs energy; a channeled ability counts twice for
    Efficiency and Duration (it drains energy over time, which both reduce).
    """
    w = Weights(survivability=SURVIVABILITY.get(survivability, 1.0))
    for a in frame.abilities:
        if chosen and a["key"] not in chosen:
            continue
        channeled = 1.0 if a.get("channeled") else 0.0
        w.strength += 1.0 if a["strength"] else 0.0
        w.range += 1.0 if a["range"] else 0.0
        w.duration += (1.0 if a["duration"] else 0.0) + channeled
        w.efficiency += (1.0 if (a.get("energy") or channeled) else 0.0) + channeled
    return w


def totals(frame: Frame, mods: list[tuple[FrameMod, int]]) -> dict[str, float]:
    s: dict[str, float] = {}
    for m, rank in mods:
        for k, v in m.stats(rank).items():
            s[k] = s.get(k, 0.0) + v
    strength = 1 + s.get("strength", 0.0)
    duration = 1 + s.get("duration", 0.0)
    rng = 1 + s.get("range", 0.0)
    efficiency = 1 + s.get("efficiency", 0.0)
    health = frame.health * (1 + s.get("health", 0.0))
    armor = frame.armor * (1 + s.get("armor", 0.0))
    shields = frame.shields * (1 + s.get("shields", 0.0))
    ehp = health * (armor + 300) / 300 + shields
    return {
        "strength": strength,
        "duration": duration,
        "range": rng,
        "efficiency": efficiency,
        "energy_cost": max(0.25, 2 - min(efficiency, EFFICIENCY_CAP)),
        "health": health,
        "armor": armor,
        "shields": shields,
        "energy": frame.energy * (1 + s.get("energy", 0.0)),
        "effective_health": ehp,
        "damage_reduction": armor / (armor + 300),
    }


def score(frame: Frame, w: Weights, mods: list[tuple[FrameMod, int]], base_ehp: float) -> float:
    t = totals(frame, mods)
    return (
        w.strength * math.log(max(FLOOR, t["strength"]))
        + w.duration * math.log(max(FLOOR, t["duration"]))
        + w.range * math.log(max(FLOOR, t["range"]))
        + w.efficiency * -math.log(t["energy_cost"])
        + w.survivability * math.log(t["effective_health"] / base_ehp)
    )


def forma_needed(mods: list[tuple[FrameMod, int]]) -> int | None:
    drains = sorted((m.drain(r) for m, r in mods), reverse=True)
    total, n = sum(drains), 0
    for d in drains:
        if total <= CAPACITY:
            return n
        total -= d - (d + 1) // 2
        n += 1
    return n if total <= CAPACITY else None


def _ok(mods: list[tuple[FrameMod, int]]) -> bool:
    keys = [m.exclusive for m, _ in mods]
    return len(keys) == len(set(keys)) and forma_needed(mods) is not None


def search(frame: Frame, w: Weights, pool: list[tuple[FrameMod, int]]) -> list[tuple[FrameMod, int]]:
    base = totals(frame, [])["effective_health"]
    chosen: list[tuple[FrameMod, int]] = []
    while len(chosen) < SLOTS:
        cur = score(frame, w, chosen, base)
        best, gain = None, 1e-9
        for p in pool:
            if p in chosen or not _ok([*chosen, p]):
                continue
            g = score(frame, w, [*chosen, p], base) - cur
            if g > gain:
                best, gain = p, g
        if best is None:
            break
        chosen.append(best)
    cur = score(frame, w, chosen, base)
    while True:
        # one mod in or swapped; when that stops helping, two at once: mods with a cost
        # (Blind Rage, Overextended) often only pay off next to the mod that covers the cost
        best = _best_move(frame, w, chosen, pool, base, cur, pairs=False) or _best_move(
            frame, w, chosen, pool, base, cur, pairs=True
        )
        if best is None:
            return chosen
        chosen, cur = best


def _best_move(frame, w, chosen, pool, base, cur, *, pairs: bool):
    out = None
    left = [p for p in pool if p not in chosen]
    if not pairs:
        trials = ([*chosen, p] for p in left if len(chosen) < SLOTS)
        swaps = (chosen[:i] + [p] + chosen[i + 1 :] for i in range(len(chosen)) for p in left)
        candidates = [*trials, *swaps]
    else:
        n = len(chosen)
        drops = [
            [c for x, c in enumerate(chosen) if x not in (i, k)] for i in range(n) for k in range(i + 1, n)
        ]
        if n < SLOTS:
            drops += [[c for x, c in enumerate(chosen) if x != i] for i in range(n)]
        if n <= SLOTS - 2:
            drops.append(list(chosen))
        candidates = ([*rest, a, b] for a_i, a in enumerate(left) for b in left[a_i + 1 :] for rest in drops)
    for trial in candidates:
        if not _ok(trial):
            continue
        s = score(frame, w, trial, base)
        if s > cur + 1e-9 and (out is None or s > out[1]):
            out = (trial, s)
    return out


def suggest_frame(
    conn: sqlite3.Connection,
    uid: str,
    *,
    abilities: list[int] | None = None,
    survivability: str = "some",
    owned: dict[str, int] | None = None,
) -> dict:
    data = kb_abilities()
    frame = load_frame(uid, data)
    mods = load_frame_mods(conn)
    if owned is not None:
        pool = [(m, min(owned[m.unique_name], m.max_rank)) for m in mods if m.unique_name in owned]
    else:
        pool = [(m, m.max_rank) for m in mods]
    w = weights_for(frame, abilities, survivability)
    chosen = search(frame, w, pool)
    t = totals(frame, chosen)
    base = totals(frame, [])
    upgrade = None
    if owned is not None:
        full = [(m, m.max_rank) for m in mods]
        best = search(frame, w, full)
        cur = score(frame, w, chosen, base["effective_health"])
        cand = None
        for p in best:
            if p[0].unique_name in owned:
                continue
            options = [chosen] if len(chosen) < SLOTS else []
            options += [chosen[:i] + chosen[i + 1 :] for i in range(len(chosen))]
            for rest in options:
                trial = [*rest, p]
                if not _ok(trial):
                    continue
                s = score(frame, w, trial, base["effective_health"])
                if s > cur + 1e-6 and (cand is None or s > cand[1]):
                    cand = (p[0], s)
        if cand:
            upgrade = {"name": cand[0].name}
    used = [a for a in frame.abilities if not abilities or a["key"] in abilities]
    drain = sum(m.drain(r) for m, r in chosen)
    forma = forma_needed(chosen) or 0
    return {
        "frame": frame.name,
        "abilities": [
            {
                "key": a["key"],
                "name": a["ability"],
                "strength": a["strength"],
                "duration": a["duration"],
                "range": a["range"],
                "channeled": a.get("channeled", False),
                "energy": a.get("energy", 0),
                "used": a in used,
            }
            for a in frame.abilities
        ],
        "weights": w.__dict__,
        "mods": [
            {
                "id": m.unique_name,
                "name": m.name,
                "rank": r,
                "max_rank": m.max_rank,
                "owned": None if owned is None else True,
                "why": ", ".join(
                    f"{'+' if v >= 0 else ''}{round(v * 100)}% {k}" for k, v in m.stats(r).items()
                ),
            }
            for m, r in chosen
        ],
        "stats": t,
        "base": base,
        "upgrade": upgrade,
        "forma": forma,
        "notes": [
            "Balanced by how many of the abilities you use scale with each stat (from the Warframe Wiki's "
            "ability pages, checked 2026-11-27), plus survivability. It doesn't know how much each ability "
            "gains from a stat, only that it uses it; pick the abilities you actually cast.",
            "Not filled: the Aura and Exilus slots, augment mods, Archon Shards, arcanes and set bonuses "
            "(Umbral); conditional effects (on kill, while aiming) aren't counted.",
            f"Mod drain {drain} against {CAPACITY} capacity with an Orokin Reactor"
            + (f": polarize {forma} slot{'s' if forma != 1 else ''} with Forma." if forma else "."),
        ],
        "source": data.get("source"),
        "last_verified": data.get("last_verified"),
    }
