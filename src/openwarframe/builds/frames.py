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

SLOTS = 8  # general slots
EXILUS_SLOTS = 1  # a 9th slot for exilus-capable (utility) mods only
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
    utility: bool = False  # can go in the Exilus slot (isUtility in the game data)
    aura: bool = False
    augment_for: str | None = None  # the ability an augment changes
    text: str = ""  # an augment's effect at its top rank, as the game describes it

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
                if self.aura:  # auras: only the effects on your own frame count here
                    for part in line.replace("\r", "").split("\n"):
                        a = _AURA.match(part.strip())
                        if a and not conditional:
                            k = STATS.get(a["what"].strip())
                            if k:
                                v = float(a["v"]) / 100 * (-1 if a["lose"] else 1)
                                out[k] = out.get(k, 0.0) + v
                    continue
                m = _PCT.match(line)
                if conditional or not m or _CONDITION.search(line):
                    continue
                k = STATS.get(m["what"].strip())
                if k:
                    out[k] = out.get(k, 0.0) + float(m["v"]) / 100
        return out

    def drain(self, rank: int | None = None) -> int:
        """Capacity used; an aura's is negative (it adds capacity): -(|base| + rank)."""
        r = self.max_rank if rank is None else rank
        return -(abs(self.base_drain) + r) if self.aura else self.base_drain + r

    def aura_capacity(self, rank: int | None = None) -> int:
        """Capacity an aura adds in a slot of matching polarity: double its drain (wiki Aura)."""
        return 2 * -self.drain(rank) if self.aura else 0


# "Squad gains +20% Maximum Health", "Squad receives +25% Armor", "You lose 30% Ability Strength"
_AURA = re.compile(
    r"^(?:Squad (?:gains|receives) \+?|(?P<lose>You lose )(?:<LOWER_IS_BETTER>)?)(?P<v>\d+(?:\.\d+)?)% "
    r"(?:Maximum )?(?P<what>.+)$"
)


# variants whose name doesn't contain the base mod's name
VARIANT_OF = {"Umbral Fiber": "Steel Fiber"}


_AUGMENT = re.compile(r"^(?P<ability>.+?)\s*Augment\s*:\s*(?P<text>.*)$", re.S)


# Archon Shards (wiki Archon_Shard, edited 2026-11-21): 5 slots per frame, any stat may repeat;
# Tauforged gives 1.5x. Crimson percentages add to the mods'; Azure values are flat and added
# after all percentage bonuses. Only stats this model scores are offered.
SHARD_SLOTS = 5
SHARD_STATS = {  # (color, stat key, regular value)
    "strength": ("Crimson", "strength", 0.10),
    "duration": ("Crimson", "duration", 0.10),
    "health": ("Azure", "health_flat", 150.0),
    "shields": ("Azure", "shields_flat", 150.0),
    "armor": ("Azure", "armor_flat", 150.0),
}
SHARD_ITEMS = {  # color -> (regular, Tauforged) item uniqueNames (wiki Module:Resources/data)
    "Crimson": (
        "/Lotus/Types/Gameplay/NarmerSorties/ArchonCrystalAmar",
        "/Lotus/Types/Gameplay/NarmerSorties/ArchonCrystalAmarMythic",
    ),
    "Azure": (
        "/Lotus/Types/Gameplay/NarmerSorties/ArchonCrystalBoreal",
        "/Lotus/Types/Gameplay/NarmerSorties/ArchonCrystalBorealMythic",
    ),
}


def shard_effects(picks: list[str], tauforged: bool) -> dict[str, float]:
    out: dict[str, float] = {}
    for stat in picks:
        _, key, v = SHARD_STATS[stat]
        out[key] = out.get(key, 0.0) + v * (1.5 if tauforged else 1.0)
    return out


