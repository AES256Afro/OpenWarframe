"""Flatten a Report into named tables (lists of dicts) for SQLite, CSV and Excel."""

from __future__ import annotations

from dataclasses import dataclass

from ..report.model import MissingItem, Report, SourceRow


@dataclass
class Table:
    name: str
    title: str
    columns: list[str]
    rows: list[dict]
    description: str = ""


def _src(s: SourceRow) -> str:
    vault = ""
    if s.kind == "relic":
        vault = " (farmable)" if s.farmable else " (vaulted)"
    return f"{s.where}{vault}"


def best_sources(m: MissingItem, limit: int = 3) -> str:
    """Short human summary: blueprint sources first, then one line per component."""
    parts: list[str] = []
    if m.blueprint_sources:
        parts.append("Blueprint: " + ", ".join(_src(s) for s in m.blueprint_sources[:limit]))
    for c in m.components:
        if c.sources:
            parts.append(f"{c.name}: " + ", ".join(_src(s) for s in c.sources[:limit]))
    if not parts and m.tradeable:
        parts.append(f"warframe.market: {m.market_slug}")
    return " | ".join(parts)


def summary_rows(r: Report) -> list[dict]:
    h, m = r.headline, r.mastery
    rows = [
        ("Player", r.identity.display_name or "(hidden)"),
        ("Platform", r.identity.platform),
        ("Clan", r.identity.clan or "(hidden)" if r.identity.anonymized else r.identity.clan or ""),
        ("Mastery rank", h.mastery_rank),
        ("Account age (days)", h.account_age_days),
        ("Play time (hours)", h.play_time_hours),
        ("Missions completed", h.missions_completed),
        ("Items mastered", h.items_mastered),
        ("Items leveling (owned, not rank 30)", h.items_leveling),
        ("Items never leveled", h.items_missing),
        ("Masterable items in game", h.items_total),
        ("Star chart nodes done", f"{h.starchart_done} / {h.starchart_total}"),
        ("Steel Path nodes done", f"{h.steel_path_done} / {h.starchart_total}"),
        ("Syndicates at max rank", h.syndicates_maxed),
        ("Achievements tracked", h.achievements_tracked),
        ("Mastery XP visible (items + intrinsics)", m.visible_total),
        ("Mastery XP needed for current rank", m.rank_threshold),
        ("Mastery XP needed for next rank", m.next_rank_threshold),
        ("Snapshot taken", r.snapshot_taken_at.isoformat(timespec="minutes")),
        ("Report generated", r.generated_at.isoformat(timespec="minutes")),
    ]
    return [{"key": k, "value": v} for k, v in rows]


def build_tables(r: Report) -> list[Table]:
    t: list[Table] = []
    t.append(Table("summary", "Summary", ["key", "value"], summary_rows(r), "Headline numbers."))
    t.append(
        Table(
            "categories",
            "Mastery by category",
            ["category", "mastered", "leveling", "missing", "total", "percent_mastered"],
            [c.model_dump() for c in r.categories],
        )
    )
    t.append(
        Table(
            "missing_items",
            "Never leveled",
            [
                "name",
                "category",
                "mastery_req",
                "above_your_mr",
                "acquisition",
                "best_sources",
                "tradeable",
                "market_slug",
                "wiki_url",
                "unique_name",
            ],
            [
                {
                    "name": m.name,
                    "category": m.category,
                    "mastery_req": m.mastery_req,
                    "above_your_mr": m.above_your_mr,
                    "acquisition": m.acquisition,
                    "best_sources": best_sources(m),
                    "tradeable": m.tradeable,
                    "market_slug": m.market_slug,
                    "wiki_url": m.wiki_url,
                    "unique_name": m.unique_name,
                }
                for m in r.missing
            ],
            "Mastery-eligible items with no XP on this account.",
        )
    )
    long_rows = []
    for m in r.missing:
        for s in m.blueprint_sources:
            long_rows.append(
                {"item": m.name, "part": "Blueprint", **s.model_dump(), "item_unique_name": m.unique_name}
            )
        for c in m.components:
            for s in c.sources:
                long_rows.append(
                    {"item": m.name, "part": c.name, **s.model_dump(), "item_unique_name": m.unique_name}
                )
    t.append(
        Table(
            "missing_sources",
            "Where to get them",
            ["item", "part", "kind", "where", "detail", "farmable", "item_unique_name"],
            long_rows,
            "One row per source for each missing item and component.",
        )
    )
    t.append(
        Table(
            "owned_items",
            "Owned and leveled",
            ["name", "category", "rank", "mastered", "xp", "xp_to_30", "mastery_xp", "unique_name"],
            [o.model_dump() for o in r.owned],
        )
    )
    t.append(
        Table(
            "star_chart",
            "Star chart",
            [
                "planet",
                "name",
                "mission_type",
                "faction",
                "level",
                "completed",
                "steel_path",
                "completes",
                "node",
            ],
            [n.model_dump() for n in r.nodes],
        )
    )
    t.append(
        Table(
            "syndicates",
            "Syndicates",
            ["name", "rank", "standing", "tag"],
            [s.model_dump() for s in r.syndicates],
        )
    )
    t.append(
        Table(
            "achievements",
            "Achievements",
            ["name", "progress", "description", "key"],
            [a.model_dump() for a in r.achievements],
        )
    )
    t.append(
        Table("intrinsics", "Intrinsics", ["name", "value", "key"], [i.model_dump() for i in r.intrinsics])
    )
    t.append(
        Table(
            "weapon_usage",
            "Usage",
            ["name", "kills", "headshots", "equip_hours", "xp", "unique_name"],
            [u.model_dump() for u in r.usage],
            "Lifetime stats per item from the profile.",
        )
    )
    t.append(
        Table("sources", "Sources", ["source", "version", "fetched_at"], [s.model_dump() for s in r.sources])
    )
    return t
