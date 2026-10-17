"""Build a Report from a snapshot and the codex."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import quote

from ..account.model import SUIT_CATEGORIES, Snapshot
from ..account.summary import MASTERY_CATEGORIES
from ..codex.queries import Codex
from .model import (
    AchievementRow,
    CategoryRow,
    ComponentRow,
    Headline,
    Identity,
    IntrinsicRow,
    MasteryEstimate,
    MissingItem,
    NodeRow,
    OwnedItem,
    Report,
    SourceRow,
    SourceStamp,
    SyndicateRow,
    UsageRow,
)

INTRINSIC_NAMES = {
    "LPS_TACTICAL": "Railjack: Tactical",
    "LPS_PILOTING": "Railjack: Piloting",
    "LPS_GUNNERY": "Railjack: Gunnery",
    "LPS_ENGINEERING": "Railjack: Engineering",
    "LPS_COMMAND": "Railjack: Command",
    "LPS_DRIFT_RIDING": "Drifter: Riding",
    "LPS_DRIFT_COMBAT": "Drifter: Combat",
    "LPS_DRIFT_OPPORTUNITY": "Drifter: Opportunity",
    "LPS_DRIFT_ENDURANCE": "Drifter: Endurance",
    "LPP_SPACE": "Railjack intrinsic points (unspent pool)",
    "LPP_DRIFTER": "Drifter intrinsic points (unspent pool)",
}
INTRINSIC_MASTERY_PER_RANK = 1500
# Star chart mastery: 241 nodes award mastery, 14,569 in total (about 60 each); Steel
# Path awards the same again. Junctions are 1,000 each, normal and Steel Path.
STARCHART_MASTERY_NODES = 241
STARCHART_MASTERY_TOTAL = 14_569
JUNCTION_MASTERY = 1000
WIKI = "https://wiki.warframe.com/w/"
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def rank_threshold(rank: int) -> int:
    return 2500 * rank * rank


def starchart_mastery(nodes_done: int) -> int:
    """Estimated mastery for ``nodes_done`` completed star chart nodes."""
    done = min(max(nodes_done, 0), STARCHART_MASTERY_NODES)
    return round(done * STARCHART_MASTERY_TOTAL / STARCHART_MASTERY_NODES)


def xp_for_rank(rank: int, suit: bool) -> int:
    return (1000 if suit else 500) * rank * rank


def wiki_url(name: str) -> str:
    return WIKI + quote(name.replace(" ", "_"))


def _pretty(key: str) -> str:
    return _CAMEL.sub(" ", key).replace("_", " ").strip()


_RADIO = re.compile(r"^RadioLegion(Intermission)?(\d*)Syndicate$")


def syndicate_label(name: str, tag: str, ambiguous: bool) -> str:
    """Disambiguate syndicates that share a display name (every Nightwave season is
    called "Nightwave")."""
    m = _RADIO.match(tag)
    if m:
        kind = "Intermission" if m.group(1) else "Series"
        return f"Nightwave {kind} {m.group(2) or 1}"
    if ambiguous:
        return f"{name} ({tag.removesuffix('Syndicate')})"
    return name


def _eligible_items(codex: Codex) -> list[tuple[str, str, str, int, bool]]:
    """(uniqueName, name, category, mastery_req, hidden) for mastery-eligible items.

    Eligible: a masterable category and not flagged ``excludeFromCodex`` (modular
    parts, enemy variants). Hidden items are kept so owned ones still count.
    """
    placeholders = ",".join("?" * len(MASTERY_CATEGORIES))
    out = []
    for uid, name, cat, mr, data in codex.conn.execute(
        f"SELECT unique_name, name, category, mastery_req, data FROM item WHERE category IN ({placeholders})",
        MASTERY_CATEGORIES,
    ):
        hidden = bool(json.loads(data or "{}").get("excludeFromCodex"))
        out.append((uid, name, cat, int(mr or 0), hidden))
    return out


def _farmable_relics(codex: Codex) -> set[str]:
    q = """SELECT item FROM node_reward WHERE item LIKE '%/Projections/%'
           UNION SELECT item FROM transient_reward WHERE item LIKE '%/Projections/%'
           UNION SELECT item FROM bounty_reward WHERE item LIKE '%/Projections/%'"""
    return {r[0] for r in codex.conn.execute(q)}


def _source_rows(codex: Codex, unique_name: str, farmable: set[str], limit: int = 6) -> list[SourceRow]:
    rows: list[SourceRow] = []
    for s in codex.sources_for(unique_name):
        if s.kind == "market":
            continue
        is_farm = None
        if s.kind == "relic":
            is_farm = s.extra.get("relic") in farmable
        rows.append(SourceRow(kind=s.kind, where=s.where, detail=s.detail, farmable=is_farm))
    # farmable relics and non-relic sources first, then vaulted relics
    rows.sort(
        key=lambda r: (r.kind == "relic" and not r.farmable, r.kind != "vendor" and r.kind != "syndicate")
    )
    return rows[:limit]


def _acquisition(bp: list[SourceRow], comps: list[ComponentRow], tradeable: bool, has_recipe: bool) -> str:
    kinds = [s for s in bp] + [s for c in comps for s in c.sources]
    labels: list[str] = []
    if any(s.kind in ("vendor", "syndicate") for s in kinds):
        labels.append("Vendor / standing")
    relics = [s for s in kinds if s.kind == "relic"]
    if relics:
        labels.append("Relics (farmable now)" if any(s.farmable for s in relics) else "Relics (vaulted)")
    if any(s.kind in ("node", "transient") for s in kinds):
        labels.append("Mission drops")
    if any(s.kind == "bounty" for s in kinds):
        labels.append("Bounties")
    if any(s.kind == "enemy" for s in kinds):
        labels.append("Enemy drops")
    if tradeable and (not labels or labels == ["Relics (vaulted)"]):
        labels.append("Trade")
    if not labels:
        labels.append("Market / dojo / quest (no drop data)" if has_recipe else "Not in drop data")
    return " + ".join(labels)


def build_report(snapshot: Snapshot, codex: Codex, *, anonymize: bool = False) -> Report:
    snap = snapshot.anonymized() if anonymize else snapshot
    p = snap.progression
    owned_by_uid = {i.item: i for i in p.items}
    farmable = _farmable_relics(codex)
    notes: list[str] = []

    # -- owned items ---------------------------------------------------------------
    owned = []
    for it in p.items:
        suit = it.category in SUIT_CATEGORIES
        owned.append(
            OwnedItem(
                unique_name=it.item,
                name=it.name,
                category=it.category,
                rank=it.rank,
                xp=it.xp,
                mastery_xp=it.mastery_xp,
                mastered=it.mastered,
                xp_to_30=max(0, xp_for_rank(30, suit) - it.xp),
            )
        )

    # -- missing items (mastery-eligible, never leveled) ----------------------------
    eligible = _eligible_items(codex)
    missing: list[MissingItem] = []
    totals: dict[str, int] = {c: 0 for c in MASTERY_CATEGORIES}
    for uid, name, cat, mr, hidden in eligible:
        if hidden and uid not in owned_by_uid:
            continue
        totals[cat] += 1
        if uid in owned_by_uid:
            continue
        item = codex.item(uid) or {}
        market = item.get("market")
        recipes = codex.recipes_for(uid)
        comps: list[ComponentRow] = []
        if recipes:
            for ing in codex.ingredients(recipes[0]["unique_name"]):
                if not codex.is_component(ing["item"]):
                    continue
                comps.append(
                    ComponentRow(
                        unique_name=ing["item"],
                        name=ing["name"],
                        count=ing["count"],
                        sources=_source_rows(codex, ing["item"], farmable, limit=4),
                    )
                )
        bp = _source_rows(codex, uid, farmable)
        missing.append(
            MissingItem(
                unique_name=uid,
                name=name,
                category=cat,
                mastery_req=mr,
                above_your_mr=mr > p.mastery_rank,
                acquisition=_acquisition(bp, comps, bool(market), bool(recipes)),
                tradeable=bool(market),
                market_slug=market["slug"] if market else None,
                blueprint_sources=bp,
                components=comps,
                wiki_url=wiki_url(name),
            )
        )
    missing.sort(key=lambda m: (MASTERY_CATEGORIES.index(m.category), m.above_your_mr, m.name))

    # -- categories -------------------------------------------------------------------
    categories = []
    by_cat: dict[str, list] = {}
    for it in p.items:
        by_cat.setdefault(it.category, []).append(it)
    for c in MASTERY_CATEGORIES:
        items = by_cat.get(c, [])
        total = max(totals.get(c, 0), len(items))
        if total == 0:
            continue
        m = sum(1 for i in items if i.mastered)
        categories.append(
            CategoryRow(
                category=c,
                mastered=m,
                leveling=len(items) - m,
                missing=total - len(items),
                total=total,
                percent_mastered=round(100 * m / total, 1),
            )
        )

    # -- star chart -------------------------------------------------------------------
    done = {n.node: n for n in p.nodes}
    nodes = []
    for r in codex.conn.execute(
        "SELECT id, name, planet, mission_type, faction, level_min, level_max FROM node ORDER BY system_index, name"
    ):
        n = done.get(r["id"])
        lvl = f"{r['level_min']}-{r['level_max']}" if r["level_min"] is not None else None
        nodes.append(
            NodeRow(
                node=r["id"],
                name=r["name"],
                planet=r["planet"],
                mission_type=r["mission_type"],
                faction=r["faction"],
                level=lvl,
                completes=n.completes if n else 0,
                completed=n is not None,
                steel_path=bool(n and n.steel_path),
            )
        )
    sc_done = sum(1 for n in nodes if n.completed)

    # -- mastery estimate -------------------------------------------------------------
    intrinsic_ranks = sum(v for k, v in p.intrinsics.items() if k.startswith("LPS_"))
    from_intrinsics = intrinsic_ranks * INTRINSIC_MASTERY_PER_RANK
    from_items = sum(i.mastery_xp for i in p.items)
    from_starchart = starchart_mastery(sc_done)
    from_steel_path = starchart_mastery(sum(1 for n in nodes if n.steel_path))
    junctions = [n for n in p.nodes if n.node.endswith("Junction")]
    from_junctions = JUNCTION_MASTERY * (len(junctions) + sum(1 for n in junctions if n.steel_path))
    visible = from_items + from_intrinsics
    mastery = MasteryEstimate(
        rank=p.mastery_rank,
        rank_threshold=rank_threshold(p.mastery_rank),
        next_rank_threshold=rank_threshold(p.mastery_rank + 1),
        from_items=from_items,
        from_intrinsics=from_intrinsics,
        visible_total=visible,
        from_starchart=from_starchart,
        from_steel_path=from_steel_path,
        from_junctions=from_junctions,
        estimated_total=visible + from_starchart + from_steel_path + from_junctions,
        note="Items and intrinsics are computed from the profile. The estimated total adds star chart and "
        f"Steel Path nodes (about {STARCHART_MASTERY_TOTAL // STARCHART_MASTERY_NODES} each, "
        f"{STARCHART_MASTERY_TOTAL:,} for all {STARCHART_MASTERY_NODES}) and junctions "
        f"({JUNCTION_MASTERY:,} each); it is an estimate, not the in-game figure.",
    )

    # -- syndicates, achievements, intrinsics, usage ----------------------------------
    name_counts: dict[str, int] = {}
    for a in p.affiliations:
        name_counts[a.name] = name_counts.get(a.name, 0) + 1
    syndicates = sorted(
        (
            SyndicateRow(
                tag=a.tag,
                name=syndicate_label(a.name, a.tag, name_counts[a.name] > 1),
                rank=a.title,
                standing=a.standing,
            )
            for a in p.affiliations
        ),
        key=lambda s: (-s.rank, -s.standing),
    )
    ch_meta = {
        u.rsplit("/", 1)[-1]: (n, d)
        for u, n, d in codex.conn.execute("SELECT unique_name, name, description FROM challenge")
    }
    achievements = []
    for c in p.challenges:
        name, desc = ch_meta.get(c.name, (_pretty(c.name), None))
        achievements.append(
            AchievementRow(key=c.name, name=name, description=desc or None, progress=c.progress)
        )
    achievements.sort(key=lambda a: a.name.lower())
    intrinsics = [
        IntrinsicRow(key=k, name=INTRINSIC_NAMES.get(k, _pretty(k)), value=v)
        for k, v in sorted(p.intrinsics.items())
    ]
    usage = []
    for w in snap.stats.get("Weapons", []) or []:
        t = w.get("type", "")
        if not t:
            continue
        usage.append(
            UsageRow(
                unique_name=t,
                name=codex.name_of(t),
                kills=int(w.get("kills", 0)),
                headshots=int(w.get("headshots", 0)),
                equip_hours=round(float(w.get("equipTime", 0)) / 3600, 1),
                xp=int(w.get("xp", 0)),
            )
        )
    usage.sort(key=lambda u: -u.kills)

    # -- headline ---------------------------------------------------------------------
    items_total = sum(c.total for c in categories)
    mastered_n = sum(c.mastered for c in categories)
    leveling_n = sum(c.leveling for c in categories)
    ident = snap.identity
    age = (snap.taken_at - ident.created_at).days if ident.created_at else None
    headline = Headline(
        mastery_rank=p.mastery_rank,
        account_age_days=age,
        play_time_hours=round(p.play_time_s / 3600, 1) if p.play_time_s else None,
        missions_completed=p.missions_completed,
        items_mastered=mastered_n,
        items_leveling=leveling_n,
        items_missing=len(missing),
        items_total=items_total,
        starchart_done=sc_done,
        starchart_total=len(nodes),
        steel_path_done=sum(1 for n in nodes if n.steel_path),
        syndicates_maxed=sum(1 for s in syndicates if s.rank >= 5),
        achievements_tracked=len(achievements),
    )
    if "inventory" not in snap.coverage:
        notes.append(
            "Profile-only snapshot: resource counts, owned blueprints, foundry, relics and mods need an inventory "
            "source (milestone 3). 'Missing' means never leveled, which includes items you own but never used."
        )

    stamps = [
        SourceStamp(source=r["source"], version=r["version"], fetched_at=r["fetched_at"])
        for r in codex.versions()
    ]
    stamps.append(
        SourceStamp(source="profile", version=snap.schema_version, fetched_at=snap.taken_at.isoformat())
    )
    return Report(
        generated_at=datetime.now(UTC),
        snapshot_taken_at=snap.taken_at,
        coverage=list(snap.coverage),
        identity=Identity(
            display_name=ident.display_name,
            platform=ident.platform,
            clan=ident.clan,
            created_at=ident.created_at,
            anonymized=anonymize,
        ),
        headline=headline,
        mastery=mastery,
        categories=categories,
        owned=owned,
        missing=missing,
        nodes=nodes,
        syndicates=syndicates,
        achievements=achievements,
        intrinsics=intrinsics,
        usage=usage,
        sources=stamps,
        notes=notes,
    )