def best_shards(
    frame: Frame, w: Weights, mods: list, tauforged: bool, limits: dict[str, int] | None = None
) -> list[str]:
    """Every way to fill the shard slots with the scored stats (126 at most); the best one.
    ``limits``: how many shards of each color you have (None: any)."""
    from itertools import combinations_with_replacement

    base = totals(frame, [])["effective_health"]
    best: tuple[float, list[str]] | None = None
    for n in range(SHARD_SLOTS, -1, -1):
        for combo in combinations_with_replacement(sorted(SHARD_STATS), n):
            if limits is not None:
                need: dict[str, int] = {}
                for stat in combo:
                    color = SHARD_STATS[stat][0]
                    need[color] = need.get(color, 0) + 1
                if any(need[c] > limits.get(c, 0) for c in need):
                    continue
            sc = score(frame, w, mods, base, shard_effects(list(combo), tauforged))
            if best is None or sc > best[0] + 1e-12:
                best = (sc, list(combo))
    return best[1] if best else []


def base_frame(name: str) -> str:
    """'Saryn Prime' -> 'Saryn': augments name the base frame."""
    return re.sub(r" (Prime|Umbra)$", "", name)


def load_augments(conn: sqlite3.Connection, frame_name: str) -> list[FrameMod]:
    """The frame's augment mods (compatName = the frame), each tied to the ability its text names."""
    out = []
    rows = conn.execute(
        "SELECT unique_name, name, data FROM item WHERE category = 'Mod' AND json_extract(data, '$.compatName') = ?",
        (base_frame(frame_name),),
    )
    for uid, name, data in rows:
        if any(p in uid for p in SKIP_PATHS):
            continue
        d = json.loads(data or "{}")
        stats = [list(x.get("stats") or []) for x in d.get("levelStats") or []]
        first = " ".join(stats[-1]) if stats else ""
        m = _AUGMENT.match(first)
        if d.get("type") != "WARFRAME" or not m:
            continue
        out.append(
            FrameMod(
                uid,
                name,
                int(d.get("baseDrain") or 0),
                int(d.get("fusionLimit") or 0),
                stats,
                name,
                utility=bool(d.get("isUtility")),
                augment_for=m["ability"].strip(),
                text=re.sub(r"<[^>]+>", "", m["text"]).strip(),
            )
        )
    return sorted(out, key=lambda a: (a.augment_for or "", a.name))


def frame_exclusive_key(name: str) -> str:
    """Primed, Umbral, Archon and Amalgam versions can't be equipped next to their base mod."""
    name = VARIANT_OF.get(name, name)
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
        aura = d.get("type") == "AURA"
        if not d.get("levelStats") or not (
            aura or (d.get("type") == "WARFRAME" and d.get("compatName") in ("WARFRAME", None))
        ):
            continue
        m = FrameMod(
            uid,
            name,
            int(d.get("baseDrain") or 0),
            int(d.get("fusionLimit") or 0),
            [list(x.get("stats") or []) for x in d["levelStats"]],
            frame_exclusive_key(name),
            utility=bool(d.get("isUtility")),
            aura=aura,
        )
        if aura or m.stats():  # every aura adds capacity, even one whose effect we can't count
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


def totals(
    frame: Frame, mods: list[tuple[FrameMod, int]], extra: dict[str, float] | None = None
) -> dict[str, float]:
    """``extra``: Archon Shard effects (percentages added to the mods'; ``*_flat`` added last)."""
    s: dict[str, float] = dict(extra or {})
    for m, rank in mods:
        for k, v in m.stats(rank).items():
            s[k] = s.get(k, 0.0) + v
    strength = 1 + s.get("strength", 0.0)
    duration = 1 + s.get("duration", 0.0)
    rng = 1 + s.get("range", 0.0)
    efficiency = 1 + s.get("efficiency", 0.0)
    health = frame.health * (1 + s.get("health", 0.0)) + s.get("health_flat", 0.0)
    armor = frame.armor * (1 + s.get("armor", 0.0)) + s.get("armor_flat", 0.0)
    shields = frame.shields * (1 + s.get("shields", 0.0)) + s.get("shields_flat", 0.0)
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


