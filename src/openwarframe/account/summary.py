"""Human-readable summary of a snapshot, optionally against the codex."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..codex.queries import Codex
from .model import Snapshot

MASTERY_CATEGORIES = [
    "Warframe",
    "Primary",
    "Secondary",
    "Melee",
    "Companion",
    "Companion Weapon",
    "Archwing",
    "Archgun",
    "Archmelee",
    "Necramech",
    "Amp",
    "K-Drive",
]


@dataclass
class CategoryLine:
    category: str
    mastered: int
    leveling: int  # has XP, not mastered
    total: int | None  # in codex (None without codex)


@dataclass
class Summary:
    mastery_rank: int
    play_time_h: float | None
    missions_completed: int | None
    account_age_days: int | None
    categories: list[CategoryLine] = field(default_factory=list)
    nodes_done: int = 0  # star chart nodes known to the codex
    nodes_total: int | None = None
    nodes_other: int = 0  # hubs, Railjack, Duviri and other mission tags outside the star chart
    steel_path_done: int = 0
    syndicates_max: int = 0
    syndicates_total: int = 0
    challenges_tracked: int = 0
    unmastered_names: list[str] = field(default_factory=list)


def summarize(snapshot: Snapshot, codex: Codex | None = None) -> Summary:
    p = snapshot.progression
    by_cat = snapshot.items_by_category()
    totals: dict[str, int] = {}
    nodes_total = None
    if codex:
        placeholders = ",".join("?" * len(MASTERY_CATEGORIES))
        for row in codex.conn.execute(
            f"SELECT category, COUNT(*) FROM item WHERE category IN ({placeholders}) GROUP BY category",
            MASTERY_CATEGORIES,
        ):
            totals[row[0]] = row[1]
        nodes_total = codex.conn.execute("SELECT COUNT(*) FROM node").fetchone()[0]
    known = [n for n in p.nodes if n.planet != "?"] if codex else list(p.nodes)
    cats = []
    for c in MASTERY_CATEGORIES:
        items = by_cat.get(c, [])
        if not items and c not in totals:
            continue
        m = sum(1 for i in items if i.mastered)
        cats.append(CategoryLine(c, m, len(items) - m, totals.get(c)))
    age = (snapshot.taken_at - snapshot.identity.created_at).days if snapshot.identity.created_at else None
    return Summary(
        mastery_rank=p.mastery_rank,
        play_time_h=(p.play_time_s or 0) / 3600 if p.play_time_s else None,
        missions_completed=p.missions_completed,
        account_age_days=age,
        categories=cats,
        nodes_done=len(known),
        nodes_total=nodes_total,
        nodes_other=len(p.nodes) - len(known),
        steel_path_done=sum(1 for n in known if n.steel_path),
        syndicates_max=sum(1 for a in p.affiliations if a.title >= 5),
        syndicates_total=len(p.affiliations),
        challenges_tracked=len(p.challenges),
        unmastered_names=[f"{i.name} (rank {i.rank})" for i in snapshot.unmastered()[:12]],
    )
