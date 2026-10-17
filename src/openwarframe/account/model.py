"""The snapshot model: everything we know about an account at one point in time.

A snapshot is built from whichever sources are available (profile now, inventory in
M3). ``coverage`` says which sections are present so every consumer can degrade
gracefully.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

SCHEMA = "openwarframe.snapshot/1"

# Categories that level like a Warframe (1000·r² affinity, 200 mastery per rank);
# everything else levels at 500·r² for 100 mastery per rank.
SUIT_CATEGORIES = {"Warframe", "Archwing", "Necramech", "Companion", "K-Drive"}


class ItemXP(BaseModel):
    item: str  # uniqueName
    name: str
    category: str
    xp: int
    rank: int
    mastery_xp: int
    mastered: bool  # rank >= 30


class NodeProgress(BaseModel):
    node: str  # SolNode94
    name: str
    planet: str
    completes: int
    steel_path: bool = False


class Affiliation(BaseModel):
    tag: str
    name: str
    standing: int
    title: int  # rank, negative for enemies


class Challenge(BaseModel):
    name: str
    progress: int


class Loadout(BaseModel):
    focus_school: str | None = None
    warframe: str | None = None
    primary: str | None = None
    secondary: str | None = None
    melee: str | None = None


class Identity(BaseModel):
    display_name: str | None = None
    account_id: str | None = None
    platform: str = "pc"
    clan: str | None = None
    clan_tier: int | None = None
    created_at: datetime | None = None


class Progression(BaseModel):
    mastery_rank: int
    mastery_xp_from_items: int = 0  # estimate: sum of item mastery
    play_time_s: float | None = None
    missions_completed: int | None = None
    items: list[ItemXP] = Field(default_factory=list)
    nodes: list[NodeProgress] = Field(default_factory=list)
    affiliations: list[Affiliation] = Field(default_factory=list)
    daily_affiliations: dict[str, int] = Field(default_factory=dict)
    intrinsics: dict[str, int] = Field(default_factory=dict)
    challenges: list[Challenge] = Field(default_factory=list)
    loadout: Loadout = Field(default_factory=Loadout)
    quests_completed: list[str] = Field(default_factory=list)  # inventory only (M3)


class SourceInfo(BaseModel):
    kind: str  # profile | inventory
    fetched_at: datetime
    detail: str = ""


class Snapshot(BaseModel):
    schema_version: str = SCHEMA
    taken_at: datetime
    sources: list[SourceInfo] = Field(default_factory=list)
    coverage: list[str] = Field(default_factory=list)  # progression, stats, loadout, inventory...
    identity: Identity = Field(default_factory=Identity)
    progression: Progression
    stats: dict = Field(default_factory=dict)  # lifetime stats, raw
    raw: dict = Field(default_factory=dict)  # verbatim source payloads by kind

    # -- convenience ------------------------------------------------------------------
    def mastered(self) -> list[ItemXP]:
        return [i for i in self.progression.items if i.mastered]

    def unmastered(self) -> list[ItemXP]:
        return [i for i in self.progression.items if not i.mastered]

    def items_by_category(self) -> dict[str, list[ItemXP]]:
        out: dict[str, list[ItemXP]] = {}
        for it in self.progression.items:
            out.setdefault(it.category, []).append(it)
        return out

    def anonymized(self) -> Snapshot:
        """Copy with identity, clan and raw payloads stripped (share mode)."""
        copy = self.model_copy(deep=True)
        copy.identity = Identity(platform=self.identity.platform)
        copy.raw = {}
        copy.stats.pop("GuildName", None)
        return copy