def score(
    frame: Frame,
    w: Weights,
    mods: list[tuple[FrameMod, int]],
    base_ehp: float,
    extra: dict[str, float] | None = None,
) -> float:
    t = totals(frame, mods, extra)
    return (
        w.strength * math.log(max(FLOOR, t["strength"]))
        + w.duration * math.log(max(FLOOR, t["duration"]))
        + w.range * math.log(max(FLOOR, t["range"]))
        + w.efficiency * -math.log(t["energy_cost"])
        + w.survivability * math.log(t["effective_health"] / base_ehp)
    )


def forma_needed(mods: list[tuple[FrameMod, int]], capacity: int = CAPACITY) -> int | None:
    """Slots to polarize so the mods fit ``capacity``; None if they can't fit at all."""
    drains = sorted((m.drain(r) for m, r in mods), reverse=True)
    total, n = sum(drains), 0
    for d in drains:
        if total <= capacity:
            return n
        total -= d - (d + 1) // 2
        n += 1
    return n if total <= capacity else None


def _ok(mods: list[tuple[FrameMod, int]], capacity: int = CAPACITY) -> bool:
    """No two variants of one mod; at most 8 general mods plus one exilus-capable mod; fits."""
    keys = [m.exclusive for m, _ in mods]
    general = sum(1 for m, _ in mods if not m.utility)
    return (
        len(keys) == len(set(keys))
        and len(mods) <= SLOTS + EXILUS_SLOTS
        and general <= SLOTS
        and forma_needed(mods, capacity) is not None
    )


def pick_aura(frame: Frame, w: Weights, auras: list[tuple[FrameMod, int]]) -> tuple[FrameMod, int] | None:
    """The aura that helps your own stats most; on a tie, the one that adds the most capacity."""
    if not auras:
        return None
    base = totals(frame, [])["effective_health"]
    return max(
        auras, key=lambda a: (round(score(frame, w, [a], base), 9), a[0].aura_capacity(a[1]), a[0].name)
    )


def search(
    frame: Frame,
    w: Weights,
    pool: list[tuple[FrameMod, int]],
    *,
    fixed: list[tuple[FrameMod, int]] | None = None,
    capacity: int = CAPACITY,
    locked: list[tuple[FrameMod, int]] | None = None,
    extra: dict[str, float] | None = None,
) -> list[tuple[FrameMod, int]]:
    """Mods for the 8 general slots and the Exilus slot. ``fixed`` (the aura) counts toward the
    stats but takes no slot; ``capacity`` includes what the aura adds; ``locked`` mods (augments
    you picked) take slots and are never swapped out."""
    fixed = fixed or []
    locked = list(locked or [])
    base = totals(frame, [])["effective_health"]

    def sc(mods):
        return score(frame, w, [*mods, *fixed], base, extra)

    chosen: list[tuple[FrameMod, int]] = list(locked)
    pool = [p for p in pool if p not in locked]
    while len(chosen) < SLOTS + EXILUS_SLOTS:
        cur = sc(chosen)
        best, gain = None, 1e-9
        for p in pool:
            if p in chosen or not _ok([*chosen, p], capacity):
                continue
            g = sc([*chosen, p]) - cur
            if g > gain:
                best, gain = p, g
        if best is None:
            break
        chosen.append(best)
    cur = sc(chosen)
    while True:
        # one mod in or swapped; when that stops helping, two at once: mods with a cost
        # (Blind Rage, Overextended) often only pay off next to the mod that covers the cost
        best = _best_move(sc, chosen, pool, cur, capacity, pairs=False, locked=locked) or _best_move(
            sc, chosen, pool, cur, capacity, pairs=True, locked=locked
        )
        if best is None:
            return chosen
        chosen, cur = best


