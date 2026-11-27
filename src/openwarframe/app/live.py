"""Live world state for the app, matched against the account.

Fissures and void storms are checked against the relics you own (by tier) and the parts
you need; Baro's stock and invasion rewards are checked against what you have not
mastered or are short of. "You are here" comes from the game's own log.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from ..codex.names import mission_label
from ..http import CachedClient

WORLDSTATE_URL = "https://api.warframe.com/cdn/worldState.php"
TIERS = {
    "VoidT1": "Lith",
    "VoidT2": "Meso",
    "VoidT3": "Neo",
    "VoidT4": "Axi",
    "VoidT5": "Requiem",
    "VoidT6": "Omnia",
}
RELAYS = {
    "MercuryHUB": "Larunda Relay (Mercury)",
    "VenusHUB": "Vesper Relay (Venus)",
    "EarthHUB": "Strata Relay (Earth)",
    "SaturnHUB": "Kronia Relay (Saturn)",
    "EuropaHUB": "Leonov Relay (Europa)",
    "ErisHUB": "Kuiper Relay (Eris)",
    "PlutoHUB": "Orcus Relay (Pluto)",
}
FAST = {"Capture", "Exterminate", "Sabotage", "Rescue", "Spy", "Mobile Defense", "Hijack", "Void Flood"}
ALWAYS_VALUABLE = ("Orokin Catalyst", "Orokin Reactor", "Forma", "Exilus", "Riven")


def _ms(v) -> int | None:
    try:
        return int(v["$date"]["$numberLong"])
    except (KeyError, TypeError, ValueError):
        return None


def _pretty_mission(mt: str | None) -> str:
    return mission_label(mt)


def _store_to_item(path: str) -> str:
    return path.replace("/Lotus/StoreItems/", "/Lotus/", 1)


ARCHONS = {
    "SORTIE_BOSS_AMAR": "Archon Amar",
    "SORTIE_BOSS_NIRA": "Archon Nira",
    "SORTIE_BOSS_BOREAL": "Archon Boreal",
}
ARCHON_SHARDS = {"Archon Amar": "crimson", "Archon Nira": "amber", "Archon Boreal": "azure"}
# the profile's DailyAffiliation<suffix> keys: how much standing each group can still earn today
STANDING_NAMES = {
    "Default": "Main syndicates",
    "Pvp": "Conclave",
    "Library": "Cephalon Simaris",
    "Cetus": "Ostrons",
    "Quills": "The Quills",
    "Solaris": "Solaris United",
    "Ventkids": "Ventkids",
    "Vox": "Vox Solaris",
    "Entrati": "Entrati",
    "Necraloid": "Necraloid",
    "Zariman": "The Holdfasts",
    "Kahl": "Kahl's Garrison",
    "Cavia": "Cavia",
    "Hex": "The Hex",
}


def _words(name: str) -> str:
    """'CeramicDagger' -> 'Ceramic Dagger', 'MPVSevagothPrimeSinglePack' -> 'Sevagoth Prime Single Pack'."""
    name = name.removeprefix("MPV")
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).strip()


def _owns(item: dict | None) -> bool:
    """Owned now (inventory) or, without an inventory, leveled at some point."""
    if not item:
        return False
    if item.get("owned") is not None:
        return bool(item["owned"])
    return item.get("mastery") != "Never leveled"


def build_weekly(ws: dict, data: dict, place, now_ms: int) -> list[dict]:
    """Archon Hunt, the Circuit's weekly picks and today's standing, as rows for the Live view."""
    by_name: dict[str, list[dict]] = {}
    for it in data.get("items", []):
        by_name.setdefault(it["name"].lower(), []).append(it)
    rows: list[dict] = []

    for a in ws.get("LiteSorties") or []:
        exp = _ms(a.get("Expiry"))
        if exp and exp < now_ms:
            continue
        boss = ARCHONS.get(
            a.get("Boss", ""), _words(str(a.get("Boss", "")).removeprefix("SORTIE_BOSS_").title())
        )
        missions = [
            f"{_pretty_mission(m.get('missionType'))} on {place(m.get('node', ''))['where']}"
            for m in a.get("Missions") or []
        ]
        shard = ARCHON_SHARDS.get(boss)
        rows.append(
            {
                "id": "archon",
                "kind": "Archon Hunt",
                "what": boss,
                "detail": " → ".join(missions),
                "for_you": True,
                "note": f"An {shard} Archon Shard once a week" if shard else "An Archon Shard once a week",
                "hours_left": round((exp - now_ms) / 3_600_000, 1) if exp else None,
            }
        )
        break

    for sched in ws.get("EndlessXpSchedule") or []:
        exp = _ms(sched.get("Expiry"))
        start = _ms(sched.get("Activation"))
        if (exp and exp < now_ms) or (start and start > now_ms):
            continue
        for cat in sched.get("CategoryChoices") or []:
            hard = cat.get("Category") == "EXC_HARD"
            for raw in cat.get("Choices") or []:
                name = _words(raw)
                if hard:
                    # an Incarnon Genesis adapter fits the base weapon and its Prime/variants
                    family = [
                        it
                        for key, its in by_name.items()
                        if key in (name.lower(), name.lower() + " prime") or key.endswith(" " + name.lower())
                        for it in its
                    ]
                    own = [it["name"] for it in family if _owns(it)]
                    note = (
                        f"You have {', '.join(sorted(own)[:3])}: worth taking the adapter"
                        if own
                        else "You don't own this weapon yet"
                    )
                    rows.append(
                        {
                            "id": f"circuit-sp|{raw}",
                            "kind": "Circuit, Steel Path",
                            "what": f"{name} Incarnon Genesis",
                            "detail": "Duviri Circuit (Steel Path) reward this week",
                            "for_you": bool(own),
                            "note": note,
                            "hours_left": round((exp - now_ms) / 3_600_000, 1) if exp else None,
                        }
                    )
                else:
                    frame = (by_name.get(name.lower()) or [None])[0]
                    need = bool(frame and frame.get("mastery") != "Mastered")
                    rows.append(
                        {
                            "id": f"circuit|{raw}",
                            "kind": "Circuit",
                            "what": name,
                            "detail": "Duviri Circuit (normal) Warframe parts this week",
                            "for_you": need,
                            "note": "Not mastered yet" if need else "Already mastered",
                            "hours_left": round((exp - now_ms) / 3_600_000, 1) if exp else None,
                        }
                    )
        break

    standing = (data.get("meta") or {}).get("standing_left", {})
    for key, left in sorted(
        standing.items(), key=lambda kv: (kv[0] != "Default", STANDING_NAMES.get(kv[0], kv[0]))
    ):
        if left is None:
            continue
        rows.append(
            {
                "id": f"standing|{key}",
                "kind": "Standing today",
                "what": STANDING_NAMES.get(key, _words(key)),
                "detail": f"{left:,} standing left today (at your last profile refresh)",
                "for_you": left > 0,
                "note": "Resets at 00:00 UTC",
                "hours_left": None,
            }
        )
    return rows


def build_varzia(ws: dict, data: dict, names: dict, now_ms: int) -> dict | None:
    """Varzia's Prime Resurgence stock, flagged where it gives you something you need."""
    items = {i["id"]: i for i in data.get("items", [])}
    relics = {r["id"]: r for r in data.get("relics", [])}
    for v in ws.get("PrimeVaultTraders") or []:
        start, end = _ms(v.get("Activation")), _ms(v.get("Expiry"))
        stock = []
        for evergreen, it in [(False, x) for x in v.get("Manifest") or []] + [
            (True, x) for x in v.get("EvergreenManifest") or []
        ]:
            uid = _store_to_item(it.get("ItemType", ""))
            item, relic = items.get(uid), relics.get(uid)
            if evergreen and not item:
                continue  # the permanent stock is mostly cosmetics: keep only gear
            if relic:
                why = (
                    f"Holds {relic['needed']} part{'s' if relic['needed'] != 1 else ''} you need"
                    if relic.get("needed")
                    else ""
                )
            elif item:
                why = "For mastery" if item["mastery"] != "Mastered" else ""
            else:
                why = ""
            stock.append(
                {
                    "name": relic["name"] if relic else names.get(uid) or _words(uid.rsplit("/", 1)[-1]),
                    # relics cost Aya (earned in game); Prime gear and packs cost Regal Aya
                    "aya": it.get("RegularPrice"),
                    "regal_aya": it.get("PrimePrice"),
                    "kind": "Relic"
                    if relic or "/Projections/" in uid
                    else "Gear"
                    if item
                    else "Pack or cosmetic",
                    "for_you": bool(why),
                    "why": why,
                }
            )
        stock.sort(key=lambda s: (not s["for_you"], s["kind"] != "Gear", s["name"]))
        return {
            "here": bool(start and start <= now_ms and (not end or now_ms < end)),
            "days_left": round((end - now_ms) / 86_400_000, 1) if end else None,
            "stock": stock,
        }
    return None


