"""Pydantic models for the report. ``Report.model_json_schema()`` is the published
schema for ``account.json`` (docs/schema/account.schema.json)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

REPORT_SCHEMA = "openwarframe.account/1"


class SourceStamp(BaseModel):
    source: str
    version: str
    fetched_at: str


class MasteryEstimate(BaseModel):
    """Mastery XP from items and intrinsics (``visible_total``), plus an estimated total
    that adds star chart, Steel Path and junction mastery from completed nodes. The
    profile does not report node mastery, so ``estimated_total`` is an approximation."""

    rank: int
    rank_threshold: int  # total mastery the current rank requires (2,500 x r² to 30, then +147,500 a rank)
    next_rank_threshold: int
    from_items: int
    from_intrinsics: int
    visible_total: int  # items + intrinsics
    from_starchart: int = 0  # estimate: completed nodes x average node mastery
    from_steel_path: int = 0  # estimate: same, for Steel Path completions
    from_junctions: int = 0  # 1000 per junction, normal and Steel Path
    junctions_done: int = 0  # junctions cleared on the normal star chart
    steel_path_junctions_done: int = 0  # junctions cleared on the Steel Path
    estimated_total: int = 0  # visible_total + star chart + Steel Path + junctions
    note: str


class CategoryRow(BaseModel):
    category: str
    mastered: int
    leveling: int
    missing: int
    total: int  # mastery-eligible items in the game
    percent_mastered: float


class OwnedItem(BaseModel):
    unique_name: str
    name: str
    category: str
    rank: int
    xp: int
    mastery_xp: int
    mastered: bool
    xp_to_30: int  # affinity still needed to reach rank 30 (0 when mastered)


class SourceRow(BaseModel):
    kind: str  # relic | node | enemy | bounty | transient | vendor | syndicate
    where: str
    detail: str
    farmable: bool | None = None  # relics: drops somewhere right now


class ComponentRow(BaseModel):
    unique_name: str
    name: str
    count: int
    sources: list[SourceRow] = Field(default_factory=list)


# How a missing item can be obtained, as fixed codes. The display text ("acquisition") is built
# from these codes, and every decision (routing, priorities, access) reads the codes, so
# rewording a label can never change behaviour.
WAYS = {
    "vendor": "Vendor / standing",
    "relic_farmable": "Relics (farmable now)",
    "relic_vaulted": "Relics (vaulted)",
    "mission": "Mission drops",
    "bounty": "Bounties",
    "enemy": "Enemy drops",
    "trade": "Trade",
    "market_dojo_quest": "Market / dojo / quest (no drop data)",
    "unknown": "Not in drop data",
}
DROPS = ("mission", "bounty", "enemy")


def ways_label(ways: list[str]) -> str:
    return " + ".join(WAYS[w] for w in ways if w in WAYS)


class MissingItem(BaseModel):
    unique_name: str
    name: str
    category: str
    mastery_req: int
    above_your_mr: bool
    acquisition: str  # one-line summary: "Relics (farmable)", "Vendor", "Market only"...
    tradeable: bool
    market_slug: str | None = None
    blueprint_sources: list[SourceRow] = Field(default_factory=list)
    components: list[ComponentRow] = Field(default_factory=list)
    wiki_url: str
    owned: bool | None = None  # from the inventory: you have it but never leveled it (None: unknown)
    ways: list[str] = Field(default_factory=list)  # codes from WAYS; see kinds()

    def kinds(self) -> list[str]:
        """The acquisition codes. Reports from before the codes existed (or items built by
        hand) only have the text, so the codes are read back from it."""
        if self.ways:
            return list(self.ways)
        text = self.acquisition.split(": level it (", 1)[-1].rstrip(")")
        return [code for code, label in WAYS.items() if label in text]

    def has(self, *codes: str) -> bool:
        return any(c in self.kinds() for c in codes)

    def priority(self) -> int:
        """Cheapest way first: 0 farmable relics, 1 vendors, 2 drops, 3 anything else."""
        return 0 if self.has("relic_farmable") else 1 if self.has("vendor") else 2 if self.has(*DROPS) else 3

    def hard_to_get(self) -> bool:
        """Vaulted, trade-only, or with no drop source at all."""
        return self.has("relic_vaulted") or self.kinds()[:1] in (
            ["trade"],
            ["market_dojo_quest"],
            ["unknown"],
        )


class NodeRow(BaseModel):
    node: str
    name: str
    planet: str
    mission_type: str | None = None
    faction: str | None = None
    level: str | None = None
    completes: int
    completed: bool
    steel_path: bool


class SyndicateRow(BaseModel):
    tag: str
    name: str
    rank: int
    standing: int
    max_rank: int = 5  # from the codex: Necraloid tops out at 3, Nightwave seasons use 30


class AchievementRow(BaseModel):
    key: str
    name: str
    description: str | None = None
    progress: int


class IntrinsicRow(BaseModel):
    key: str
    name: str
    value: int


class UsageRow(BaseModel):
    unique_name: str
    name: str
    kills: int
    headshots: int
    equip_hours: float
    xp: int


class Identity(BaseModel):
    display_name: str | None = None
    platform: str
    clan: str | None = None
    created_at: datetime | None = None
    anonymized: bool = False


class Headline(BaseModel):
    mastery_rank: int
    account_age_days: int | None = None
    play_time_hours: float | None = None
    missions_completed: int | None = None
    items_mastered: int
    items_leveling: int
    items_missing: int
    items_total: int
    starchart_done: int
    starchart_total: int
    steel_path_done: int
    syndicates_maxed: int
    achievements_tracked: int


class Report(BaseModel):
    schema_version: str = REPORT_SCHEMA
    generated_at: datetime
    snapshot_taken_at: datetime
    coverage: list[str]
    identity: Identity
    headline: Headline
    mastery: MasteryEstimate
    categories: list[CategoryRow]
    owned: list[OwnedItem]
    missing: list[MissingItem]
    nodes: list[NodeRow]
    syndicates: list[SyndicateRow]
    achievements: list[AchievementRow]
    intrinsics: list[IntrinsicRow]
    usage: list[UsageRow]
    sources: list[SourceStamp]
    notes: list[str] = Field(default_factory=list)
