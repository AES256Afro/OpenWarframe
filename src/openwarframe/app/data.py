"""Everything the desktop app shows, as one JSON-ready dict.

Built from the profile report (what you have leveled), the codex (what exists and
where it drops) and, when present, an inventory file (what you own right now).
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..codex import Codex
from ..codex.howto import special_label
from ..codex.queries import farmable_relics
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
    if m.owned:
        return "Owned"
    if m.above_your_mr:
        return f"Needs MR {m.mastery_req}"
    ways = set(m.kinds())
    if ways == {"unknown"}:
        return "Event or unavailable"
    if ways and ways <= {"trade", "relic_vaulted"}:
        return "Vaulted: trade only"
    srcs = list(m.blueprint_sources) + [s for c in m.components for s in c.sources]
    synd = [s for s in srcs if s.kind == "syndicate"]
    if synd and all(s.kind in ("syndicate", "vendor") for s in srcs):
        # only syndicates sell it: you need enough standing with one of them. A syndicate you
        # never pledged to is not in the profile at all, which means no standing, not "fine".
        for s in synd:
            rank = _syndicate_rank(s.where, syndicate_ranks)
            if rank is not None and rank >= max(_required_rank(s.detail), 1):
                return "Available"
        return "Needs syndicate standing"
    return "Available"


_RANK_RE = re.compile(r"\brank (-?\d+)")


def _required_rank(detail: str) -> int:
    m = _RANK_RE.search(detail or "")
    return int(m.group(1)) if m else 1


def _norm_syndicate(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower().replace("'s ", " ")).strip()


def _syndicate_rank(where: str, ranks: dict[str, int]) -> int | None:
    """Your rank with the syndicate named in a source ("Kahl's Garrison" is "Garrison")."""
    want = _norm_syndicate(where)
    for name, rank in ranks.items():
        have = _norm_syndicate(name)
        if have and (have == want or have in want or want in have):
            return rank
    return None


def build_app_data(report: Report, codex: Codex, inventory: Inventory | None = None) -> dict:
    conn = codex.conn
    graph = codex.graph
    have_inv = inventory is not None
    syndicate_ranks = {s.name.lower(): s.rank for s in report.syndicates}

    # -- items -----------------------------------------------------------------------
    items: list[dict] = []
    mastered_ids: set[str] = set()
    # the MR an item needs, known for owned items too (the profile only lists it for missing ones)
    mastery_req = dict(conn.execute("SELECT unique_name, mastery_req FROM item"))
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
                "mr": mastery_req.get(o.unique_name) or None,  # 0 or unknown: shown blank
                "how": special_label(o.unique_name, o.name, o.category, graph.recipe_for(o.unique_name)),
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
                "rank": None,  # never leveled: a blank cell, not a 0
                "owned": inventory.owns(m.unique_name) if have_inv else None,
                "mr": m.mastery_req or None,
                "how": special_label(m.unique_name, m.name, m.category, graph.recipe_for(m.unique_name))
                or m.acquisition
                or None,
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
    if have_inv:  # what you neither mastered nor own
        needed_items = {it["id"] for it in items if it["mastery"] != "Mastered"}
    else:  # without an inventory, only what you never leveled (the farm planner agrees)
        needed_items = {m.unique_name for m in report.missing}

    # -- relics ----------------------------------------------------------------------
    farmable = farmable_relics(conn)
    rewards = defaultdict(list)
    for relic, item, rarity, intact, radiant in conn.execute(
        "SELECT relic, item, rarity, chance_intact, chance_radiant FROM relic_reward"
    ):
        rewards[relic].append((item, rarity, intact, radiant))
    # a part is vaulted when no relic that drops it can be farmed right now
    part_relics: dict[str, set[str]] = defaultdict(set)
    for relic, rows_ in rewards.items():
        for item, *_ in rows_:
            part_relics[item].add(relic)
    vaulted_part = {p: not (rs & farmable) for p, rs in part_relics.items()}
    market = dict(
        conn.execute("SELECT unique_name, slug FROM market_item WHERE unique_name LIKE '%/Projections/%'")
    )

    final = graph.final_item

    def held(uid: str) -> int:
        """Copies of a part you hold, counting a part blueprint as the part it makes."""
        if not have_inv:
            return 0
        n = inventory.count(uid)
        made = graph.result.get(uid)
        if made and made != graph.final_item(uid):  # a part blueprint: built parts count too
            n += inventory.count(made)
        return n

    relics: list[dict] = []
    for uid, name, tier in conn.execute("SELECT unique_name, name, tier FROM relic ORDER BY tier, name"):
        counts = inventory.relics.get(uid, {}) if have_inv else {}
        drops = []
        need = 0
        for item, rarity, intact, radiant in rewards.get(uid, []):
            target = final(item)
            for_name = item_names.get(target, target.rsplit("/", 1)[-1])
            needed = target in needed_items and (
                not have_inv or (held(item) < graph.needed_count(item, target) and not inventory.owns(target))
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
    batch = {k: v for k, v in conn.execute("SELECT unique_name, num FROM recipe") if v and v > 1}
    unknown_blueprints = 0  # in the inventory but not in the game data yet (new content)
    if have_inv:
        for rid, n in inventory.recipes.items():
            row = conn.execute(
                "SELECT result_item, build_price, build_time_s FROM recipe WHERE unique_name = ?", (rid,)
            ).fetchone()
            if not row:
                unknown_blueprints += 1
                continue
            result, price, seconds = row
            parts = []
            ready = True
            for ing, cnt in graph.ingredients(rid).items():
                have = inventory.count(ing)
                short = max(0, cnt - have)
                ready = ready and short == 0
                drops = []
                if short:
                    keys = [ing] + graph.blueprints_for(ing)[:1]
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
                    "batch": batch.get(rid) or 1,  # one build makes this many (Cipher: 10)
                    "blueprints": n,
                    "ready": ready,
                    # part and consumable blueprints: mastery is about what they end up building
                    "mastered": (final(result) in mastered_ids)
                    if final(result) in graph.masterable
                    else None,
                    "credits": price,
                    "hours": round((seconds or 0) / 3600, 1),
                    "parts": parts,
                    "missing": sum(1 for p in parts if p["short"]),
                }
            )
        blueprints.sort(key=lambda b: (not b["ready"], b["missing"], b["name"]))

    extra = {"foundry": [], "resources": [], "mods": [], "sell": []}
    if have_inv:
        from .extras import build_foundry, build_mods, build_resources, build_sell

        def best_source(uid: str) -> str | None:
            """The likeliest place to farm a resource: best drop chance first, no PvP."""
            options = [
                s
                for s in codex.sources_for(uid)
                if s.kind != "market" and "conclave" not in f"{s.where} {s.detail}".lower()
            ]
            if not options:
                return None
            best = max(options, key=lambda s: (s.chance is not None, s.chance or 0))
            return f"{best.where}: {best.detail}"

        extra = {
            "foundry": build_foundry(conn, inventory),
            "resources": build_resources(conn, inventory, best_source, graph, mastered_ids),
            "mods": build_mods(conn, inventory),
            "sell": build_sell(conn, inventory, graph, mastered_ids, item_names),
        }
        for row in extra["foundry"]:
            # the row id is the recipe followed by its ready time
            recipe = row["id"].removesuffix(row.get("ready_at") or "")
            row["batch"] = batch.get(recipe) or 1

    farm = build_farm(report, codex, inventory, relics)

    m = report.mastery
    return {
        "meta": {
            "player": report.identity.display_name,
            "platform": report.identity.platform,
            "mr": m.rank,
            "estimate": m.estimated_total,
            "next": m.next_rank_threshold,
            "snapshot": report.snapshot_taken_at.isoformat(),
            "game_data": _game_data_date(conn),
            "unknown_blueprints": unknown_blueprints,
            # Steel Path opens once the whole star chart is done; until then, don't suggest it
            "steel_path_unlocked": bool(
                report.headline.steel_path_done
                or (
                    report.headline.starchart_total
                    and report.headline.starchart_done >= report.headline.starchart_total
                )
            ),
            "inventory": None
            if not have_inv
            else {
                "loaded": inventory.loaded_at.isoformat(),
                "source": inventory.source,
                "credits": inventory.credits,
                "platinum": inventory.platinum,
                "endo": inventory.endo,
                "regal_aya": inventory.regal_aya,
                "ducats": inventory.misc.get("/Lotus/Types/Items/MiscItems/PrimeBucks"),
            },
        },
        "items": items,
        "relics": relics,
        "blueprints": blueprints,
        "farm": farm,
        **extra,
    }


def _game_data_date(conn) -> str | None:
    """When the game data (the official Public Export) was last downloaded."""
    try:
        row = conn.execute("SELECT fetched_at FROM source_version WHERE source = 'public_export'").fetchone()
    except Exception:  # noqa: BLE001 - an old or partial database
        return None
    return row[0] if row else None


def _part_name(conn, uid: str) -> str:
    row = conn.execute(
        "SELECT i.name FROM recipe r JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
        (uid,),
    ).fetchone()
    if row:
        return f"{row[0]} Blueprint"
    tail = uid.rsplit("/", 1)[-1]
    return tail.replace("Blueprint", " Blueprint").replace("Component", "")


def build_farm(report: Report, codex: Codex, inventory: Inventory | None, relics: list[dict]) -> dict:
    from .farm import finish_cards, load_popular, needed_parts, rank_missions, relics_with_needs

    try:
        from ..guide.kb import kb_dir

        kb_root = kb_dir()
    except FileNotFoundError:
        kb_root = None
    conn = codex.conn
    need = needed_parts(conn, report, inventory, set(), codex.graph)
    relic_needs = relics_with_needs(conn, need)
    missions = rank_missions(conn, need, relic_needs, load_popular(kb_root))
    crack = sorted(
        (r for r in relics if (r.get("count") or 0) > 0 and (r["needed"] or r["vaulted_parts"])),
        key=lambda r: (-r["needed"], -r["vaulted_parts"], -(r["count"] or 0)),
    )[:30]
    return {
        "needed_parts": len(need),
        "needed_relics": len(relic_needs),
        "missions": missions,
        "finish": finish_cards(conn, report, inventory, codex.graph),
        "crack": [
            {
                "id": r["id"],
                "name": r["name"],
                "count": r["count"],
                "needed": r["needed"],
                "vaulted_parts": r["vaulted_parts"],
                "vaulted": r["vaulted"],
                # the same detail as on Relics: what it drops and its market name
                "drops": r.get("drops") or [],
                "slug": r.get("slug"),
                "price": r.get("price"),
            }
            for r in crack
        ],
    }