def _best_move(sc, chosen, pool, cur, capacity, *, pairs: bool, locked=()):
    out = None
    left = [p for p in pool if p not in chosen]
    room = SLOTS + EXILUS_SLOTS
    if not pairs:
        trials = ([*chosen, p] for p in left if len(chosen) < room)
        swaps = (chosen[:i] + [p] + chosen[i + 1 :] for i in range(len(chosen)) for p in left)
        candidates = [*trials, *swaps]
    else:
        n = len(chosen)
        drops = [
            [c for x, c in enumerate(chosen) if x not in (i, k)] for i in range(n) for k in range(i + 1, n)
        ]
        if n < room:
            drops += [[c for x, c in enumerate(chosen) if x != i] for i in range(n)]
        if n <= room - 2:
            drops.append(list(chosen))
        candidates = ([*rest, a, b] for a_i, a in enumerate(left) for b in left[a_i + 1 :] for rest in drops)
    for trial in candidates:
        if not _ok(trial, capacity) or any(x not in trial for x in locked):
            continue
        s = sc(trial)
        if s > cur + 1e-9 and (out is None or s > out[1]):
            out = (trial, s)
    return out


def exilus_of(chosen: list[tuple[FrameMod, int]]) -> tuple[FrameMod, int] | None:
    """Which chosen mod goes in the Exilus slot: the cheapest exilus-capable one, so the costlier
    mods sit in general slots (an augment that can go there is preferred: it has no other home)."""
    utility = [p for p in chosen if p[0].utility]
    if not utility:
        return None
    return min(utility, key=lambda p: (p[0].augment_for is None, p[0].drain(p[1])))


