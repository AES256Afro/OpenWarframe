"""How to get an item: every known source for it, its blueprint and its parts, in one answer.

The app shows this when a player opens an item's details. Drop tables cover relics,
missions, bounties, enemies and vendors. Some items are in none of them (Lich weapons,
Dojo research, Market blueprints), so a few written rules fill those gaps, worded as
"usually" where the data can't confirm it.
"""

from __future__ import annotations

from ..account.summary import MASTERY_CATEGORIES
from .queries import Codex, Source, farmable_relics
from .recipes import is_component

MAX_SOURCES = 6  # per list; the rest are counted, not shown
MAX_RESOURCE_SOURCES = 2
LABS = {
    "Bio": "Bio Lab",
    "Chemical": "Chem Lab",
    "Energy": "Energy Lab",
    "Tenno": "Tenno Lab",
    "Orokin": "Orokin Lab",
}
KIND_ORDER = {"relic": 0, "node": 1, "bounty": 2, "transient": 3, "enemy": 4, "vendor": 5, "syndicate": 6}


def _source_row(s: Source, farmable: set[str], owned_relics: dict[str, int]) -> dict:
    row = {"kind": s.kind, "where": s.where, "detail": s.detail}
    if s.kind == "relic":
        relic = s.extra.get("relic")
        row["where"] = s.where.removesuffix(" relic")
        row["intact"] = s.extra.get("intact")
        row["radiant"] = s.extra.get("radiant")
        row["rarity"] = (s.rarity or "").title()
        row["vaulted"] = relic not in farmable
        if owned_relics.get(relic):
            row["owned"] = owned_relics[relic]
        row["detail"] = f"{row['rarity']} · {row['intact']}% intact, {row['radiant']}% radiant"
    return row


def _sort_key(row: dict, resource: bool = False) -> tuple:
    kind = KIND_ORDER.get(row["kind"], 9)
    if resource and row["kind"] == "relic":
        kind = 99  # Kuva is "in" Requiem relics, but nobody farms it that way
    return (
        kind,
        row.get("vaulted", False),  # farmable relics first
        -(row.get("owned") or 0),  # then the ones you already have
        -(row.get("radiant") or 0),
    )


def _rows(
    sources: list[Source], farmable: set[str], owned: dict[str, int], limit: int, resource: bool = False
) -> tuple[list, int]:
    rows = sorted(
        (_source_row(s, farmable, owned) for s in sources if s.kind != "market"),
        key=lambda r: _sort_key(r, resource),
    )
    # the same place listed for several rotations or tiers reads as noise: keep the first
    seen: set[tuple] = set()
    unique = []
    for r in rows:
        key = (r["kind"], r["where"].replace(" (Caches)", "").replace(" (Extra)", ""))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique[:limit], max(0, len(unique) - limit)


SPECIAL_LABELS = (
    ("Kuva Lich", "Kuva Lich"),
    ("Sister of Parvos", "Sister of Parvos"),
    ("Tenet melee", "Ergo Glast (Relays)"),
    ("Coda weapon", "Technocyte Coda"),
    ("Clan Dojo", "Clan Dojo research"),
)


def special_label(uid: str, name: str, category: str, recipe: str | None) -> str | None:
    """A short "How to get" for items no drop table records (Lich weapons, Dojo research)."""
    notes = _special_notes(uid, name, category, recipe)
    return next((label for key, label in SPECIAL_LABELS if notes and notes[0].startswith(key)), None)


def _special_notes(uid: str, name: str, category: str, recipe: str | None) -> list[str]:
    """Ways to get an item that no drop table records."""
    path = f"{uid} {recipe or ''}"
    if name.startswith("Kuva ") or "/KuvaLich/" in path or "/KuvaWeapons/" in path:
        return [
            "Kuva Lich weapon. Each Kuva Lich you create carries one Kuva weapon; vanquish or "
            "convert that Lich to get it."
        ]
    if name.startswith("Tenet "):
        note = (
            "Sister of Parvos weapon. Each Sister you create carries one Tenet weapon; vanquish "
            "or convert her to get it."
        )
        if category == "Melee":
            note = "Tenet melee weapon. Ergo Glast in the Relays sells these on a rotation."
        return [note]
    if name.startswith("Coda "):
        return ["Coda weapon. Earned from a Technocyte Coda (the Infested Lich) in Höllvania."]
    if "/ClanTech/" in path:
        lab = next((v for k, v in LABS.items() if f"/ClanTech/{k}/" in path), "research labs")
        return [
            f"Clan Dojo research. Once your clan has researched it in the {lab}, buy the "
            "blueprint there for credits and resources."
        ]
    return []


def how_to_get(codex: Codex, uid: str, owned_relics: dict[str, int] | None = None) -> dict:
    """Everything known about getting ``uid``: direct sources, parts and their sources, notes.

    ``owned_relics`` (relic uniqueName -> count, from the inventory) marks relics the player
    already holds.
    """
    owned = owned_relics or {}
    farmable = farmable_relics(codex.conn)
    item = codex.item(uid) or {}
    name = item.get("name") or codex.display_name(uid)
    category = item.get("category") or ""
    recipe = codex.graph.recipe_for(uid)
    notes = _special_notes(uid, name, category, recipe)
    sources = codex.sources_for(uid)
    market = next((s.extra.get("slug") for s in sources if s.kind == "market"), None)
    direct, direct_more = _rows(sources, farmable, owned, MAX_SOURCES)

    parts = []
    if recipe and not notes:  # a Lich weapon's "recipe" is not something a player builds
        for part, count in codex.graph.ingredients(recipe).items():
            part_sources = codex.sources_for(part)
            # a part you build or a weapon a recipe consumes (Bronco Prime for Akbronco); Kuva or
            # Orokin Cells are resources even though Requiem relics hold Kuva
            component = is_component(part) or (codex.item(part) or {}).get("category") in MASTERY_CATEGORIES
            limit = MAX_SOURCES if component else MAX_RESOURCE_SOURCES
            rows, more = _rows(part_sources, farmable, owned, limit, resource=not component)
            parts.append(
                {
                    "id": part,
                    "name": codex.display_name(part),
                    "count": count,
                    "component": component,
                    "sources": rows,
                    "more": more,
                }
            )
        parts.sort(key=lambda p: not p["component"])  # the parts that matter, then resources

    has_relics = any(r["kind"] == "relic" for r in direct) or any(
        r["kind"] == "relic" for p in parts if p["component"] for r in p["sources"]
    )
    all_relics = [r for r in direct if r["kind"] == "relic"] + [
        r for p in parts if p["component"] for r in p["sources"] if r["kind"] == "relic"
    ]
    if has_relics and all(r.get("vaulted") for r in all_relics):
        notes.append(
            "Every relic that holds this is vaulted: look for it in Prime Resurgence (Varzia, "
            "in Maroo's Bazaar) or trade for it."
        )
    if not notes and recipe and not direct:
        if " Prime" in name:
            notes.append(
                "The main blueprint isn't in any current relic: look for it in Prime Resurgence "
                "(Varzia) or trade for it."
            )
        else:
            notes.append(
                "The main blueprint isn't in any drop table, so it usually comes from the in-game "
                "Market (bought for credits) or a quest reward."
            )
    if not notes and not recipe and not direct:
        notes.append("Not in any drop table: usually the in-game Market, a quest, an event or a bundle.")
    return {
        "id": uid,
        "name": name,
        "notes": notes,
        "sources": direct,
        "more": direct_more,
        "parts": parts,
        "slug": market,
    }
