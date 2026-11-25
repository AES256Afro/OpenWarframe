"""Live world state for the app, matched against the account.

Fissures and void storms are checked against the relics you own (by tier) and the parts
you need; Baro's stock and invasion rewards are checked against what you have not
mastered or are short of. "You are here" comes from the game's own log.
"""

from __future__ import annotations

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


def you_are_here(log_path: Path | None = None, tail_bytes: int = 768_000) -> dict | None:
    """Last mission the game loaded, read from the end of EE.log."""
    from ..live.eelog import default_log_path, parse_lines

    path = log_path or default_log_path()
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - tail_bytes))
            text = f.read().decode("utf-8", errors="replace")
        modified = path.stat().st_mtime
    except OSError:
        return None
    lines = text.splitlines()[1:] if size > tail_bytes else text.splitlines()
    events = [e for e in parse_lines(lines) if e.kind == "mission_loaded"]
    if not events:
        return None
    last = events[-1]
    return {
        "node": last.data.get("node"),
        "mission": _pretty_mission(last.data.get("missionType")),
        "faction": (last.data.get("faction") or "").removeprefix("FC_").title(),
        "log_age_min": round((time.time() - modified) / 60, 1),
    }


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
        for side, key in (("Attacker", "AttackerReward"), ("Defender", "DefenderReward")):
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
                    {"side": side, "name": name, "count": r.get("ItemCount", 1), "flag": valuable or needed}
                )
        goal = inv.get("Goal") or 1
        progress = round(50 + 50 * (inv.get("Count") or 0) / goal)
        invasions.append(
            {
                "id": str((inv.get("_id") or {}).get("$oid", inv.get("Node"))),
                **place(inv.get("Node", "")),
                "attacker": (inv.get("Faction") or "").removeprefix("FC_").title(),
                "defender": (inv.get("DefenderFaction") or "").removeprefix("FC_").title(),
                "progress": max(0, min(100, progress)),
                "rewards": sides,
                "worth_it": any(s["flag"] for s in sides),
            }
        )
    invasions.sort(key=lambda i: not i["worth_it"])

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
        "here": here,
        "inventory": have_inv,
    }