def suggest_frame(
    conn: sqlite3.Connection,
    uid: str,
    *,
    abilities: list[int] | None = None,
    survivability: str = "some",
    owned: dict[str, int] | None = None,
    augments: list[str] | None = None,
    shards: str = "none",
    owned_shards: dict[str, int] | None = None,
) -> dict:
    """``augments``: uniqueNames of augment mods to put in (they change abilities in ways a number
    can't capture, so you choose them; the rest of the build is fitted around them)."""
    data = kb_abilities()
    frame = load_frame(uid, data)
    mods = load_frame_mods(conn)
    all_augments = load_augments(conn, frame.name)
    wanted = set(augments or [])
    locked = [
        (a, min(owned.get(a.unique_name, a.max_rank), a.max_rank) if owned is not None else a.max_rank)
        for a in all_augments
        if a.unique_name in wanted
    ]
    if owned is not None:
        every = [(m, min(owned[m.unique_name], m.max_rank)) for m in mods if m.unique_name in owned]
    else:
        every = [(m, m.max_rank) for m in mods]
    pool = [p for p in every if not p[0].aura]
    w = weights_for(frame, abilities, survivability)
    aura = pick_aura(frame, w, [p for p in every if p[0].aura])
    fixed = [aura] if aura else []
    capacity = CAPACITY + (aura[0].aura_capacity(aura[1]) if aura else 0)
    chosen = search(frame, w, pool, fixed=fixed, capacity=capacity, locked=locked)
    shard_picks: list[str] = []
    tauforged = shards == "tauforged"
    extra: dict[str, float] = {}
    if shards in ("regular", "tauforged"):
        limits = None
        if owned_shards is not None:
            limits = {
                c: owned_shards.get(items[1 if tauforged else 0], 0) for c, items in SHARD_ITEMS.items()
            }
        # shards and mods depend on each other: alternate twice
        for _ in range(2):
            shard_picks = best_shards(frame, w, [*chosen, *fixed], tauforged, limits)
            extra = shard_effects(shard_picks, tauforged)
            chosen = search(frame, w, pool, fixed=fixed, capacity=capacity, locked=locked, extra=extra)
    t = totals(frame, [*chosen, *fixed], extra)
    base = totals(frame, [])
    upgrade = None
    if owned is not None:
        full = [(m, m.max_rank) for m in mods if not m.aura]
        best = search(frame, w, full, fixed=fixed, capacity=capacity, locked=locked, extra=extra)
        cur = score(frame, w, [*chosen, *fixed], base["effective_health"], extra)
        cand = None
        for p in best:
            if p[0].unique_name in owned:
                continue
            options = [chosen] if len(chosen) < SLOTS + EXILUS_SLOTS else []
            options += [chosen[:i] + chosen[i + 1 :] for i in range(len(chosen)) if chosen[i] not in locked]
            for rest in options:
                trial = [*rest, p]
                if not _ok(trial, capacity):
                    continue
                s = score(frame, w, [*trial, *fixed], base["effective_health"], extra)
                if s > cur + 1e-6 and (cand is None or s > cand[1]):
                    cand = (p[0], s)
        if cand:
            upgrade = {"name": cand[0].name}
    used = [a for a in frame.abilities if not abilities or a["key"] in abilities]
    drain = sum(m.drain(r) for m, r in chosen)
    forma = forma_needed(chosen, capacity) or 0
    exilus = exilus_of(chosen)
    general = [p for p in chosen if p is not exilus]
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
        "mods": [_mod_row(m, r, owned, exilus=False) for m, r in general]
        + ([_mod_row(*exilus, owned, exilus=True)] if exilus else []),
        "aura": None
        if not aura
        else {
            **_mod_row(*aura, owned, exilus=False),
            "capacity": aura[0].aura_capacity(aura[1]),
            "counts": bool(aura[0].stats(aura[1])),
        },
        "capacity": capacity,
        "shards": [
            {
                "color": SHARD_STATS[x][0],
                "stat": x,
                "value": SHARD_STATS[x][2] * (1.5 if tauforged else 1.0),
                "tauforged": tauforged,
            }
            for x in shard_picks
        ],
        "augments": [
            {
                "id": a.unique_name,
                "name": a.name,
                "ability": a.augment_for,
                "text": a.text,
                "exilus_ok": a.utility,
                "owned": None if owned is None else a.unique_name in owned,
                "chosen": a.unique_name in wanted,
            }
            for a in all_augments
        ],
        "stats": t,
        "base": base,
        "upgrade": upgrade,
        "forma": forma,
        "notes": [
            "Balanced by how many of the abilities you use scale with each stat (from the Warframe Wiki's "
            "ability pages, checked 2026-11-27), plus survivability. It doesn't know how much each ability "
            "gains from a stat, only that it uses it; pick the abilities you actually cast.",
            "The Exilus slot takes one exilus-capable mod. The aura adds capacity (double its drain in a "
            "slot of matching polarity); most auras help the squad in ways this doesn't count, so any "
            "max-rank aura with a matching polarity adds the same capacity.",
            "Augments change what an ability does, which no single number captures, so they go in only "
            "when you tick them; the rest of the build is fitted around them.",
            "Not counted: arcanes, set bonuses (Umbral) and conditional effects (on kill, while aiming). "
            "Archon Shards here are Crimson (Strength, Duration) and Azure (Health, Shields, Armor, added "
            "after mods); shards that raise ability damage against enemies with a status, and Amber "
            "shards, aren't scored.",
            f"Mod drain {drain} against {capacity} capacity (Orokin Reactor 60"
            + (f" + {capacity - CAPACITY} from the aura" if capacity > CAPACITY else "")
            + ")"
            + (f": polarize {forma} slot{'s' if forma != 1 else ''} with Forma." if forma else "."),
        ],
        "source": data.get("source"),
        "last_verified": data.get("last_verified"),
    }


def _mod_row(m: FrameMod, r: int, owned: dict[str, int] | None, *, exilus: bool) -> dict:
    why = ", ".join(f"{'+' if v >= 0 else ''}{round(v * 100)}% {k}" for k, v in m.stats(r).items())
    return {
        "id": m.unique_name,
        "name": m.name,
        "rank": r,
        "max_rank": m.max_rank,
        "owned": None if owned is None else m.unique_name in owned,
        "exilus": exilus,
        "augment": m.augment_for,
        "why": f"{m.augment_for} augment (your choice): {m.text}" if m.augment_for else why,
    }
