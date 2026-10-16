"""Turn a raw profile payload into a Snapshot.

Mastery math (per the wiki and FrameHub): affinity to rank r is 1000·r² for
Warframes, Archwings, Necramechs and companions and 500·r² for everything else;
each rank is worth 200 or 100 mastery XP respectively; ranks above 30 (up to 40)
count. The profile gives PlayerLevel directly, so item mastery is an estimate used
for "what is left", not the source of the rank.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from ..codex.queries import Codex
from .model import (
    SUIT_CATEGORIES,
    Affiliation,
    Challenge,
    Identity,
    ItemXP,
    Loadout,
    NodeProgress,
    Progression,
    Snapshot,
    SourceInfo,
)

MAX_RANK = 40

# Fallbacks when the codex is not available or does not know the item.
_PATH_HINTS = (
    ("/Powersuits/Archwing/", "Archwing"),
    ("/Powersuits/EntratiMech/", "Necramech"),
    ("/Powersuits/", "Warframe"),
    ("/Types/Friendly/Pets/", "Companion"),
    ("/Types/Sentinels/", "Companion"),
    ("/Weapons/Sentinels/", "Companion Weapon"),
    ("/Weapons/Tenno/Archwing/", "Archgun"),
    ("/Weapons/Tenno/Melee/", "Melee"),
    ("/Weapons/Tenno/Pistol", "Secondary"),
    ("/Weapons/Tenno/", "Primary"),
    ("/Types/Vehicles/Hoverboard", "K-Drive"),
    ("/OperatorAmplifiers/", "Amp"),
)


def category_from_path(path: str) -> str:
    for needle, cat in _PATH_HINTS:
        if needle in path:
            return cat
    return "Weapon"


def rank_from_xp(xp: int, suit: bool) -> int:
    per = 1000 if suit else 500
    if xp <= 0:
        return 0
    return min(MAX_RANK, int(math.isqrt(xp // per)))


def mastery_for(rank: int, suit: bool) -> int:
    return rank * (200 if suit else 100)


def _mongo_date(v) -> datetime | None:
    try:
        ms = int(v["$date"]["$numberLong"])
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (KeyError, TypeError, ValueError):
        return None


def _syndicate_name(codex: Codex | None, tag: str) -> str:
    if codex:
        row = codex.conn.execute("SELECT name FROM syndicate WHERE tag = ?", (tag,)).fetchone()
        if row:
            return row[0]
    return tag.removesuffix("Syndicate")


def parse_profile(
    data: dict, *, platform: str = "pc", codex: Codex | None = None, taken_at: datetime | None = None
) -> Snapshot:
    r = data["Results"][0]
    now = taken_at or datetime.now(UTC)

    # item lookups through the codex (names, categories), with path fallbacks
    item_meta: dict[str, tuple[str, str]] = {}
    if codex:
        for row in codex.conn.execute("SELECT unique_name, name, category FROM item"):
            item_meta[row[0]] = (row[1], row[2])
    node_meta: dict[str, tuple[str, str]] = {}
    if codex:
        for row in codex.conn.execute("SELECT id, name, planet FROM node"):
            node_meta[row[0]] = (row[1], row[2])

    items: list[ItemXP] = []
    for e in r.get("LoadOutInventory", {}).get("XPInfo", []):
        path, xp = e.get("ItemType", ""), int(e.get("XP", 0))
        name, cat = item_meta.get(path, (path.rsplit("/", 1)[-1], category_from_path(path)))
        suit = cat in SUIT_CATEGORIES
        rank = rank_from_xp(xp, suit)
        items.append(
            ItemXP(
                item=path,
                name=name,
                category=cat,
                xp=xp,
                rank=rank,
                mastery_xp=mastery_for(rank, suit),
                mastered=rank >= 30,
            )
        )
    items.sort(key=lambda i: (-i.xp, i.name))

    nodes = []
    for m in r.get("Missions", []):
        tag = m.get("Tag", "")
        name, planet = node_meta.get(tag, (tag, "?"))
        nodes.append(
            NodeProgress(
                node=tag,
                name=name,
                planet=planet,
                completes=int(m.get("Completes", 0)),
                steel_path=bool(m.get("Tier")),
            )
        )

    affiliations = [
        Affiliation(
            tag=a.get("Tag", ""),
            name=_syndicate_name(codex, a.get("Tag", "")),
            standing=int(a.get("Standing", 0)),
            title=int(a.get("Title", 0)),
        )
        for a in r.get("Affiliations", [])
    ]
    daily = {
        k.removeprefix("DailyAffiliation") or "Default": int(v)
        for k, v in r.items()
        if k.startswith("DailyAffiliation")
    }
    challenges = [
        Challenge(name=c.get("Name", ""), progress=int(c.get("Progress", 0)))
        for c in r.get("ChallengeProgress", [])
    ]

    loi = r.get("LoadOutInventory", {})

    def first_type(key: str) -> str | None:
        lst = loi.get(key) or []
        return lst[0].get("ItemType") if lst else None

    loadout = Loadout(
        focus_school=(r.get("LoadOutPreset") or {}).get("FocusSchool"),
        warframe=first_type("Suits"),
        primary=first_type("LongGuns"),
        secondary=first_type("Pistols"),
        melee=first_type("Melee"),
    )

    stats = dict(data.get("Stats", {}))
    progression = Progression(
        mastery_rank=int(r.get("PlayerLevel", 0)),
        mastery_xp_from_items=sum(i.mastery_xp for i in items),
        play_time_s=stats.get("TimePlayedSec"),
        missions_completed=stats.get("MissionsCompleted"),
        items=items,
        nodes=nodes,
        affiliations=affiliations,
        daily_affiliations=daily,
        intrinsics={k: int(v) for k, v in (r.get("PlayerSkills") or {}).items()},
        challenges=challenges,
        loadout=loadout,
    )
    identity = Identity(
        display_name=r.get("DisplayName"),
        account_id=(r.get("AccountId") or {}).get("$oid")
        if isinstance(r.get("AccountId"), dict)
        else r.get("AccountId"),
        platform=platform,
        clan=r.get("GuildName"),
        clan_tier=r.get("GuildTier"),
        created_at=_mongo_date(r.get("Created")),
    )
    return Snapshot(
        taken_at=now,
        sources=[SourceInfo(kind="profile", fetched_at=now, detail=f"platform={platform}")],
        coverage=["progression", "stats", "loadout", "achievements", "syndicates", "intrinsics", "starchart"],
        identity=identity,
        progression=progression,
        stats=stats,
        raw={"profile": data},
    )
