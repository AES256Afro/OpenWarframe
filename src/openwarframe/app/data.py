"""Everything the desktop app shows, as one JSON-ready dict.

Built from the profile report (what you have leveled), the codex (what exists and
where it drops) and, when present, an inventory file (what you own right now).
"""

from __future__ import annotations

from collections import defaultdict

from ..codex import Codex
from ..inventory import Inventory
from ..report.model import Report

GROUPS = {
    "Warframe": "Warframes",
    "Primary": "Weapons",
    "Secondary": "Weapons",
    "Melee": "Weapons",
    "Archgun": "Weapons",
    "Archmelee": "Weapons",
    "Amp": "Weapons",
    "Companion Weapon": "Weapons",
    "Companion": "Companions & more",
    "Archwing": "Companions & more",
    "Necramech": "Companions & more",
    "K-Drive": "Companions & more",
}


def _access(m, syndicate_ranks: dict[str, int]) -> str:
    """Why a never-leveled item is or isn't reachable right now."""
    if m.above_your_mr:
        return f"Needs MR {m.mastery_req}"
    acq = m.acquisition
    if acq.startswith("Not in drop data"):
        return "Event or unavailable"
    if acq in ("Trade", "Relics (vaulted) + Trade", "Relics (vaulted)"):
        return "Vaulted: trade only"
    srcs = list(m.blueprint_sources) + [s for c in m.components for s in c.sources]
    synd = [s for s in srcs if s.kind in ("syndicate", "vendor")]
    if synd and len(synd) == len(srcs):
        for s in synd:
            rank = syndicate_ranks.get(s.where.lower())
            if rank is not None and rank > 0:
                return "Available"
        if any(s.where.lower() in syndicate_ranks and syndicate_ranks[s.where.lower()] <= 0 for s in synd):
            return "Needs syndicate standing"
    return "Available"


def _final_item(conn, uid: str, depth: int = 0) -> str:
    """Follow recipes upward: part blueprint -> part -> the item it builds."""
    if depth > 4:
        return uid
    row = conn.execute("SELECT result_item FROM recipe WHERE unique_name = ?", (uid,)).fetchone()
    if row:
        uid = row[0]
    up = conn.execute(
        "SELECT r.result_item FROM recipe_ingredient ri JOIN recipe r ON r.unique_name = ri.recipe "
        "WHERE ri.item = ? LIMIT 1",
        (uid,),
    ).fetchone()
    if up and up[0] != uid:
        return _final_item(conn, up[0], depth + 1)
    return uid


