"""Inventory-only views for the app: sell list, Foundry, resource shortfalls, mods.

Each function takes the codex connection and a parsed Inventory and returns plain rows.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime

from ..inventory import Inventory


def build_foundry(conn, inventory: Inventory, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    rows = []
    for p in inventory.pending:
        recipe = p.get("recipe") or ""
        r = conn.execute(
            "SELECT i.name FROM recipe r LEFT JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
            (recipe,),
        ).fetchone()
        name = r[0] if r and r[0] else recipe.rsplit("/", 1)[-1].replace("Blueprint", "")
        ready_at = datetime.fromisoformat(p["ready_at"]) if p.get("ready_at") else None
        hours = round(max(0.0, (ready_at - now).total_seconds() / 3600), 1) if ready_at else None
        rows.append(
            {
                "id": recipe + (p.get("ready_at") or ""),
                "name": name,
                # compare times, not the rounded hours: 0.0 h can still be a few minutes away
                "ready": ready_at is not None and ready_at <= now,
                "hours_left": hours,
                "ready_at": p.get("ready_at"),
            }
        )
    rows.sort(key=lambda r: (not r["ready"], r["hours_left"] if r["hours_left"] is not None else 1e9))
    return rows


def build_resources(conn, inventory: Inventory, sources_for, graph, mastered: set[str]) -> list[dict]:
    """Resources needed to build what you still need from the blueprints you own.

    One build per blueprint: holding 34 copies of a blueprint does not mean building it 34
    times. Blueprints for things you already mastered or own (and their parts) are left
    out, since there is nothing left to build.
    """
    need: dict[str, int] = defaultdict(int)
    users: dict[str, list[str]] = defaultdict(list)
    for rid in inventory.recipes:
        target = graph.final_item(rid)
        if target in mastered or inventory.owns(target):
            continue
        made = graph.result.get(rid)
        if made and made != target and inventory.count(made) >= graph.needed_count(rid, target):
            continue  # a part blueprint whose parts are already built
        r = conn.execute(
            "SELECT r.result_item, COALESCE(i.name, r.result_item) FROM recipe r "
            "LEFT JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
            (rid,),
        ).fetchone()
        if not r:
            continue
        res_cat = conn.execute("SELECT category FROM item WHERE unique_name = ?", (r[0],)).fetchone()
        if res_cat and res_cat[0] == "Resource" and "/Recipes/" not in r[0]:
            continue  # blueprints that only convert resources (Orokin Cell, alloys...) are optional
        for ing, cnt in graph.ingredients(rid).items():
            if graph.category.get(ing) != "Resource" or "/Recipes/" in ing:
                continue  # parts are tracked on the Blueprints tab
            need[ing] += cnt
            users[ing].append(r[1])
    rows = []
    for uid, total in need.items():
        have = inventory.misc.get(uid, 0)
        name = conn.execute("SELECT name FROM item WHERE unique_name = ?", (uid,)).fetchone()
        best = sources_for(uid)
        rows.append(
            {
                "id": uid,
                "name": name[0] if name else uid.rsplit("/", 1)[-1],
                "need": total,
                "have": have,
                "short": max(0, total - have),
                "blueprints": len(users[uid]),
                "used_by": sorted(set(users[uid]))[:8],
                "farm": best,
            }
        )
    rows.sort(key=lambda r: (-r["short"], r["name"]))
    return rows


def build_mods(conn, inventory: Inventory) -> list[dict]:
    rows = []
    for uid, m in inventory.mods.items():
        r = conn.execute("SELECT name, category, data FROM item WHERE unique_name = ?", (uid,)).fetchone()
        if not r:
            continue
        name, cat, data = r
        info = json.loads(data or "{}")
        ranks = sorted(m["ranks"], reverse=True)
        total = m["unranked"] + len(ranks)
        max_rank = info.get("fusionLimit")
        slug = conn.execute("SELECT slug FROM market_item WHERE unique_name = ?", (uid,)).fetchone()
        rows.append(
            {
                "id": uid,
                "name": name,
                "category": cat,
                "rarity": str(info.get("rarity", "")).title() or None,
                "owned": total,
                "unranked": m["unranked"],
                "ranked": len(ranks),
                "best_rank": ranks[0] if ranks else 0,
                "max_rank": max_rank,
                "maxed": bool(ranks and max_rank is not None and ranks[0] >= max_rank),
                "spare": max(0, total - 1),
                "slug": slug[0] if slug else None,
                "price": None,
            }
        )
    rows.sort(key=lambda r: (-r["spare"], r["name"]))
    return rows


def build_sell(
    conn, inventory: Inventory, graph, mastered: set[str], item_names: dict[str, str]
) -> list[dict]:
    """Prime parts and blueprints you hold, with ducats and how many are spare.

    Keeps as many as the build still needs: two Akstiletto Prime barrels when the recipe
    takes two, minus any already built.
    """
    ducat_items: dict[str, int] = {}
    for uid, ducats in conn.execute("SELECT unique_name, ducats FROM recipe WHERE ducats IS NOT NULL"):
        ducat_items[uid] = ducats
    for uid, data in conn.execute("SELECT unique_name, data FROM item WHERE data LIKE '%primeSellingPrice%'"):
        val = json.loads(data or "{}").get("primeSellingPrice")
        if val:
            ducat_items[uid] = val
    held = {**inventory.misc}
    for k, v in inventory.recipes.items():
        held[k] = held.get(k, 0) + v
    rows = []
    for uid, count in held.items():
        if uid not in ducat_items or count <= 0:
            continue
        target = graph.final_item(uid)
        done = target in mastered or inventory.owns(target)
        made = graph.result.get(uid)
        if done:
            keep, status = 0, "Mastered or built"
        else:
            keep = graph.needed_count(uid, target)
            if made and made != target:  # a part blueprint: parts already built cover the need
                keep = max(0, keep - inventory.count(made))
            status = (
                "Already have the parts"
                if keep == 0
                else "Keep one to build"
                if keep == 1
                else f"Keep {keep} to build"
            )
        spare = max(0, count - keep)
        name = item_names.get(uid)
        if not name:
            r = conn.execute(
                "SELECT i.name FROM recipe r JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
                (uid,),
            ).fetchone()
            name = f"{r[0]} Blueprint" if r else uid.rsplit("/", 1)[-1]
        slug = conn.execute("SELECT slug FROM market_item WHERE unique_name = ?", (uid,)).fetchone()
        rows.append(
            {
                "id": uid,
                "name": name,
                "for": item_names.get(target, target.rsplit("/", 1)[-1]),
                "owned": count,
                "keep": keep,
                "spare": spare,
                "ducats": ducat_items[uid],
                "ducats_total": spare * ducat_items[uid],
                "status": status,
                "slug": slug[0] if slug else None,
                "price": None,
            }
        )
    rows.sort(key=lambda r: (-r["ducats_total"], r["name"]))
    return rows
