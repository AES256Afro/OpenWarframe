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
    """Mastery XP we can see. Star chart and junction XP are not in the profile, so the
    estimate is a floor, not the account's true total."""

    rank: int
    rank_threshold: int  # total mastery XP the current rank requires (2500 * r^2)
    next_rank_threshold: int
    from_items: int
    from_intrinsics: int
    visible_total: int
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
