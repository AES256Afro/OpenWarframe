"""What to farm: missions ranked by what you need, and per-item "to finish this" cards.

"Need" means parts for items you have not mastered and do not own, plus the parts still
missing from blueprints in your inventory. A relic counts when it drops at least one
needed part; a mission counts when it drops a needed relic or part.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from ..inventory import Inventory
from ..report.model import Report


def load_popular(kb_root: Path | None) -> dict[str, dict]:
    if not kb_root:
        return {}
    path = kb_root / "routes" / "relic_farms.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {f["place"].lower(): f for f in data.get("farms", [])}


def needed_parts(conn, report: Report, inventory: Inventory | None, skip_items: set[str]) -> dict[str, str]:
    """Part or blueprint uniqueName -> the item it is for."""
    names = dict(conn.execute("SELECT unique_name, name FROM item"))
    out: dict[str, str] = {}

    def held(uid: str) -> int:
        return inventory.count(uid) if inventory else 0

    def add(uid: str, for_name: str) -> None:
        if held(uid) > 0:
            return
        out[uid] = for_name
        # warframe parts drop as blueprints: a part counts as needed through its blueprint too
        for (bp,) in conn.execute("SELECT unique_name FROM recipe WHERE result_item = ?", (uid,)):
            if held(bp) == 0:
                out[bp] = for_name

    for m in report.missing:
        if m.unique_name in skip_items or m.above_your_mr:
            continue
        if inventory and inventory.owns(m.unique_name):
            continue
        for (bp,) in conn.execute("SELECT unique_name FROM recipe WHERE result_item = ?", (m.unique_name,)):
            if held(bp) == 0:
                out[bp] = m.name
        for c in m.components:
            add(c.unique_name, m.name)
    if inventory:
        for rid in inventory.recipes:
            row = conn.execute("SELECT result_item FROM recipe WHERE unique_name = ?", (rid,)).fetchone()
            if not row:
                continue
            for_name = names.get(row[0], row[0].rsplit("/", 1)[-1])
            for ing, cnt in conn.execute(
                "SELECT item, count FROM recipe_ingredient WHERE recipe = ?", (rid,)
            ):
                if "/Recipes/" in ing and inventory.count(ing) < cnt:
                    add(ing, for_name)
    return out


def relics_with_needs(conn, need: dict[str, str]) -> dict[str, list[str]]:
    """Relic uniqueName -> names of the items its needed rewards are for."""
    out: dict[str, list[str]] = defaultdict(list)
    for relic, item in conn.execute("SELECT relic, item FROM relic_reward"):
        if item in need:
            out[relic].append(need[item])
    return out


def rank_missions(
    conn, need: dict[str, str], relic_needs: dict[str, list[str]], popular: dict[str, dict]
) -> list[dict]:
    relic_names = dict(conn.execute("SELECT unique_name, name FROM relic"))
    relic_tier = dict(conn.execute("SELECT unique_name, tier FROM relic"))
    nodes = {
        r[0]: r[1:] for r in conn.execute("SELECT id, mission_type, faction, level_min, level_max FROM node")
    }
    groups: dict[tuple, dict] = {}

    def bump(key, label, kind, mission, level, rotation, item, chance):
        if item in relic_needs:
            weight = len(relic_needs[item])
            what = f"{relic_names.get(item, 'relic')} ({', '.join(sorted(set(relic_needs[item]))[:3])})"
            tier = relic_tier.get(item)
        elif item in need:
            weight, what, tier = 1, f"part for {need[item]}", None
        else:
            return
        g = groups.setdefault(
            key,
            {
                "id": "|".join(str(k) for k in key),
                "place": label,
                "kind": kind,
                "mission": mission or "",
                "level": level or "",
                "score": 0.0,
                "rotations": defaultdict(float),
                "gives": defaultdict(float),
                "tiers": set(),
            },
        )
        value = (chance or 0) / 100 * weight
        g["score"] += value
        g["rotations"][rotation or "-"] += value
        g["gives"][what] += chance or 0
        if tier:
            g["tiers"].add(tier)

    for node, planet, place, mode, rot, item, chance, is_event in conn.execute(
        "SELECT node, planet, place, game_mode, rotation, item, chance, is_event FROM node_reward WHERE item IS NOT NULL"
    ):
        if is_event:
            continue
        info = nodes.get(node) or (None, None, None, None)
        level = f"{info[2]}-{info[3]}" if info[2] is not None else ""
        bump((place, planet), f"{place} ({planet})", "Mission", info[0] or mode, level, rot, item, chance)
    for region, bounty, rot, item, chance in conn.execute(
        "SELECT region, bounty, rotation, item, chance FROM bounty_reward WHERE item IS NOT NULL"
    ):
        bump((bounty, region), f"{bounty} ({region})", "Bounty", "Bounty", "", rot, item, chance)
    for objective, rot, item, chance in conn.execute(
        "SELECT objective, rotation, item, chance FROM transient_reward WHERE item IS NOT NULL"
    ):
        bump((objective, ""), objective, "Special", objective, "", rot, item, chance)

    rows = []
    for g in groups.values():
        place_key = g["place"].split(" (")[0].lower()
        pop = popular.get(place_key)
        is_popular = bool(pop and set(pop.get("tiers", [])) & g["tiers"])
        best_rot = max(g["rotations"].items(), key=lambda kv: kv[1])[0]
        gives = sorted(g["gives"].items(), key=lambda kv: -kv[1])
        rows.append(
            {
                "id": g["id"],
                "place": g["place"],
                "kind": g["kind"],
                "mission": g["mission"],
                "level": g["level"],
                "score": round(g["score"], 3),
                "best_rotation": best_rot,
                "tiers": ", ".join(sorted(g["tiers"])),
                "popular": is_popular,
                "popular_why": pop.get("why") if is_popular else None,
                "gives": [f"{w} · {c:.1f}%" for w, c in gives[:8]],
                "needed_count": len(gives),
            }
        )
    rows.sort(key=lambda r: -r["score"])
    return rows[:300]


def _slug(conn, uid: str) -> str | None:
    row = conn.execute("SELECT slug FROM market_item WHERE unique_name = ?", (uid,)).fetchone()
    if row:
        return row[0]
    bp = conn.execute("SELECT unique_name FROM recipe WHERE result_item = ?", (uid,)).fetchone()
    if bp:
        row = conn.execute("SELECT slug FROM market_item WHERE unique_name = ?", (bp[0],)).fetchone()
        if row:
            return row[0]
    return None


def build_cost(conn, item_uid: str, inventory: Inventory | None) -> dict:
    """Credits and resources to build an item from its blueprint and part blueprints."""
    credits = 0
    resources: dict[str, int] = {}
    main = conn.execute(
        "SELECT unique_name, build_price FROM recipe WHERE result_item = ?", (item_uid,)
    ).fetchone()
    if not main:
        return {"credits": 0, "resources": []}
    queue = [(main[0], main[1] or 0)]
    for rid, price in queue:
        credits += price
        for ing, cnt in conn.execute("SELECT item, count FROM recipe_ingredient WHERE recipe = ?", (rid,)):
            if "/Recipes/" in ing:
                held = inventory.count(ing) if inventory else 0
                if held >= cnt:
                    continue  # part already built
                sub = conn.execute(
                    "SELECT unique_name, build_price FROM recipe WHERE result_item = ?", (ing,)
                ).fetchone()
                if sub:
                    queue.append((sub[0], sub[1] or 0))
            else:
                resources[ing] = resources.get(ing, 0) + cnt
    rows = []
    for uid, need in resources.items():
        name = conn.execute("SELECT name FROM item WHERE unique_name = ?", (uid,)).fetchone()
        have = inventory.misc.get(uid, 0) if inventory else None
        rows.append(
            {
                "name": name[0] if name else uid.rsplit("/", 1)[-1],
                "need": need,
                "have": have,
                "short": None if have is None else max(0, need - have),
            }
        )
    rows.sort(key=lambda r: (-(r["short"] or 0), r["name"]))
    return {"credits": credits, "resources": rows}


def finish_cards(conn, report: Report, inventory: Inventory | None) -> list[dict]:
    """One card per not-yet-mastered item: each piece, what you hold, and the best sources."""
    cards = []
    for m in report.missing:
        if m.above_your_mr or not m.components:
            continue
        if inventory and inventory.owns(m.unique_name):
            continue
        pieces = []
        missing = 0
        bp = conn.execute("SELECT unique_name FROM recipe WHERE result_item = ?", (m.unique_name,)).fetchone()
        if bp:
            have = inventory.count(bp[0]) if inventory else None
            short = None if have is None else (0 if have else 1)
            missing += 1 if short else 0
            srcs = []
            for s in m.blueprint_sources[:4]:
                label = f"{s.where}: {s.detail}"
                if s.kind == "relic":
                    label += " (farmable)" if s.farmable else " (vaulted)"
                srcs.append(label)
            pieces.append(
                {
                    "id": bp[0],
                    "name": f"{m.name} Blueprint",
                    "need": 1,
                    "have": have,
                    "short": short,
                    "sources": srcs or ["Market, Dojo or quest"],
                    "slug": _slug(conn, bp[0]),
                    "price": None,
                }
            )
        for c in m.components:
            have = inventory.count(c.unique_name) if inventory else None
            short = None if have is None else max(0, c.count - have)
            if short:
                missing += 1
            srcs = []
            for s in c.sources[:4]:
                label = f"{s.where}: {s.detail}"
                if s.kind == "relic":
                    label += " (farmable)" if s.farmable else " (vaulted)"
                srcs.append(label)
            pieces.append(
                {
                    "id": c.unique_name,
                    "name": c.name,
                    "need": c.count,
                    "have": have,
                    "short": short,
                    "sources": srcs,
                    "slug": _slug(conn, c.unique_name),
                    "price": None,
                }
            )
        cards.append(
            {
                "id": m.unique_name,
                "name": m.name,
                "category": m.category,
                "access": m.acquisition,
                "pieces": pieces,
                "missing": missing if inventory else len(pieces),
                "total": len(pieces),
                "slug": m.market_slug,
                "cost": build_cost(conn, m.unique_name, inventory),
            }
        )
    cards.sort(key=lambda c: (c["missing"], c["name"]))
    return cards
