"""What to farm: missions ranked by what you need, and per-item "to finish this" cards.

"Need" means parts for items you have not mastered and do not own, plus the parts still
missing from blueprints in your inventory. A relic counts when it drops at least one
needed part; a mission counts when it drops a needed relic or part.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from ..codex.names import mission_label
from ..codex.recipes import RecipeGraph
from ..inventory import Inventory, relic_base
from ..report.model import Report


def load_popular(kb_root: Path | None) -> dict[str, dict]:
    if not kb_root:
        return {}
    path = kb_root / "routes" / "relic_farms.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {f["place"].lower(): f for f in data.get("farms", [])}


def needed_parts(
    conn, report: Report, inventory: Inventory | None, skip_items: set[str], graph: RecipeGraph | None = None
) -> dict[str, str]:
    """Part or blueprint uniqueName -> the item it is for.

    A part stays needed until you hold as many as the recipe takes (two barrels for
    Akstiletto Prime), counting part blueprints and built parts together.
    """
    graph = graph or RecipeGraph(conn)
    names = dict(conn.execute("SELECT unique_name, name FROM item"))
    out: dict[str, str] = {}

    def held(uid: str) -> int:
        return inventory.count(uid) if inventory else 0

    def add(uid: str, for_name: str, need: int = 1) -> None:
        have = held(uid)
        if have >= need:
            return
        out[uid] = for_name
        # warframe parts drop as blueprints: a part counts as needed through its blueprint too
        for bp in graph.blueprints_for(uid):
            if have + held(bp) < need:
                out[bp] = for_name

    for m in report.missing:
        if m.unique_name in skip_items or m.above_your_mr:
            continue
        if inventory and inventory.owns(m.unique_name):
            continue
        for bp in graph.blueprints_for(m.unique_name):
            if held(bp) == 0:
                out[bp] = m.name
        for c in m.components:
            add(c.unique_name, m.name, c.count)
    if inventory:
        for rid in inventory.recipes:
            result = graph.result.get(rid)
            if not result:
                continue
            for_name = names.get(result, result.rsplit("/", 1)[-1])
            for ing, cnt in graph.ingredients(rid).items():
                if "/Recipes/" in ing:
                    add(ing, for_name, cnt)
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
        # the best single chance, not a sum: two rotations at 50% are not "100%"
        g["gives"][what] = max(g["gives"][what], chance or 0)
        if tier:
            g["tiers"].add(tier)

    for node, planet, place, mode, rot, item, chance, is_event in conn.execute(
        "SELECT node, planet, place, game_mode, rotation, item, chance, is_event FROM node_reward WHERE item IS NOT NULL"
    ):
        if is_event:
            continue
        info = nodes.get(node) or (None, None, None, None)
        level = f"{info[2]}-{info[3]}" if info[2] is not None else ""
        bump(
            (place, planet),
            f"{place} ({planet})",
            "Mission",
            mission_label(info[0] or mode),
            level,
            rot,
            item,
            chance,
        )
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


def build_cost(conn, item_uid: str, inventory: Inventory | None, graph: RecipeGraph | None = None) -> dict:
    """Credits and resources to build an item from its blueprint and part blueprints."""
    graph = graph or RecipeGraph(conn)
    credits = 0
    resources: dict[str, int] = {}
    main = graph.recipe_for(item_uid)
    if not main:
        return {"credits": 0, "resources": []}
    queue = [(main, 1)]
    for rid, times in queue:
        credits += graph.build_price.get(rid, 0) * times
        for ing, cnt in graph.ingredients(rid).items():
            if "/Recipes/" in ing:
                held = inventory.count(ing) if inventory else 0
                if held >= cnt:
                    continue  # parts already built
                sub = graph.recipe_for(ing)
                if sub:
                    queue.append((sub, cnt - held))  # each missing part is one build
            else:
                resources[ing] = resources.get(ing, 0) + cnt * times
    rows = []
    for uid, need in resources.items():
        name = conn.execute("SELECT name FROM item WHERE unique_name = ?", (uid,)).fetchone()
        # anything can be an ingredient (Akbronco Prime takes two built Bronco Primes)
        have = inventory.count(uid) if inventory else None
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


OTHER_SOURCE_TABLES = ("node_reward", "enemy_drop", "bounty_reward", "transient_reward", "vendor_offer")


def relic_route(conn, item_uid: str, inventory: Inventory | None) -> dict:
    """How the relics in your inventory relate to one piece.

    ``crack``: relics you own that hold the piece (or its blueprint), best chance first.
    ``relic_only``: the piece comes only from relics, so without one of them you must farm
    a relic first. ``farm_relic``: for that case, a relic that drops somewhere now and the
    best place to get it.
    """
    targets = [item_uid] + [
        r[0] for r in conn.execute("SELECT unique_name FROM recipe WHERE result_item = ?", (item_uid,))
    ]
    q = ",".join("?" * len(targets))
    holders = list(
        conn.execute(
            f"""SELECT rr.relic, rl.name, rr.rarity, rr.chance_intact, rr.chance_radiant
                FROM relic_reward rr JOIN relic rl ON rl.unique_name = rr.relic
                WHERE rr.item IN ({q})""",
            targets,
        )
    )
    other = any(
        conn.execute(f"SELECT 1 FROM {t} WHERE item IN ({q}) LIMIT 1", targets).fetchone()
        for t in OTHER_SOURCE_TABLES
    )
    out: dict = {"relic_only": bool(holders) and not other, "crack": None, "farm_relic": None, "owned": {}}
    if inventory is None or not holders:
        return out
    crack = []
    for rid, name, rarity, intact, radiant in holders:
        have = sum(inventory.relics.get(relic_base(rid), {}).values())
        out["owned"][f"{name} relic"] = have
        if have:
            crack.append(
                {
                    "relic": name,
                    "tier": name.split(" ")[0],
                    "have": have,
                    "rarity": (rarity or "").title(),
                    "intact": intact,
                    "radiant": radiant,
                }
            )
    crack.sort(key=lambda r: (-(r["intact"] or 0), -r["have"]))
    out["crack"] = crack
    if not crack:
        # nothing to crack: point at the relic that is easiest to farm right now
        best = None
        for rid, name, *_ in holders:
            row = conn.execute(
                """SELECT nr.place, nr.planet, nr.rotation, nr.chance, COALESCE(n.mission_type, nr.game_mode)
                   FROM node_reward nr LEFT JOIN node n ON n.id = nr.node
                   WHERE nr.item = ? ORDER BY nr.chance DESC LIMIT 1""",
                (rid,),
            ).fetchone()
            if row and (best is None or (row[3] or 0) > (best["chance"] or 0)):
                place, planet, rotation, chance, mode = row
                best = {
                    "relic": name,
                    "where": f"{place} ({planet})",
                    "mission": mission_label(mode),
                    "rotation": rotation,
                    "chance": chance,
                }
        out["farm_relic"] = best
    return out


def _labels(rows, route: dict, inventory: Inventory | None, limit: int = 4) -> list[str]:
    """Source lines for a piece: relics you own first, then the usual sources.

    The report keeps only a few sources per piece, so relics you own are added from the
    route even when the report's short list left them out.
    """
    owned = route["owned"]
    out: list[str] = []
    seen: set[str] = set()
    for r in (route["crack"] or [])[:limit]:
        where = f"{r['relic']} relic"
        seen.add(where)
        out.append(
            f"{where}: {r['rarity']} - Intact {r['intact']}% -> Radiant {r['radiant']}% · you have {r['have']}"
        )
    for s in rows:
        if s.where in seen:
            continue
        label = f"{s.where}: {s.detail}"
        if s.kind == "relic":
            label += " (farmable)" if s.farmable else " (vaulted)"
            if inventory is not None:
                label += " · you have none" if not owned.get(s.where) else f" · you have {owned[s.where]}"
        out.append(label)
    return out[:limit]


def _route_fields(route: dict) -> dict:
    return {"crack": route["crack"], "relic_only": route["relic_only"], "farm_relic": route["farm_relic"]}


def finish_cards(
    conn, report: Report, inventory: Inventory | None, graph: RecipeGraph | None = None
) -> list[dict]:
    """One card per not-yet-mastered item: each piece, what you hold, and the best sources."""
    graph = graph or RecipeGraph(conn)
    cards = []
    for m in report.missing:
        if m.above_your_mr or not m.components:
            continue
        if inventory and inventory.owns(m.unique_name):
            continue
        pieces = []
        missing = 0
        main = graph.recipe_for(m.unique_name)
        bp = (main,) if main else None
        if bp:
            have = inventory.count(bp[0]) if inventory else None
            short = None if have is None else (0 if have else 1)
            missing += 1 if short else 0
            route = relic_route(conn, bp[0], inventory)
            srcs = _labels(m.blueprint_sources[:4], route, inventory)
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
                    **_route_fields(route),
                }
            )
        for c in m.components:
            have = inventory.count(c.unique_name) if inventory else None
            short = None if have is None else max(0, c.count - have)
            if short:
                missing += 1
            route = relic_route(conn, c.unique_name, inventory)
            pieces.append(
                {
                    "id": c.unique_name,
                    "name": c.name,
                    "need": c.count,
                    "have": have,
                    "short": short,
                    "sources": _labels(c.sources[:4], route, inventory),
                    "slug": _slug(conn, c.unique_name),
                    "price": None,
                    **_route_fields(route),
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
                # every missing piece can come from a relic you own or from a non-relic source
                "doable": None
                if inventory is None
                else all(p["short"] == 0 or p["crack"] or not p["relic_only"] for p in pieces),
                "slug": m.market_slug,
                "cost": build_cost(conn, m.unique_name, inventory, graph),
            }
        )
    cards.sort(key=lambda c: (c["missing"], c["name"]))
    return cards
