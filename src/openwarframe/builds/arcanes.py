"""Warframe arcanes: which ones can be scored, and what they add.

Warframe arcane slots take arcanes named "Arcane ..." or "Molt ..." (weapon arcanes are named
Primary/Secondary/Melee/Shotgun/Exodia/Pax/Residual/Theorem/...). Most Warframe arcanes trigger
on something (being hit, freezing an enemy, going invisible), so they're listed for you to pick.
A few hold steady during a mission and are scored, values parsed from the game's text:

- Molt Augmented: "+0.24% Ability Strength. Stacks up to 250x." on kill -> stacks at maximum
- Arcane Bellicose: "Gain 6% Ability Strength for every 250 Max Health up to 72%."
- Arcane Blessing: "+24 Max Health. Stacks up to 50x." on health pickup -> stacks at maximum
- Arcane Intention: "Gain +250 Max Health per active channeled ability." -> per channeled ability
  you use (up to 4)

Molt Augmented and Arcane Blessing last until death (wiki, 2026-09-12 and 2026-07-01). Bellicose
reads your max health including flat bonuses; the wiki doesn't say so for arcane health in so
many words. Two copies of one arcane can't be equipped.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

SLOTS = 2
WEAPON_PREFIXES = (
    "Primary ",
    "Secondary ",
    "Melee ",
    "Shotgun ",
    "Exodia ",
    "Pax ",
    "Residual ",
    "Theorem ",
    "Magus ",
    "Virtuos ",
    "Akimbo ",
    "Longbow ",
    "Cascadia ",
    "Conjunction ",
    "Emergence ",
    "Eternal ",
    "Fractalized ",
)


@dataclass
class Arcane:
    unique_name: str
    name: str
    max_rank: int
    ranks: list[str]  # effect text per rank, joined

    def text(self, rank: int | None = None) -> str:
        r = self.max_rank if rank is None else max(0, min(rank, self.max_rank))
        t = self.ranks[r] if r < len(self.ranks) else ""
        t = re.sub(r"<[^>]+>", "", t).replace("\r", "")
        return re.sub(r"\n?\+1 Arcane Revive", "", t).strip()

    def scored(self) -> bool:
        return self.name in SCORED


def _num(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text)
    return float(m.group(1).replace(",", "")) if m else None


def _molt(text: str, health: float, channeled: bool) -> dict[str, float]:
    per, n = _num(r"\+([\d.]+)% Ability Strength", text), _num(r"Stacks up to (\d+)x", text)
    return {"strength": per * n / 100} if per and n else {}


def _bellicose(text: str, health: float, channeled: bool) -> dict[str, float]:
    per, step, cap = (
        _num(r"Gain ([\d.]+)% Ability Strength", text),
        _num(r"every ([\d,]+) Max Health", text),
        _num(r"up to ([\d.]+)%", text),
    )
    if not (per and step and cap):
        return {}
    # wiki Arcane_Bellicose (2026-11-16): round(health / 250 x 6)%, capped (reached at 2,980)
    return {"strength": min(cap, round(health / step * per)) / 100}


def _blessing(text: str, health: float, channeled: bool) -> dict[str, float]:
    per, n = _num(r"\+([\d.]+) Max Health", text), _num(r"Stacks up to (\d+)x", text)
    return {"health_flat": per * n} if per and n else {}


def _intention(text: str, health: float, channeled: int) -> dict[str, float]:
    """Per active channeled ability, up to 4 (wiki Arcane_Intention, 2026-09-27): counts the
    channeled abilities you use, taken as all active at once."""
    per = _num(r"\+([\d,]+) Max Health per active channeled", text)
    return {"health_flat": per * min(4, int(channeled))} if per and channeled else {}


# name -> (effect from the text, needs the final health first?)
SCORED = {
    "Molt Augmented": (_molt, False),
    "Arcane Blessing": (_blessing, False),
    "Arcane Intention": (_intention, False),
    "Arcane Bellicose": (_bellicose, True),
}


def effects(picks: list[tuple[Arcane, int]], health_before: float, channeled: bool) -> dict[str, float]:
    """What the scored arcanes add. Flat health first, then health-based Strength (Bellicose)."""
    out: dict[str, float] = {}
    for a, r in picks:
        fn, late = SCORED.get(a.name, (None, False))
        if fn and not late:
            for k, v in fn(a.text(r), 0.0, channeled).items():
                out[k] = out.get(k, 0.0) + v
    health = health_before + out.get("health_flat", 0.0)
    for a, r in picks:
        fn, late = SCORED.get(a.name, (None, False))
        if fn and late:
            for k, v in fn(a.text(r), health, channeled).items():
                out[k] = out.get(k, 0.0) + v
    return out


def load_frame_arcanes(conn: sqlite3.Connection) -> list[Arcane]:
    out, seen = [], set()
    for uid, name, data in conn.execute("SELECT unique_name, name, data FROM item WHERE category = 'Arcane'"):
        if not (name.startswith("Arcane ") or name.startswith("Molt ")) or name.startswith(WEAPON_PREFIXES):
            continue
        d = json.loads(data or "{}")
        ranks = ["\n".join(x.get("stats") or []) for x in d.get("levelStats") or []]
        if not ranks or not ranks[-1].strip() or name in seen:
            continue  # placeholders without text (several "Arcane Steadfast" entries)
        seen.add(name)
        out.append(Arcane(uid, name, len(ranks) - 1, ranks))
    return sorted(out, key=lambda a: (not a.scored(), a.name))


# -- weapon arcanes (wiki Arcane_Enhancement, edited 2026-11-21): one slot per weapon -----------
WEAPON_FAMILIES = {
    "PRIMARY": ("Primary ", "Fractalized "),
    "SECONDARY": ("Secondary ", "Cascadia ", "Conjunction "),
    "MELEE": ("Melee ",),
}
HOLSTER_FAMILIES = {"BOW": ("Longbow ",), "SHOTGUN": ("Shotgun ",)}
# arcanes that need a status from the weapon itself: scored only when the build has that element
STATUS_TRIGGERED = {
    "Primary Blight": "toxin",
    "Primary Frostbite": "cold",
    "Conjunction Voltage": "electricity",
}
# arcanes scored automatically (others are listed for you to pick); "heavy" ones only for heavy attacks
WEAPON_SCORED = {
    "Primary Merciless",
    "Secondary Merciless",
    "Melee Doughty",
    "Melee Animosity",
    "Primary Deadhead",
    "Secondary Deadhead",
    "Primary Crux",
    *STATUS_TRIGGERED,
}
HEAVY_ONLY = {"Melee Animosity"}
HEAD_ONLY = {"Primary Deadhead", "Secondary Deadhead", "Primary Crux"}  # weak point hits or kills


def load_weapon_arcanes(conn: sqlite3.Connection, slot: str, holster: str | None) -> list[Arcane]:
    prefixes = WEAPON_FAMILIES.get(slot, ()) + HOLSTER_FAMILIES.get(holster or "", ())
    out, seen = [], set()
    for uid, name, data in conn.execute("SELECT unique_name, name, data FROM item WHERE category = 'Arcane'"):
        if not name.startswith(prefixes) or name in seen:
            continue
        d = json.loads(data or "{}")
        ranks = ["\n".join(x.get("stats") or []) for x in d.get("levelStats") or []]
        if not ranks or not ranks[-1].strip():
            continue
        seen.add(name)
        out.append(Arcane(uid, name, len(ranks) - 1, ranks))
    return sorted(out, key=lambda a: (a.name not in WEAPON_SCORED, a.name))


def weapon_effect(a: Arcane, rank: int | None = None) -> dict[str, float]:
    """An arcane's numbers for the damage model, at full stacks. Text shapes from the game data:
    "+30% Damage for 4s. Stacks up to 12x." / "+3.6% Critical Damage and +1.8% Multishot for 12s.
    Stacks up to 40x." / Doughty: "1.0x Critical Damage for every 10% Puncture Status chance" /
    Animosity: "42% Critical Chance on your next Heavy Attack, up to 420%" /
    Exposure: "60% Corrosive Damage ... Stacks up to 240%"."""
    from .mods import parse_line

    text = a.text(rank)
    if a.name == "Melee Doughty":
        v = _num(r"([\d.]+)x Critical Damage for every", text)
        return {"doughty": v} if v else {}
    if a.name == "Melee Animosity":
        v = _num(r"up to ([\d.]+)%", text)
        return {"heavy_crit_chance": v / 100} if v else {}
    if a.name == "Melee Exposure":
        v = _num(r"up to ([\d.]+)%", text)
        return {"corrosive": v / 100} if v else {}
    out: dict[str, float] = {}
    for m in re.finditer(r"(?P<body>[^\n]+?) for [\d.]+s\. Stacks up to (?P<n>\d+)x", text):
        n = int(m["n"])
        body = re.sub(r"^On [^:]+:\s*", "", m["body"])  # "On Weak Point Hit: Gain +30% ..."
        for part in body.split(" and "):
            got = parse_line(part.strip().removeprefix("Gain "))
            if got:
                out[got[0]] = out.get(got[0], 0.0) + got[1] * n
    # lines that always apply ("+30% to Headshot Multiplier", Merciless's reload); the game
    # data repeats them, so each counts once
    for line in {x.strip() for x in text.split("\n")}:
        if "Stacks up to" in line or line.endswith(":"):
            continue
        got = parse_line(line)
        if got and got[0] in ("headshot_bonus", "reload"):
            out[got[0]] = out.get(got[0], 0.0) + got[1]
    return out