def build_app_data(report: Report, codex: Codex, inventory: Inventory | None = None) -> dict:
    conn = codex.conn
    have_inv = inventory is not None
    syndicate_ranks = {s.name.lower(): s.rank for s in report.syndicates}

    # -- items -----------------------------------------------------------------------
    items: list[dict] = []
    mastered_ids: set[str] = set()
    for o in report.owned:
        if o.mastered:
            mastered_ids.add(o.unique_name)
        items.append(
            {
                "id": o.unique_name,
                "name": o.name,
                "category": o.category,
                "group": GROUPS.get(o.category, "Companions & more"),
                "mastery": "Mastered" if o.mastered else "Leveling",
                "rank": o.rank,
                "owned": inventory.owns(o.unique_name) if have_inv else None,
                "mr": None,
                "how": "",
                "access": "Leveled before",
                "slug": None,
            }
        )
    for m in report.missing:
        items.append(
            {
                "id": m.unique_name,
                "name": m.name,
                "category": m.category,
                "group": GROUPS.get(m.category, "Companions & more"),
                "mastery": "Never leveled",
                "rank": 0,
                "owned": inventory.owns(m.unique_name) if have_inv else None,
                "mr": m.mastery_req,
                "how": m.acquisition,
                "access": _access(m, syndicate_ranks),
                "slug": m.market_slug,
                "sources": [f"{s.where}: {s.detail}" for s in m.blueprint_sources][:4]
                + [f"{c.name}: {c.sources[0].where}" for c in m.components if c.sources][:5],
            }
        )
    for it in items:
        if it["owned"] is None:
            it["state"] = it["mastery"]
        elif it["owned"]:
            it["state"] = "Owned, mastered" if it["mastery"] == "Mastered" else "Owned, not mastered"
        else:
            it["state"] = "Mastered, not owned" if it["mastery"] == "Mastered" else "Not owned"

    item_names = dict(conn.execute("SELECT unique_name, name FROM item"))
    needed_items = {it["id"] for it in items if it["mastery"] != "Mastered"}

    # -- relics ----------------------------------------------------------------------
    farmable = {
        r[0]
        for r in conn.execute(
            """SELECT item FROM node_reward WHERE item LIKE '%/Projections/%'
               UNION SELECT item FROM transient_reward WHERE item LIKE '%/Projections/%'
               UNION SELECT item FROM bounty_reward WHERE item LIKE '%/Projections/%'"""
        )
    }
    rewards = defaultdict(list)
    for relic, item, rarity, intact, radiant in conn.execute(
        "SELECT relic, item, rarity, chance_intact, chance_radiant FROM relic_reward"
    ):
        rewards[relic].append((item, rarity, intact, radiant))
    final_cache: dict[str, str] = {}
    # a part is vaulted when no relic that drops it can be farmed right now
    part_relics: dict[str, set[str]] = defaultdict(set)
    for relic, rows_ in rewards.items():
        for item, *_ in rows_:
            part_relics[item].add(relic)
    vaulted_part = {p: not (rs & farmable) for p, rs in part_relics.items()}
    market = dict(
        conn.execute("SELECT unique_name, slug FROM market_item WHERE unique_name LIKE '%/Projections/%'")
    )

    def final(uid: str) -> str:
        if uid not in final_cache:
            final_cache[uid] = _final_item(conn, uid)
        return final_cache[uid]

    owned_parts = (inventory.misc | inventory.recipes) if have_inv else {}
    relics: list[dict] = []
    for uid, name, tier in conn.execute("SELECT unique_name, name, tier FROM relic ORDER BY tier, name"):
        counts = inventory.relics.get(uid, {}) if have_inv else {}
        drops = []
        need = 0
        for item, rarity, intact, radiant in rewards.get(uid, []):
            target = final(item)
            for_name = item_names.get(target, target.rsplit("/", 1)[-1])
            needed = target in needed_items and (
                not have_inv or (owned_parts.get(item, 0) == 0 and not inventory.owns(target))
            )
            need += needed
            vaulted_drop = vaulted_part.get(item, False)
            drops.append(
                {
                    "part": item_names.get(item) or _part_name(conn, item),
                    "for": for_name,
                    "rarity": rarity.title(),
                    "intact": intact,
                    "radiant": radiant,
                    "needed": needed,
                    "vaulted": vaulted_drop,
                }
            )
        total = sum(counts.values())
        relics.append(
            {
                "id": uid,
                "name": name,
                "tier": tier,
                "vaulted": uid not in farmable,
                "count": total if have_inv else None,
                "refinements": counts,
                "needed": need,
                "vaulted_parts": sum(1 for d in drops if d["vaulted"]),
                "slug": market.get(uid) or market.get(uid.removesuffix("Bronze")),
                "price": None,
                "drops": drops,
            }
        )
    if have_inv:
        relics = [r for r in relics if r["count"] or r["needed"] or r["vaulted_parts"]]

    # -- blueprints ------------------------------------------------------------------
    blueprints: list[dict] = []
    if have_inv:
        for rid, n in inventory.recipes.items():
            row = conn.execute(
                "SELECT result_item, build_price, build_time_s FROM recipe WHERE unique_name = ?", (rid,)
            ).fetchone()
            if not row:
                continue
            result, price, seconds = row
            parts = []
            ready = True
            for ing, cnt in conn.execute(
                "SELECT item, count FROM recipe_ingredient WHERE recipe = ?", (rid,)
            ).fetchall():
                have = inventory.count(ing)
                short = max(0, cnt - have)
                ready = ready and short == 0
                drops = []
                if short:
                    bp = conn.execute(
                        "SELECT unique_name FROM recipe WHERE result_item = ?", (ing,)
                    ).fetchone()
                    keys = [ing] + ([bp[0]] if bp else [])
                    for k in keys:
                        for (relic,) in conn.execute("SELECT relic FROM relic_reward WHERE item = ?", (k,)):
                            rname = conn.execute(
                                "SELECT name FROM relic WHERE unique_name = ?", (relic,)
                            ).fetchone()
                            owned_n = sum(inventory.relics.get(relic, {}).values())
                            drops.append(
                                {
                                    "relic": rname[0] if rname else relic,
                                    "owned": owned_n,
                                    "vaulted": relic not in farmable,
                                }
                            )
                parts.append(
                    {
                        "name": item_names.get(ing) or _part_name(conn, ing),
                        "need": cnt,
                        "have": have,
                        "short": short,
                        "relics": drops,
                    }
                )
            blueprints.append(
                {
                    "id": rid,
                    "name": item_names.get(result, result.rsplit("/", 1)[-1]),
                    "blueprints": n,
                    "ready": ready,
                    "mastered": result in mastered_ids,
                    "credits": price,
                    "hours": round((seconds or 0) / 3600, 1),
                    "parts": parts,
                    "missing": sum(1 for p in parts if p["short"]),
                }
            )
        blueprints.sort(key=lambda b: (not b["ready"], b["missing"], b["name"]))

    m = report.mastery
    return {
        "meta": {
            "player": report.identity.display_name,
            "platform": report.identity.platform,
            "mr": m.rank,
            "estimate": m.estimated_total,
            "next": m.next_rank_threshold,
            "snapshot": report.snapshot_taken_at.isoformat(),
            "inventory": None
            if not have_inv
            else {
                "loaded": inventory.loaded_at.isoformat(),
                "source": inventory.source,
                "credits": inventory.credits,
                "platinum": inventory.platinum,
            },
        },
        "items": items,
        "relics": relics,
        "blueprints": blueprints,
    }


def _part_name(conn, uid: str) -> str:
    row = conn.execute(
        "SELECT i.name FROM recipe r JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
        (uid,),
    ).fetchone()
    if row:
        return f"{row[0]} Blueprint"
    tail = uid.rsplit("/", 1)[-1]
    return tail.replace("Blueprint", " Blueprint").replace("Component", "")
