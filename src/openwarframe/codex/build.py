"""Build the codex database from the static sources.

``build_codex`` is a pure function of its payloads so tests can feed small fixtures;
``update_codex`` fetches the real payloads and swaps the database atomically.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..config import Settings
from ..http import CachedClient
from ..sources.static.market import MarketItem, fetch_market_items
from ..sources.static.pe_plus import PlusExport, fetch_plus
from ..sources.static.public_export import IMAGE_BASE, PublicExport, fetch_public_export
from ..sources.static.wfcd_drops import DropData, fetch_drops
from .names import CURRENCY_ITEMS, NameResolver, normalize, strip_decorations, strip_store_prefix
from .schema import SCHEMA, SCHEMA_VERSION

log = logging.getLogger(__name__)

# Relic reward chances by rarity and refinement (percent).
RELIC_CHANCES = {
    "COMMON": (25.33, 23.33, 20.0, 16.67),
    "UNCOMMON": (11.0, 13.0, 17.0, 20.0),
    "RARE": (2.0, 4.0, 6.0, 10.0),
}

FACTIONS = {
    0: "Grineer",
    1: "Corpus",
    2: "Infested",
    3: "Orokin",
    4: "Sentient",
    5: "Stalker",
    6: "Murmur",
    7: "Scaldra",
    8: "Techrot",
}

# manifest -> (category label, record key)
PE_ITEM_MANIFESTS: dict[str, list[tuple[str, str]]] = {
    "ExportWarframes": [("Warframe", "ExportWarframes")],
    "ExportWeapons": [("Weapon", "ExportWeapons"), ("Railjack Weapon", "ExportRailjackWeapons")],
    "ExportSentinels": [("Companion", "ExportSentinels")],
    "ExportResources": [("Resource", "ExportResources")],
    "ExportUpgrades": [
        ("Mod", "ExportUpgrades"),
        ("Railjack Mod", "ExportAvionics"),
        ("Focus", "ExportFocusUpgrades"),
    ],
    "ExportKeys": [("Quest", "ExportKeys")],
    "ExportGear": [("Gear", "ExportGear")],
    "ExportDrones": [("Extractor", "ExportDrones")],
    "ExportCustoms": [("Cosmetic", "ExportCustoms")],
    "ExportFlavour": [("Flavour", "ExportFlavour")],
    "ExportFusionBundles": [("Endo Bundle", "ExportFusionBundles")],
}

WEAPON_SLOTS = {
    "LongGuns": "Primary",
    "Pistols": "Secondary",
    "Melee": "Melee",
    "SpaceGuns": "Archgun",
    "SpaceMelee": "Archmelee",
    "SentinelWeapons": "Companion Weapon",
    "OperatorAmps": "Amp",
    "SpecialItems": "Special",
}
SUIT_TYPES = {"Suits": "Warframe", "SpaceSuits": "Archwing", "MechSuits": "Necramech"}


@dataclass
class CodexPayloads:
    public_export: PublicExport
    plus: PlusExport
    drops: DropData
    market: list[MarketItem] = field(default_factory=list)


@dataclass
class BuildReport:
    counts: dict[str, int] = field(default_factory=dict)
    unresolved: dict[str, tuple[int, str]] = field(default_factory=dict)
    seconds: float = 0.0


# --------------------------------------------------------------------------------------
# helpers


_MODULAR_MARKERS = (
    "/ModularMelee",
    "/SUModular",
    "/InfKitGun/",
    "/OperatorAmplifiers/",
    "/HoverboardParts/",
    "PetParts/",
)


def modular_category(unique_name: str) -> str | None:
    """Classify modular parts. Returns a mastery category for the one part per assembly
    that earns mastery (Zaw strike, Kitgun chamber, Amp prism, K-Drive deck, MOA/Hound
    model), "Modular Part" for every other part, or None if not modular."""
    u = unique_name
    if not any(m in u for m in _MODULAR_MARKERS):
        return None
    if "PvPVariant" in u:
        return "Modular Part"
    if "/ModularMelee" in u and ("/Tip/" in u or "/Tips/" in u):
        return "Melee"
    if ("/SUModularSecondary" in u and "/Barrel/" in u) or ("/InfKitGun/Barrels/" in u):
        return "Secondary"
    if "/OperatorAmplifiers/" in u and "Barrel" in u.rsplit("/", 2)[-2] + u.rsplit("/", 1)[-1]:
        return "Amp"
    if "/HoverboardParts/" in u and u.endswith("Deck"):
        return "K-Drive"
    if "/MoaPetParts/MoaPetHead" in u or "/ZanukaPetParts/ZanukaPetPartHead" in u:
        return "Companion"
    return "Modular Part"


def _category_for(manifest_label: str, rec: dict) -> str:
    pc = rec.get("productCategory")
    if manifest_label in ("Weapon", "Companion"):
        modular = modular_category(rec.get("uniqueName", ""))
        if modular:
            return modular
    if manifest_label == "Warframe":
        if str(rec.get("name", "")).startswith("<ARCHWING>"):
            return "Archwing"
        return SUIT_TYPES.get(pc, "Warframe")
    if manifest_label == "Weapon":
        return WEAPON_SLOTS.get(pc, "Weapon")
    if manifest_label == "Resource" and "/Projections/" in rec.get("uniqueName", ""):
        return "Relic"
    return manifest_label


def _relic_short_name(name: str) -> tuple[str, str] | None:
    """'Lith R2 Relic' -> ('Lith R2', 'Lith'); returns None for non-relics."""
    parts = name.replace(" Relic", "").split()
    if len(parts) >= 2 and parts[0] in ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia"):
        return " ".join(parts[:2]), parts[0]
    if name.startswith("Requiem") or name.startswith("Omnia"):
        return name.replace(" Relic", ""), parts[0]
    return None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------------------
# loaders (each takes the connection, the payload and the resolver)


def load_items(conn: sqlite3.Connection, pe: PublicExport, resolver: NameResolver) -> int:
    images = {m["uniqueName"]: m.get("textureLocation") for m in pe.get("ExportManifest").get("Manifest", [])}
    rows = []
    for manifest, groups in PE_ITEM_MANIFESTS.items():
        data = pe.get(manifest)
        for label, key in groups:
            for rec in data.get(key, []):
                uid = rec.get("uniqueName")
                name = rec.get("name")
                if not uid or not name:
                    continue
                clean_name = strip_decorations(name)
                cat = _category_for(label, rec)
                img = images.get(uid)
                rows.append(
                    (
                        uid,
                        clean_name,
                        cat,
                        rec.get("productCategory"),
                        rec.get("masteryReq"),
                        (IMAGE_BASE + img) if img else None,
                        rec.get("description") if isinstance(rec.get("description"), str) else None,
                        json.dumps(rec, ensure_ascii=False),
                    )
                )
                resolver.add_item(clean_name, uid)
                if cat == "Relic":
                    short = _relic_short_name(clean_name)
                    if short:
                        resolver.add_relic(short[0], uid, prefer=uid.endswith("Bronze"))
    # relics and arcanes from ExportRelicArcane
    for rec in pe.get("ExportRelicArcane").get("ExportRelicArcane", []):
        uid, name = rec.get("uniqueName"), rec.get("name")
        if not uid or not name:
            continue
        cat = "Relic" if "relicRewards" in rec else "Arcane"
        img = images.get(uid)
        rows.append(
            (
                uid,
                name,
                cat,
                None,
                None,
                (IMAGE_BASE + img) if img else None,
                rec.get("description") if isinstance(rec.get("description"), str) else None,
                json.dumps(rec, ensure_ascii=False),
            )
        )
        resolver.add_item(name, uid)
        if cat == "Relic":
            short = _relic_short_name(name)
            if short:
                resolver.add_relic(short[0], uid, prefer=uid.endswith("Bronze"))
    for label, uid in (("Endo", CURRENCY_ITEMS["endo"]), ("Credits", CURRENCY_ITEMS["credits"])):
        rows.append((uid, label, "Currency", None, None, None, f"{label} (currency, pseudo item)", "{}"))
        resolver.add_item(label, uid)
    conn.executemany("INSERT OR REPLACE INTO item VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_recipes(conn: sqlite3.Connection, pe: PublicExport, resolver: NameResolver) -> int:
    recipes = pe.get("ExportRecipes").get("ExportRecipes", [])
    names = {r[0]: r[1] for r in conn.execute("SELECT unique_name, name FROM item")}
    rrows, irows = [], []
    for rec in recipes:
        uid, result = rec.get("uniqueName"), rec.get("resultType")
        if not uid or not result:
            continue
        rrows.append(
            (
                uid,
                result,
                rec.get("buildPrice"),
                rec.get("buildTime"),
                rec.get("skipBuildTimePrice"),
                rec.get("num", 1),
                1 if rec.get("consumeOnUse") else 0,
            )
        )
        for ing in rec.get("ingredients", []):
            irows.append((uid, ing.get("ItemType"), ing.get("ItemCount", 1)))
        if result in names:
            resolver.add_recipe(names[result], uid)
    conn.executemany("INSERT OR REPLACE INTO recipe VALUES (?,?,?,?,?,?,?)", rrows)
    conn.executemany("INSERT INTO recipe_ingredient VALUES (?,?,?)", irows)
    return len(rrows)


def load_relics(conn: sqlite3.Connection, pe: PublicExport, plus: PlusExport, resolver: NameResolver) -> int:
    plus_relics = plus.files.get("ExportRelics", {})
    rrows, rewards = [], []
    # The export lists one entry per refinement (…Bronze/Silver/Gold/Platinum).
    # The codex keeps one relic per short name, preferring the Intact variant.
    entries = [r for r in pe.get("ExportRelicArcane").get("ExportRelicArcane", []) if "relicRewards" in r]
    entries.sort(key=lambda r: 0 if str(r.get("uniqueName", "")).endswith("Bronze") else 1)
    seen: set[str] = set()
    for rec in entries:
        uid, name = rec["uniqueName"], rec["name"]
        short = _relic_short_name(name)
        if not short or short[0] in seen:
            continue
        seen.add(short[0])
        # the relic table's choice is canonical: drop-table names must resolve to it
        resolver.add_relic(short[0], uid, prefer=True)
        extra = plus_relics.get(uid, {})
        rrows.append(
            (uid, short[0], extra.get("era") or short[1], extra.get("category"), extra.get("quality"))
        )
        for rw in rec.get("relicRewards", []):
            rarity = str(rw.get("rarity", "")).upper()
            chances = RELIC_CHANCES.get(rarity, (None, None, None, None))
            rewards.append(
                (uid, strip_store_prefix(rw.get("rewardName", "")), rarity, rw.get("itemCount", 1), *chances)
            )
    conn.executemany("INSERT OR REPLACE INTO relic VALUES (?,?,?,?,?)", rrows)
    conn.executemany("INSERT INTO relic_reward VALUES (?,?,?,?,?,?,?,?)", rewards)
    return len(rrows)


def load_nodes(conn: sqlite3.Connection, pe: PublicExport, plus: PlusExport) -> int:
    mission_types = plus.files.get("ExportMissionTypes", {})
    by_index = {v.get("index"): (k, plus.text(v.get("name"))) for k, v in mission_types.items()}
    rows = []
    for rec in pe.get("ExportRegions").get("ExportRegions", []):
        uid = rec.get("uniqueName")
        if not uid:
            continue
        mt = by_index.get(rec.get("missionIndex"))
        rows.append(
            (
                uid,
                rec.get("name", uid),
                rec.get("systemName", "?"),
                rec.get("systemIndex"),
                mt[1] if mt else None,
                FACTIONS.get(rec.get("factionIndex"), f"faction_{rec.get('factionIndex')}"),
                rec.get("minEnemyLevel"),
                rec.get("maxEnemyLevel"),
                rec.get("masteryReq"),
                rec.get("nodeType"),
                json.dumps(rec, ensure_ascii=False),
            )
        )
    conn.executemany("INSERT OR REPLACE INTO node VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_drops(conn: sqlite3.Connection, drops: DropData, resolver: NameResolver) -> dict[str, int]:
    d = drops.data
    counts: dict[str, int] = {}
    nodes = {
        (normalize(n), normalize(p)): nid for nid, n, p in conn.execute("SELECT id, name, planet FROM node")
    }
    nodes_by_name: dict[str, str] = {}
    for (n, _p), nid in nodes.items():
        nodes_by_name.setdefault(n, nid)

    # mission rewards: planet -> place -> {gameMode, isEvent, rewards: {A:[...]}} or list
    rows = []
    for planet, places in d.get("missionRewards", {}).items():
        for place, info in places.items():
            node_id = nodes.get((normalize(place), normalize(planet))) or nodes_by_name.get(normalize(place))
            rewards = info.get("rewards", {})
            rot_iter = rewards.items() if isinstance(rewards, dict) else [("A", rewards)]
            for rotation, entries in rot_iter:
                for e in entries:
                    item_name = e.get("itemName", "")
                    rows.append(
                        (
                            node_id,
                            planet,
                            place,
                            info.get("gameMode"),
                            rotation,
                            item_name,
                            resolver.resolve(item_name, source=f"missionRewards/{planet}/{place}"),
                            e.get("rarity"),
                            e.get("chance"),
                            1 if info.get("isEvent") else 0,
                        )
                    )
    conn.executemany("INSERT INTO node_reward VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    counts["node_reward"] = len(rows)

    # enemy tables
    rows = []
    for e in d.get("enemyModTables", []):
        for m in e.get("mods", []):
            rows.append(
                (
                    e.get("enemyName", ""),
                    m.get("modName", ""),
                    resolver.resolve(m.get("modName", ""), source="enemyModTables"),
                    "mod",
                    m.get("rarity"),
                    m.get("chance"),
                    _float(e.get("enemyModDropChance")),
                )
            )
    for e in d.get("enemyBlueprintTables", []):
        for it in e.get("items", []):
            rows.append(
                (
                    e.get("enemyName", ""),
                    it.get("itemName", ""),
                    resolver.resolve(it.get("itemName", ""), source="enemyBlueprintTables"),
                    "blueprint",
                    it.get("rarity"),
                    it.get("chance"),
                    _float(e.get("blueprintDropChance") or e.get("enemyBlueprintDropChance")),
                )
            )
    for key, kind in (
        ("resourceByAvatar", "resource"),
        ("sigilByAvatar", "sigil"),
        ("additionalItemByAvatar", "item"),
    ):
        for e in d.get(key, []):
            for it in e.get("items", []):
                rows.append(
                    (
                        e.get("source", ""),
                        it.get("item", ""),
                        resolver.resolve(it.get("item", ""), source=key),
                        kind,
                        it.get("rarity"),
                        it.get("chance"),
                        None,
                    )
                )
    conn.executemany("INSERT INTO enemy_drop VALUES (?,?,?,?,?,?,?)", rows)
    counts["enemy_drop"] = len(rows)

    # bounties
    rows = []
    for key, region in (
        ("cetusBountyRewards", "Cetus"),
        ("solarisBountyRewards", "Orb Vallis"),
        ("deimosRewards", "Cambion Drift"),
        ("zarimanRewards", "Zariman"),
        ("entratiLabRewards", "Entrati Lab"),
        ("hexRewards", "Hollvania"),
    ):
        for b in d.get(key, []):
            for rotation, entries in b.get("rewards", {}).items():
                for e in entries:
                    item_name = e.get("itemName", "")
                    rows.append(
                        (
                            region,
                            b.get("bountyLevel", ""),
                            rotation,
                            e.get("stage"),
                            item_name,
                            resolver.resolve(item_name, source=key),
                            e.get("rarity"),
                            e.get("chance"),
                        )
                    )
    conn.executemany("INSERT INTO bounty_reward VALUES (?,?,?,?,?,?,?,?)", rows)
    counts["bounty_reward"] = len(rows)

    # transient: arbitrations etc., sorties, key rewards
    rows = []
    for t in d.get("transientRewards", []):
        for e in t.get("rewards", []):
            item_name = e.get("itemName", "")
            rows.append(
                (
                    t.get("objectiveName", ""),
                    e.get("rotation"),
                    item_name,
                    resolver.resolve(item_name, source="transientRewards"),
                    e.get("rarity"),
                    e.get("chance"),
                )
            )
    for e in d.get("sortieRewards", []):
        item_name = e.get("itemName", "")
        rows.append(
            (
                "Sortie",
                None,
                item_name,
                resolver.resolve(item_name, source="sortieRewards"),
                e.get("rarity"),
                e.get("chance"),
            )
        )
    for k in d.get("keyRewards", []):
        for rotation, entries in k.get("rewards", {}).items():
            for e in entries:
                item_name = e.get("itemName", "")
                rows.append(
                    (
                        k.get("keyName", ""),
                        rotation,
                        item_name,
                        resolver.resolve(item_name, source="keyRewards"),
                        e.get("rarity"),
                        e.get("chance"),
                    )
                )
    conn.executemany("INSERT INTO transient_reward VALUES (?,?,?,?,?,?)", rows)
    counts["transient_reward"] = len(rows)

    # syndicate tables (names)
    rows = []
    for syn, entries in d.get("syndicates", {}).items():
        for e in entries:
            item_name = e.get("item", "")
            rows.append(
                (
                    syn,
                    item_name,
                    resolver.resolve(item_name, source="syndicates"),
                    e.get("place"),
                    e.get("standing"),
                    e.get("cost"),
                    e.get("chance"),
                    e.get("rarity"),
                )
            )
    conn.executemany("INSERT INTO syndicate_drop VALUES (?,?,?,?,?,?,?,?)", rows)
    counts["syndicate_drop"] = len(rows)
    return counts


def _float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def load_vendors(conn: sqlite3.Connection, plus: PlusExport) -> int:
    rows = []
    for path, vendor in plus.files.get("ExportVendors", {}).items():
        vendor_name = path.rsplit("/", 1)[-1].removesuffix("Manifest")
        for it in vendor.get("items", []):
            store = it.get("storeItem")
            if not store:
                continue
            prices = [
                {"item": strip_store_prefix(p.get("ItemType", "")), "count": p.get("ItemCount")}
                for p in it.get("itemPrices", [])
            ]
            extra = {k: it[k] for k in ("credits", "regularPrice", "premiumPrice", "standing") if k in it}
            rows.append(
                (
                    path,
                    vendor_name,
                    strip_store_prefix(store),
                    it.get("quantity"),
                    json.dumps({"items": prices, **extra}),
                    1 if it.get("alwaysOffered") else 0,
                )
            )
    conn.executemany("INSERT INTO vendor_offer VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


def load_syndicates(conn: sqlite3.Connection, plus: PlusExport) -> int:
    srows, orows = [], []
    for tag, s in plus.files.get("ExportSyndicates", {}).items():
        name = plus.text(s.get("name"), tag) or tag
        srows.append((tag, s.get("uniqueName"), name, json.dumps(s, ensure_ascii=False)))
        for f in s.get("favours", []):
            store = f.get("storeItem")
            if not store:
                continue
            orows.append(
                (
                    tag,
                    strip_store_prefix(store),
                    f.get("standingCost"),
                    f.get("creditsCost"),
                    f.get("requiredLevel"),
                    1 if f.get("rankUpReward") else 0,
                )
            )
    conn.executemany("INSERT OR REPLACE INTO syndicate VALUES (?,?,?,?)", srows)
    conn.executemany("INSERT INTO syndicate_offer VALUES (?,?,?,?,?,?)", orows)
    return len(srows)


def load_challenges(conn: sqlite3.Connection, plus: PlusExport) -> int:
    rows = []
    for uid, c in plus.files.get("ExportChallenges", {}).items():
        rows.append(
            (
                uid,
                plus.text(c.get("name"), uid.rsplit("/", 1)[-1]) or uid,
                plus.text(c.get("description"), ""),
                json.dumps(c.get("countedRewards", []), ensure_ascii=False),
            )
        )
    conn.executemany("INSERT OR REPLACE INTO challenge VALUES (?,?,?,?)", rows)
    return len(rows)


def load_market(conn: sqlite3.Connection, items: list[MarketItem]) -> int:
    rows = [(m.unique_name, m.slug, m.name, json.dumps(m.tags)) for m in items]
    conn.executemany("INSERT OR REPLACE INTO market_item VALUES (?,?,?,?)", rows)
    return len(rows)


def write_name_map(conn: sqlite3.Connection, resolver: NameResolver) -> None:
    rows = [(k, v, "item") for k, v in resolver.items.items()]
    rows += [(k + " blueprint", v, "recipe") for k, v in resolver.recipes_by_result_name.items()]
    rows += [(k, v, "relic") for k, v in resolver.relics.items()]
    conn.executemany("INSERT OR IGNORE INTO name_map VALUES (?,?,?)", rows)
    conn.executemany(
        "INSERT OR REPLACE INTO unresolved_name VALUES (?,?,?)",
        [(name, count, src) for name, (count, src) in resolver.unresolved.items()],
    )


# --------------------------------------------------------------------------------------


def build_codex(conn: sqlite3.Connection, payloads: CodexPayloads) -> BuildReport:
    started = time.time()
    conn.executescript(SCHEMA)
    resolver = NameResolver()
    report = BuildReport()
    pe, plus, drops = payloads.public_export, payloads.plus, payloads.drops

    with conn:
        report.counts["item"] = load_items(conn, pe, resolver)
        report.counts["recipe"] = load_recipes(conn, pe, resolver)
        report.counts["relic"] = load_relics(conn, pe, plus, resolver)
        report.counts["node"] = load_nodes(conn, pe, plus)
        report.counts["vendor_offer"] = load_vendors(conn, plus)
        report.counts["syndicate"] = load_syndicates(conn, plus)
        report.counts["challenge"] = load_challenges(conn, plus)
        report.counts.update(load_drops(conn, drops, resolver))
        report.counts["market_item"] = load_market(conn, payloads.market)
        write_name_map(conn, resolver)
        now = _now()
        conn.executemany(
            "INSERT OR REPLACE INTO source_version VALUES (?,?,?,?)",
            [
                ("schema", str(SCHEMA_VERSION), now, None),
                ("public_export", pe.version, now, json.dumps({"manifests": sorted(pe.manifests)})),
                ("public_export_plus", plus.version, now, json.dumps({"files": sorted(plus.files)})),
                ("wfcd_drops", drops.version, now, json.dumps({"modified_ms": drops.modified})),
                ("warframe_market", _now(), now, json.dumps({"items": len(payloads.market)})),
            ],
        )
    report.unresolved = dict(resolver.unresolved)
    report.seconds = time.time() - started
    return report


def fetch_payloads(client: CachedClient, *, force: bool = False) -> CodexPayloads:
    log.info("fetching public export")
    pe = fetch_public_export(client, force=force)
    log.info("fetching public export plus")
    plus = fetch_plus(client, force=force)
    log.info("fetching drop data")
    drops = fetch_drops(client, force=force)
    log.info("fetching market items")
    try:
        market = fetch_market_items(client, force=force)
    except Exception as exc:  # market is optional
        log.warning("warframe.market unavailable: %s", exc)
        market = []
    return CodexPayloads(public_export=pe, plus=plus, drops=drops, market=market)


def update_codex(settings: Settings, *, force: bool = False) -> BuildReport:
    """Fetch all static sources and rebuild the codex atomically."""
    client = CachedClient(settings.cache_dir)
    try:
        payloads = fetch_payloads(client, force=force)
    finally:
        client.close()
    tmp = settings.codex_path.with_suffix(".sqlite.tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        report = build_codex(conn, payloads)
        conn.execute("VACUUM")
    finally:
        conn.close()
    Path(tmp).replace(settings.codex_path)
    return report