FACTIONS = {
    "FC_GRINEER": "Grineer",
    "FC_CORPUS": "Corpus",
    "FC_INFESTATION": "Infested",
    "FC_OROKIN": "Orokin",
    "FC_CORRUPTED": "Corrupted",
    "FC_SENTIENT": "Sentient",
    "FC_NARMER": "Narmer",
    "FC_MITW": "The Murmur",
    "FC_MURMUR": "The Murmur",
    "FC_SCALDRA": "Scaldra",
    "FC_TECHROT": "Techrot",
    "FC_STALKER": "Stalker",
}


def faction_name(key: str | None) -> str:
    """'FC_INFESTATION' -> 'Infested'; unknown keys lose the prefix and are title-cased."""
    key = str(key or "")
    return FACTIONS.get(key) or key.removeprefix("FC_").replace("_", " ").title()


# (path, mtime_ns, size, tail_bytes) -> parsed result; the log is only re-read when it changes
_HERE_CACHE: dict[tuple, tuple[dict | None, float]] = {}


def you_are_here(log_path: Path | None = None, tail_bytes: int = 768_000) -> dict | None:
    """Last mission the game loaded, read from the end of EE.log.

    The answer is kept until the log changes (path, modified time and size), so polling
    the Live tab doesn't re-read most of a megabyte each time.
    """
    from ..live.eelog import default_log_path, parse_lines

    path = log_path or default_log_path()
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size, tail_bytes)
    hit = _HERE_CACHE.get(key)
    if hit is None:
        size = st.st_size
        try:
            with path.open("rb") as f:
                f.seek(max(0, size - tail_bytes))
                text = f.read().decode("utf-8", errors="replace")
        except OSError:
            return None
        lines = text.splitlines()[1:] if size > tail_bytes else text.splitlines()
        events = [e for e in parse_lines(lines) if e.kind == "mission_loaded"]
        found = None
        if events:
            last = events[-1]
            found = {
                "node": last.data.get("node"),
                "mission": _pretty_mission(last.data.get("missionType")),
                "faction": faction_name(last.data.get("faction") or ""),
            }
        _HERE_CACHE.clear()  # one log at a time; never grows
        hit = _HERE_CACHE[key] = (found, st.st_mtime)
    found, modified = hit
    if found is None:
        return None
    return {**found, "log_age_min": round((time.time() - modified) / 60, 1)}


