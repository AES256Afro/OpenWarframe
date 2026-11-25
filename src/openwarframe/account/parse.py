"""Turn a raw profile payload into a Snapshot.

Mastery math (per the wiki and FrameHub): affinity to rank r is 1000·r² for
Warframes, Archwings, Necramechs, companions and K-Drives and 500·r² for everything
else; each rank is worth 200 or 100 mastery XP respectively. The profile keeps
counting affinity past the cap, so ranks are clamped: 30 for ordinary items, 40 for
the few that can be ranked past 30 (see ``max_rank``). The profile gives PlayerLevel
directly, so item mastery is an estimate used for "what is left", not the source of
the rank.
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

MAX_RANK = 30
MAX_RANK_EXTENDED = 40

# Items that can be ranked past 30 (up to 40): adversary weapons (Kuva, Tenet, Coda),
# Paracesis and Necramechs. Matched on the display name, the codex category, and as a
# fallback without a codex, the uniqueName path.
EXTENDED_RANK_PREFIXES = ("Kuva ", "Tenet ", "Coda ", "Dual Coda ")
EXTENDED_RANK_NAMES = {"Paracesis"}
EXTENDED_RANK_CATEGORIES = {"Necramech"}
EXTENDED_RANK_PATHS = ("/KuvaLich/", "/InfestedLich/", "/Powersuits/EntratiMech/")

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


def max_rank(name: str, category: str, path: str = "") -> int:
    """Highest rank an item can reach: 40 for the extended-rank items, else 30."""
    if (
        name.startswith(EXTENDED_RANK_PREFIXES)
        or name in EXTENDED_RANK_NAMES
        or category in EXTENDED_RANK_CATEGORIES
        or any(p in path for p in EXTENDED_RANK_PATHS)
    ):
        return MAX_RANK_EXTENDED
    return MAX_RANK


def rank_from_xp(xp: int, suit: bool, cap: int = MAX_RANK) -> int:
    per = 1000 if suit else 500
    if xp <= 0:
        return 0
    return min(cap, int(math.isqrt(xp // per)))


def mastery_for(rank: int, suit: bool) -> int:
    return rank * (200 if suit else 100)


def clean_display_name(name: str | None) -> str | None:
    """Drop the platform icon DE appends to cross-platform names (Private Use Area glyphs)."""
    if not name:
        return name
    return "".join(ch for ch in name if not 0xE000 <= ord(ch) <= 0xF8FF).strip() or name


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


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _rows(v) -> list[dict]:
    """The dict entries of a list; anything else (null, a changed type) reads as empty."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_profile(
    data: dict, *, platform: str = "pc", codex: Codex | None = None, taken_at: datetime | None = None
) -> Snapshot:
    """Parse the public profile. Missing or null fields read as empty, never as a crash:
    a game update that changes a field must not stop the app from syncing at all."""
    results = _rows(_dict(data).get("Results"))
    if not results:
        raise ValueError("the profile has no Results")
    r = results[0]
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
    for e in _rows(_dict(r.get("LoadOutInventory")).get("XPInfo")):
        path, xp = str(e.get("ItemType") or ""), _int(e.get("XP"))
        if not path:
            continue
        name, cat = item_meta.get(path, (path.rsplit("/", 1)[-1], category_from_path(path)))
        suit = cat in SUIT_CATEGORIES
        cap = max_rank(name, cat, path)
        rank = rank_from_xp(xp, suit, cap)
        items.append(
            ItemXP(
                item=path,
                name=name,
                category=cat,
                xp=xp,
                rank=rank,
                mastery_xp=mastery_for(rank, suit),
                # rank-40 items (Kuva, Tenet, Coda, Necramechs...) keep giving mastery to 40
                mastered=rank >= cap,
            )
        )
    items.sort(key=lambda i: (-i.xp, i.name))

    nodes = []
    for m in _rows(r.get("Missions")):
        tag = str(m.get("Tag") or "")
        name, planet = node_meta.get(tag, (tag, "?"))
        nodes.append(
            NodeProgress(
                node=tag,
                name=name,
                planet=planet,
                completes=_int(m.get("Completes")),
                steel_path=bool(m.get("Tier")),
            )
        )

    affiliations = [
        Affiliation(
            tag=str(a.get("Tag") or ""),
            name=_syndicate_name(codex, str(a.get("Tag") or "")),
            standing=_int(a.get("Standing")),
            title=_int(a.get("Title")),
        )
        for a in _rows(r.get("Affiliations"))
    ]
    daily = {
        k.removeprefix("DailyAffiliation") or "Default": _int(v)
        for k, v in r.items()
        if k.startswith("DailyAffiliation") and v is not None
    }
    challenges = [
        Challenge(name=str(c.get("Name") or ""), progress=_int(c.get("Progress")))
        for c in _rows(r.get("ChallengeProgress"))
    ]

    loi = _dict(r.get("LoadOutInventory"))

    def first_type(key: str) -> str | None:
        lst = _rows(loi.get(key))
        return lst[0].get("ItemType") if lst else None

    loadout = Loadout(
        focus_school=_dict(r.get("LoadOutPreset")).get("FocusSchool"),
        warframe=first_type("Suits"),
        primary=first_type("LongGuns"),
        secondary=first_type("Pistols"),
        melee=first_type("Melee"),
    )

    stats = dict(_dict(data.get("Stats")))
    progression = Progression(
        mastery_rank=_int(r.get("PlayerLevel")),
        mastery_xp_from_items=sum(i.mastery_xp for i in items),
        play_time_s=stats.get("TimePlayedSec"),
        missions_completed=stats.get("MissionsCompleted"),
        items=items,
        nodes=nodes,
        affiliations=affiliations,
        daily_affiliations=daily,
        intrinsics={k: _int(v) for k, v in _dict(r.get("PlayerSkills")).items() if v is not None},
        challenges=challenges,
        loadout=loadout,
    )
    raw_id = r.get("AccountId")
    account_id = _dict(raw_id).get("$oid") if isinstance(raw_id, dict) else raw_id
    name = r.get("DisplayName")
    identity = Identity(
        display_name=clean_display_name(name) if isinstance(name, str) else None,
        account_id=account_id if isinstance(account_id, str) else None,
        platform=platform,
        clan=r.get("GuildName") if isinstance(r.get("GuildName"), str) else None,
        clan_tier=_int(r.get("GuildTier"), None) if r.get("GuildTier") is not None else None,
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