def build_live(
    conn, data: dict, client: CachedClient, *, now_ms: int | None = None, log_path: Path | None = None
) -> dict:
    ws = client.get_json(WORLDSTATE_URL, max_age=60)
    now_ms = now_ms or int(time.time() * 1000)
    nodes = {
        r[0]: {
            "name": r[1],
            "planet": r[2],
            "faction": r[3],
            "level": f"{r[4]}-{r[5]}" if r[4] is not None else "",
        }
        for r in conn.execute("SELECT id, name, planet, faction, level_min, level_max FROM node")
    }
    names = dict(conn.execute("SELECT unique_name, name FROM item"))
    have_inv = data.get("meta", {}).get("inventory") is not None
    relics = data.get("relics", [])
    by_tier: dict[str, list[dict]] = {}
    for r in relics:
        if have_inv and not r.get("count"):
            continue
        by_tier.setdefault(r["tier"], []).append(r)
    items = {i["id"]: i for i in data.get("items", [])}
    short = {r["id"] for r in data.get("resources", []) if r.get("short")}

    def place(node_id: str) -> dict:
        n = nodes.get(node_id) or nodes.get(node_id.split("_")[0], {})
        if n:
            label = f"{n['name']} ({n['planet']})"
        elif node_id.startswith("CrewBattleNode"):
            label = "Railjack void storm"
        else:
            label = node_id
        return {"node": node_id, "where": label, "level": n.get("level", ""), "faction": n.get("faction", "")}

    def relic_match(tier: str) -> dict:
        # an Omnia fissure takes a relic of any tier
        pool = [r for rs in by_tier.values() for r in rs] if tier == "Omnia" else by_tier.get(tier, [])
        useful = [r for r in pool if r["needed"] or r["vaulted_parts"]]
        useful.sort(key=lambda r: (-r["needed"], -r["vaulted_parts"], -(r.get("count") or 0)))
        best = useful[0] if useful else None
        return {
            "owned_relics": sum(r.get("count") or 0 for r in pool) if have_inv else None,
            "useful_relics": len(useful),
            "best_relic": best["name"] if best else None,
            "best_relic_needed": best["needed"] if best else 0,
            "best_relic_count": (best.get("count") if best else None),
        }

    fissures = []
    for f in ws.get("ActiveMissions", []):
        exp = _ms(f.get("Expiry"))
        if exp and exp < now_ms:
            continue
        tier = TIERS.get(f.get("Modifier"), f.get("Modifier"))
        mission = _pretty_mission(f.get("MissionType"))
        m = relic_match(tier)
        fissures.append(
            {
                "id": f"{f.get('Node')}|{f.get('Modifier')}|{bool(f.get('Hard'))}",
                "tier": tier,
                "mission": mission,
                "steel_path": bool(f.get("Hard")),
                "fast": mission in FAST,
                "minutes_left": round((exp - now_ms) / 60000) if exp else None,
                **place(f.get("Node", "")),
                **m,
            }
        )
    fissures.sort(key=lambda x: (-x["useful_relics"], not x["fast"], x["steel_path"], x["minutes_left"] or 0))

    storms = []
    for s in ws.get("VoidStorms", []):
        exp = _ms(s.get("Expiry"))
        if exp and exp < now_ms:
            continue
        tier = TIERS.get(s.get("ActiveMissionTier"), s.get("ActiveMissionTier"))
        storms.append(
            {
                "id": f"{s.get('Node')}|{tier}",
                "tier": tier,
                "minutes_left": round((exp - now_ms) / 60000) if exp else None,
                **place(s.get("Node", "")),
                **relic_match(tier),
            }
        )

    baro = None
    for v in ws.get("VoidTraders", []):
        start, end = _ms(v.get("Activation")), _ms(v.get("Expiry"))
        here = bool(start and end and start <= now_ms < end)
        stock = []
        for it in v.get("Manifest") or []:
            uid = _store_to_item(it.get("ItemType", ""))
            item = items.get(uid)
            stock.append(
                {
                    "name": names.get(uid, uid.rsplit("/", 1)[-1]),
                    "ducats": it.get("PrimePrice"),
                    "credits": it.get("RegularPrice"),
                    "for_mastery": bool(item and item["mastery"] != "Mastered"),
                }
            )
        stock.sort(key=lambda s: (not s["for_mastery"], s["name"]))
        baro = {
            "here": here,
            "where": RELAYS.get(v.get("Node", ""), v.get("Node", "")),
            "hours_until": None if here or not start else round((start - now_ms) / 3_600_000, 1),
            "hours_left": round((end - now_ms) / 3_600_000, 1) if here and end else None,
            "stock": stock,
        }
        break

    invasions = []
    for inv in ws.get("Invasions", []):
        if inv.get("Completed"):
            continue
        sides = []
        attacker_faction = faction_name(inv.get("Faction"))
        defender_faction = faction_name(inv.get("DefenderFaction"))
        for side, key, faction in (
            ("Attacker", "AttackerReward", attacker_faction),
            ("Defender", "DefenderReward", defender_faction),
        ):
            reward = inv.get(key) or {}
            parts = reward.get("countedItems", []) if isinstance(reward, dict) else []
            for r in parts:
                uid = r.get("ItemType", "")
                name = names.get(uid) or uid.rsplit("/", 1)[-1]
                squashed = name.replace(" ", "").lower()
                valuable = (
                    any(v.replace(" ", "").lower() in squashed for v in ALWAYS_VALUABLE) or uid in short
                )
                needed = bool(items.get(uid) and items[uid]["mastery"] != "Mastered")
                sides.append(
                    {
                        "side": side,
                        "faction": faction,  # the faction you fight for to earn this reward
                        "name": name,
                        "count": r.get("ItemCount", 1),
                        "flag": valuable or needed,
                    }
                )
        goal = inv.get("Goal") or 1
        progress = round(50 + 50 * (inv.get("Count") or 0) / goal)
        invasions.append(
            {
                "id": str((inv.get("_id") or {}).get("$oid", inv.get("Node"))),
                **place(inv.get("Node", "")),
                "attacker": (inv.get("Faction") or "").removeprefix("FC_").title(),
                "defender": (inv.get("DefenderFaction") or "").removeprefix("FC_").title(),
                "attacker_faction": attacker_faction,
                "defender_faction": defender_faction,
                "progress": max(0, min(100, progress)),
                "rewards": sides,
                "worth_it": any(s["flag"] for s in sides),
            }
        )
    invasions.sort(key=lambda i: not i["worth_it"])

    weekly = build_weekly(ws, data, place, now_ms)
    varzia = build_varzia(ws, data, names, now_ms)

    here = you_are_here(log_path)
    if here and here.get("node"):
        here["where"] = place(here["node"])["where"]
        here["fissure"] = here["node"].endswith("_ActiveMission")
    return {
        "fetched": now_ms,
        "fissures": fissures,
        "storms": storms,
        "baro": baro,
        "invasions": invasions,
        "weekly": weekly,
        "varzia": varzia,
        "here": here,
        "inventory": have_inv,
    }
