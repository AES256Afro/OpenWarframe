"""The mastery planner: from a report to a rank-by-rank plan to Mastery Rank 30.

Everything here is a pure function of a :class:`~openwarframe.report.model.Report`
and the knowledge base, so it is easy to test with small fixtures.

The plan works on *units*: one item to level, one intrinsic rank to buy, a block of
Steel Path nodes, a Forma upgrade on a rank 40 weapon. Units are queued by route
(``kb/mastery/routes.yaml`` ``order``) and handed out rank by rank until each rank's
mastery gap is filled.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from ..account.model import SUIT_CATEGORIES
from ..account.parse import MAX_RANK, max_rank
from ..report.build import STARCHART_MASTERY_NODES, STARCHART_MASTERY_TOTAL, rank_threshold
from ..report.model import Report
from .kb import MasteryKB

TARGET_RANK = 30
INTRINSIC_MASTERY = 1500
JUNCTIONS = 13
JUNCTION_MASTERY = 1000
INTRINSIC_POINT = 1000  # pools are stored in thousandths of a point

# Cost in points of raising a school from rank r to r + 1 (index r).
DRIFTER_COSTS = (20, 25, 30, 45, 65, 90, 125, 160, 205, 255)
INTRINSIC_MAX = 10

RAILJACK_SCHOOLS = {
    "LPS_TACTICAL": "Tactical",
    "LPS_PILOTING": "Piloting",
    "LPS_GUNNERY": "Gunnery",
    "LPS_ENGINEERING": "Engineering",
    "LPS_COMMAND": "Command",
}
DRIFTER_SCHOOLS = {
    "LPS_DRIFT_COMBAT": "Combat",
    "LPS_DRIFT_RIDING": "Riding",
    "LPS_DRIFT_OPPORTUNITY": "Opportunity",
    "LPS_DRIFT_ENDURANCE": "Endurance",
}

# Vendor manifests whose shop belongs to a syndicate the profile tracks.
VENDOR_SYNDICATE = {
    "HexScaldranWeaponsVendor": "The Hex",
}

RANK_TITLES = {
    24: "Gold Dragon",
    25: "Sage",
    26: "Silver Sage",
    27: "Gold Sage",
    28: "Master",
    29: "Middle Master",
    30: "True Master",
}

ARCHWING_CATEGORIES = {"Archwing", "Archgun", "Archmelee"}


# -- intrinsic math ------------------------------------------------------------------


def drifter_cost(rank: int) -> int:
    """Points to raise a Drifter school from ``rank`` to ``rank + 1``."""
    return DRIFTER_COSTS[rank]


def railjack_cost(rank: int) -> int:
    """Points to raise a Railjack school from ``rank`` to ``rank + 1`` (2^rank)."""
    return 1 << rank


@dataclass(frozen=True)
class IntrinsicStep:
    tree: str  # Drifter | Railjack
    school: str
    from_rank: int
    cost: int

    @property
    def label(self) -> str:
        return f"{self.tree} {self.school} {self.from_rank} to {self.from_rank + 1}"


def intrinsic_steps(tree: str, ranks: dict[str, int]) -> list[IntrinsicStep]:
    """Every remaining rank in a tree, cheapest first (ties broken by school name)."""
    cost = drifter_cost if tree == "Drifter" else railjack_cost
    steps = [
        IntrinsicStep(tree, school, r, cost(r))
        for school, start in ranks.items()
        for r in range(start, INTRINSIC_MAX)
    ]
    return sorted(steps, key=lambda s: (s.cost, s.from_rank, s.school))


def spend_points(tree: str, ranks: dict[str, int], points: int) -> tuple[list[IntrinsicStep], int]:
    """Spend ``points`` greedily on the cheapest next rank of any school.

    Returns the ranks bought (in order) and the points left over. Each school's ranks
    must be bought in order, so only a school's next rank is ever a candidate.
    """
    cost = drifter_cost if tree == "Drifter" else railjack_cost
    current = dict(ranks)
    bought: list[IntrinsicStep] = []
    while True:
        options = [
            IntrinsicStep(tree, school, r, cost(r)) for school, r in current.items() if r < INTRINSIC_MAX
        ]
        options = [o for o in options if o.cost <= points]
        if not options:
            return bought, points
        pick = min(options, key=lambda s: (s.cost, s.from_rank, s.school))
        bought.append(pick)
        points -= pick.cost
        current[pick.school] += 1


def tree_ranks(intrinsics: dict[str, int], schools: dict[str, str]) -> dict[str, int]:
    return {name: int(intrinsics.get(key, 0)) for key, name in schools.items()}


# -- plan model ----------------------------------------------------------------------


class Unit(BaseModel):
    route: str
    label: str
    mastery: int
    category: str | None = None
    mastery_req: int = 0
    detail: str | None = None


class RankRow(BaseModel):
    rank: int
    title: str
    threshold: int
    to_earn: int  # from the previous rank's threshold, or from the estimate for the next rank
    test: str


class TonightItem(BaseModel):
    id: str
    title: str
    detail: str
    gain: int | None = None
    gain_label: str


class PhaseStep(BaseModel):
    route: str
    title: str
    mastery: int
    count: int
    items: list[str]


class Phase(BaseModel):
    from_rank: int
    to_rank: int
    need: int
    planned: int
    title: str
    blurb: str
    steps: list[PhaseStep]
    tired: str
    too_hard: str
    done: str
    test: str
    already_there: bool = False


class MoodCard(BaseModel):
    id: str
    name: str
    moods: list[str]
    mood_labels: list[str]
    where: str
    levels: str
    too_hard: str
    tired: str


class BudgetRow(BaseModel):
    route: str
    label: str
    mastery: int
    count: int
    trade: bool = False


class TestCard(BaseModel):
    rank: int
    title: str
    name: str
    objective: str
    tips: list[str]
    bring: str
    owned_picks: list[str] = Field(default_factory=list)


class Tip(BaseModel):
    title: str
    text: str


class MasteryPlan(BaseModel):
    generated_at: datetime
    snapshot_taken_at: datetime
    display_name: str | None
    platform: str
    rank: int
    estimate: int
    estimate_parts: dict[str, int]
    estimate_note: str
    needed_to_target: int
    target_rank: int = TARGET_RANK
    ranks: list[RankRow]
    tonight: list[TonightItem]
    phases: list[Phase]
    moods: dict[str, str]
    mood_cards: list[MoodCard]
    budget: list[BudgetRow]
    budget_without_trade: int
    tests: list[TestCard]
    test_rules: list[str]
    tips: list[Tip]
    facts: dict[str, int]
    sources: list[dict]
    notes: list[str] = Field(default_factory=list)


# -- building blocks -------------------------------------------------------------------


def item_value(name: str, category: str) -> int:
    """Mastery an item is worth at its highest rank."""
    suit = category in SUIT_CATEGORIES
    return max_rank(name, category) * (200 if suit else 100)


def _per_rank(category: str) -> int:
    return 200 if category in SUIT_CATEGORIES else 100


def _owned_syndicate_ranks(report: Report) -> dict[str, int]:
    return {s.name.lower().removeprefix("the "): s.rank for s in report.syndicates}


def _vendor_rank(where: str, ranks: dict[str, int]) -> int | None:
    name = VENDOR_SYNDICATE.get(where, where).lower().removeprefix("the ")
    return ranks.get(name)


def classify_missing(report: Report) -> list[Unit]:
    """One unit per never-leveled item, routed by how it is obtained."""
    ranks = _owned_syndicate_ranks(report)
    units: list[Unit] = []
    for m in report.missing:
        acq = m.acquisition
        value = item_value(m.name, m.category)
        sources = list(m.blueprint_sources) + [s for c in m.components for s in c.sources]
        vendor_ranks = [
            r
            for s in sources
            if s.kind in ("vendor", "syndicate")
            for r in [_vendor_rank(s.where, ranks)]
            if r is not None
        ]
        vendor_names = sorted(
            {VENDOR_SYNDICATE.get(s.where, s.where) for s in sources if s.kind in ("vendor", "syndicate")}
        )
        if max_rank(m.name, m.category) > MAX_RANK:
            route = "extended"
        elif "Vendor / standing" in acq and any(r >= 1 for r in vendor_ranks):
            route = "standing_owned"
        elif "Relics (farmable now)" in acq:
            route = "relics_farmable"
        elif any(k in acq for k in ("Mission drops", "Enemy drops", "Bounties")):
            route = "drops"
        elif acq.startswith("Market"):
            route = "market"
        elif "Vendor / standing" in acq:
            route = "standing_other"
        elif "Trade" in acq or "Relics (vaulted)" in acq:
            route = "trade"
        else:
            route = "other"
        detail = ", ".join(vendor_names[:2]) if route in ("standing_owned", "standing_other") else None
        units.append(
            Unit(
                route=route,
                label=m.name,
                mastery=value,
                category=m.category,
                mastery_req=m.mastery_req,
                detail=detail,
            )
        )
    return units


def partial_units(report: Report) -> list[Unit]:
    """Owned items below rank 30, and Forma headroom on rank 40 items."""
    units: list[Unit] = []
    for o in sorted(report.owned, key=lambda o: o.xp_to_30):
        per = _per_rank(o.category)
        cap = max_rank(o.name, o.category)
        if o.rank < MAX_RANK:
            units.append(
                Unit(route="partial", label=o.name, mastery=(MAX_RANK - o.rank) * per, category=o.category)
            )
        if cap > MAX_RANK and o.rank < cap:
            units.append(
                Unit(
                    route="extended",
                    label=f"{o.name} (Forma to 40)",
                    mastery=(cap - max(o.rank, MAX_RANK)) * per,
                    category=o.category,
                )
            )
    # Forma upgrades on items you own come before buying new rank 40 weapons
    return units


def intrinsic_units(report: Report) -> list[Unit]:
    """Intrinsic ranks as units.

    Ranks the banked points already pay for go to the ``intrinsics`` route (do them
    first); every other rank needs new points from play and goes to
    ``intrinsics_grind``, cheapest first across both trees.
    """
    values = {i.key: i.value for i in report.intrinsics}
    now: list[Unit] = []
    later: list[tuple[int, Unit]] = []
    pools = {"Drifter": "LPP_DRIFTER", "Railjack": "LPP_SPACE"}
    for tree, schools in (("Drifter", DRIFTER_SCHOOLS), ("Railjack", RAILJACK_SCHOOLS)):
        ranks = tree_ranks(values, schools)
        bought, _ = spend_points(tree, ranks, values.get(pools[tree], 0) // INTRINSIC_POINT)
        for step in bought:
            now.append(
                Unit(
                    route="intrinsics",
                    label=step.label,
                    mastery=INTRINSIC_MASTERY,
                    detail=f"{step.cost} points",
                )
            )
        after = dict(ranks)
        for step in bought:
            after[step.school] += 1
        for step in intrinsic_steps(tree, after):
            unit = Unit(
                route="intrinsics_grind",
                label=step.label,
                mastery=INTRINSIC_MASTERY,
                detail=f"{step.cost} points",
            )
            later.append((step.cost, unit))
    later.sort(key=lambda cu: cu[0])
    return now + [u for _, u in later]


def steel_path_units(report: Report, block: int = 20) -> list[Unit]:
    done = min(report.headline.steel_path_done, STARCHART_MASTERY_NODES)
    left = STARCHART_MASTERY_NODES - done
    units: list[Unit] = []
    per_node = STARCHART_MASTERY_TOTAL / STARCHART_MASTERY_NODES
    while left > 0:
        n = min(block, left)
        units.append(Unit(route="steel_path", label=f"{n} Steel Path nodes", mastery=round(n * per_node)))
        left -= n
    # 13 junctions, each worth 1,000 once normally and once on the Steel Path
    cleared = report.mastery.from_junctions // JUNCTION_MASTERY
    for _ in range(max(0, 2 * JUNCTIONS - cleared)):
        units.append(Unit(route="steel_path", label="Junction (Steel Path)", mastery=JUNCTION_MASTERY))
    return units


def build_queue(report: Report, kb: MasteryKB) -> list[Unit]:
    by_route: dict[str, list[Unit]] = defaultdict(list)
    for u in (
        partial_units(report) + intrinsic_units(report) + steel_path_units(report) + classify_missing(report)
    ):
        by_route[u.route].append(u)
    for route, units in by_route.items():
        if route in ("partial", "intrinsics", "intrinsics_grind", "steel_path"):
            continue  # already in a meaningful order
        if route == "extended":
            # Forma on owned items first, then new items; within each, biggest first
            units.sort(key=lambda u: (not u.label.endswith("(Forma to 40)"), -u.mastery, u.label))
        else:
            units.sort(key=lambda u: (-u.mastery, u.mastery_req, u.label))
    return [u for route in kb.route_order for u in by_route.get(route, [])]


def allocate(
    queue: list[Unit], estimate: int, current_rank: int, target: int = TARGET_RANK
) -> list[tuple[int, int, list[Unit], int]]:
    """Hand units to ranks in queue order until each rank's threshold is met.

    Returns ``(rank, need, units, total_after)`` per rank from ``current_rank + 1`` to
    ``target``. Units whose mastery requirement is above the rank being worked toward
    wait in place until that rank is reached.
    """
    remaining = list(queue)
    total = estimate
    out = []
    for rank in range(current_rank + 1, target + 1):
        need = max(0, rank_threshold(rank) - total)
        taken: list[Unit] = []
        gained = 0
        i = 0
        while gained < need and i < len(remaining):
            u = remaining[i]
            if u.mastery_req <= rank - 1:
                taken.append(remaining.pop(i))
                gained += u.mastery
            else:
                i += 1
        total += gained
        out.append((rank, need, taken, total))
    return out


def _owned_names(report: Report) -> set[str]:
    return {o.name for o in report.owned}


def _picks(candidates: list[dict], owned: set[str]) -> list[tuple[str, str]]:
    """(owned display name, why) for candidates the account has leveled, Prime first."""
    out: list[tuple[str, str]] = []
    for c in candidates or []:
        base = c["name"]
        hits = sorted(
            (n for n in owned if n == base or n.startswith(base + " ")), key=lambda n: (" Prime" not in n, n)
        )
        if hits:
            out.append((hits[0], c["why"]))
    return out


def build_test_card(test: dict, owned: set[str]) -> TestCard:
    frames = _picks(test.get("recommend", []), owned)
    pets = _picks(test.get("companions", []), owned)
    if frames:
        first, why = frames[0]
        bring = f"{first}: {why}."
        others = [n for n, _ in frames[1:5]]
        if others:
            bring += f" Also leveled on your account: {', '.join(others)}."
    else:
        bring = test["bring_default"]
        if test.get("recommend"):
            bring += (
                " Good picks you have not leveled: "
                + ", ".join(c["name"] for c in test["recommend"][:3])
                + "."
            )
    if pets:
        bring += f" Companion: {pets[0][0]} ({pets[0][1]})."
    return TestCard(
        rank=test["rank"],
        title=test["title"],
        name=test["name"],
        objective=" ".join(test["objective"].split()),
        tips=list(test.get("tips", [])),
        bring=bring,
        owned_picks=[n for n, _ in frames + pets],
    )


def _names(units: list[Unit], limit: int) -> list[str]:
    names = [u.label for u in units[:limit]]
    if len(units) > limit:
        names.append(f"and {len(units) - limit} more")
    return names


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _fmt(text: str, ctx: dict) -> str:
    return " ".join(str(text).split()).format_map(_SafeDict(ctx))


# -- the planner ---------------------------------------------------------------------


def build_mastery_plan(report: Report, kb: MasteryKB, *, now: datetime | None = None) -> MasteryPlan:
    m = report.mastery
    rank = m.rank
    estimate = m.estimated_total
    owned = _owned_names(report)
    queue = build_queue(report, kb)

    # -- rank table ---------------------------------------------------------------------
    ranks: list[RankRow] = []
    for r in range(rank + 1, TARGET_RANK + 1):
        test = kb.test_for(r) or {}
        prev = rank_threshold(r - 1)
        to_earn = rank_threshold(r) - (max(estimate, prev) if r == rank + 1 else prev)
        ranks.append(
            RankRow(
                rank=r,
                title=RANK_TITLES.get(r, test.get("title", "")),
                threshold=rank_threshold(r),
                to_earn=max(0, to_earn),
                test=test.get("name", "Mastery test"),
            )
        )

    # -- facts used in text ---------------------------------------------------------------
    values = {i.key: i.value for i in report.intrinsics}
    drifter = tree_ranks(values, DRIFTER_SCHOOLS)
    railjack = tree_ranks(values, RAILJACK_SCHOOLS)
    drifter_pts = values.get("LPP_DRIFTER", 0) // INTRINSIC_POINT
    railjack_pts = values.get("LPP_SPACE", 0) // INTRINSIC_POINT
    drifter_buy, drifter_left_pts = spend_points("Drifter", drifter, drifter_pts)
    railjack_buy, railjack_left_pts = spend_points("Railjack", railjack, railjack_pts)
    drifter_ranks_left = sum(INTRINSIC_MAX - r for r in drifter.values()) - len(drifter_buy)
    railjack_ranks_left = sum(INTRINSIC_MAX - r for r in railjack.values()) - len(railjack_buy)
    partials = [u for u in queue if u.route == "partial"]
    arch = [u for u in partials if u.category in ARCHWING_CATEGORIES]
    extended_missing = sum(
        1 for u in queue if u.route == "extended" and not u.label.endswith("(Forma to 40)")
    )
    sp_left = max(0, STARCHART_MASTERY_NODES - report.headline.steel_path_done)
    mastered_frames = sum(1 for o in report.owned if o.category == "Warframe" and o.mastered)
    facts = {
        "mastered_frames": mastered_frames,
        "mastered_items": sum(1 for o in report.owned if o.mastered),
        "drifter_points": drifter_pts,
        "railjack_points": railjack_pts,
        "drifter_ranks_left": drifter_ranks_left,
        "railjack_ranks_left": railjack_ranks_left,
        "archwing_partials": len(arch),
        "archwing_mastery": sum(u.mastery for u in arch),
        "steel_path_left": sp_left,
        "extended_missing": extended_missing,
    }
    ctx = dict(facts)
    ctx.update(
        drifter_mastery_left=f"{drifter_ranks_left * INTRINSIC_MASTERY:,}",
        railjack_mastery_left=f"{railjack_ranks_left * INTRINSIC_MASTERY:,}",
        archwing_mastery=f"{facts['archwing_mastery']:,}",
    )

    # -- tonight ------------------------------------------------------------------------
    tonight: list[TonightItem] = []
    if drifter_buy:
        steps = "; ".join(f"{s.school} {s.from_rank} to {s.from_rank + 1} ({s.cost})" for s in drifter_buy)
        tonight.append(
            TonightItem(
                id="drifter",
                title=f"Spend your {drifter_pts} unspent Drifter intrinsic points",
                detail=f"Profile, Intrinsics, Drifter tab. {steps}. That is {len(drifter_buy)} ranks"
                + (f", with {drifter_left_pts} points left over." if drifter_left_pts else "."),
                gain=len(drifter_buy) * INTRINSIC_MASTERY,
                gain_label=f"+{len(drifter_buy) * INTRINSIC_MASTERY:,}",
            )
        )
    if railjack_buy:
        steps = "; ".join(f"{s.school} {s.from_rank} to {s.from_rank + 1} ({s.cost})" for s in railjack_buy)
        tonight.append(
            TonightItem(
                id="railjack",
                title=f"Spend your {railjack_pts} unspent Railjack intrinsic points",
                detail=f"Profile, Intrinsics, Railjack tab. {steps}.",
                gain=len(railjack_buy) * INTRINSIC_MASTERY,
                gain_label=f"+{len(railjack_buy) * INTRINSIC_MASTERY:,}",
            )
        )
    elif railjack_ranks_left:
        nxt = intrinsic_steps("Railjack", railjack)[0]
        tonight.append(
            TonightItem(
                id="railjack",
                title=f"Run one Railjack mission, then rank {nxt.school} to {nxt.from_rank + 1}",
                detail=f"You hold {railjack_pts} Railjack points and the cheapest next rank costs {nxt.cost}.",
                gain=INTRINSIC_MASTERY,
                gain_label=f"+{INTRINSIC_MASTERY:,}",
            )
        )
    close = [o for o in report.owned if not o.mastered and o.rank < MAX_RANK and o.xp_to_30 <= 15_000]
    close.sort(key=lambda o: o.xp_to_30)
    if close:
        gain = sum((MAX_RANK - o.rank) * _per_rank(o.category) for o in close[:4])
        tonight.append(
            TonightItem(
                id="close",
                title="Finish " + ", ".join(o.name for o in close[:4]),
                detail="Affinity still needed: "
                + ", ".join(f"{o.name} {o.xp_to_30:,}" for o in close[:4])
                + ". One mission each.",
                gain=gain,
                gain_label=f"+{gain:,}",
            )
        )
    tonight.append(
        TonightItem(
            id="slots",
            title="Sell mastered duplicates to open weapon and frame slots",
            detail=f"You have {facts['mastered_items']} items at rank 30. Mastery stays when you sell. Keep favourites, sell the rest.",
            gain=None,
            gain_label="slots",
        )
    )
    shop = [u for u in queue if u.route == "standing_owned"][:9]
    if shop:
        gain = sum(u.mastery for u in shop)
        tonight.append(
            TonightItem(
                id="shop",
                title=f"Buy {len(shop)} blueprints with standing you already have",
                detail=", ".join(f"{u.label} ({u.detail})" if u.detail else u.label for u in shop)
                + ". Some also need resources. Build them while you sleep.",
                gain=gain,
                gain_label=f"+{gain:,}",
            )
        )
    tonight.append(
        TonightItem(
            id="check",
            title=f"Open Profile in game and compare your bar with about {estimate:,}",
            detail="This page estimates star chart and Steel Path mastery. If the game shows more, you are closer than this page says.",
            gain=None,
            gain_label="check",
        )
    )

    # -- phases -------------------------------------------------------------------------
    phases: list[Phase] = []
    for r, need, units, _total in allocate(queue, estimate, rank):
        test = kb.test_for(r) or {"name": "Mastery test"}
        by_route: dict[str, list[Unit]] = defaultdict(list)
        for u in units:
            by_route[u.route].append(u)
        steps = [
            PhaseStep(
                route=route,
                title=kb.route(route)["title"],
                mastery=sum(u.mastery for u in us),
                count=len(us),
                items=_names(us, 16),
            )
            for route in kb.route_order
            if (us := by_route.get(route))
        ]
        lead = max(steps, key=lambda s: s.mastery).route if steps else "partial"
        info = kb.route(lead)
        phases.append(
            Phase(
                from_rank=r - 1,
                to_rank=r,
                need=need,
                planned=sum(s.mastery for s in steps),
                title=info["title"],
                blurb=_fmt(info["blurb"], ctx),
                steps=steps,
                tired=_fmt(info["tired"], ctx),
                too_hard=_fmt(info["too_hard"], ctx),
                done=f"At {rank_threshold(r):,}, take the {test['name'].removesuffix(' Test')} test.",
                test=test["name"],
                already_there=need == 0,
            )
        )

    # -- moods, budget, tests ------------------------------------------------------------
    mood_names = dict(kb.farms.get("moods", {}))
    mood_cards = [
        MoodCard(
            id=f["id"],
            name=f["name"],
            moods=list(f["moods"]),
            mood_labels=[mood_names.get(x, x) for x in f["moods"]],
            where=_fmt(f["where"], ctx),
            levels=_fmt(f["levels"], ctx),
            too_hard=_fmt(f["too_hard"], ctx),
            tired=_fmt(f["tired"], ctx),
        )
        for f in kb.farms.get("farms", [])
    ]
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for u in queue:
        totals[u.route][0] += u.mastery
        totals[u.route][1] += 1
    budget = [
        BudgetRow(route=r, label=kb.route(r)["title"], mastery=t[0], count=t[1], trade=r == "trade")
        for r in kb.route_order
        if (t := totals.get(r)) and t[0] > 0
    ]
    budget.sort(key=lambda b: (b.trade, -b.mastery))
    tests = [build_test_card(t, owned) for r in range(rank + 1, TARGET_RANK + 1) if (t := kb.test_for(r))]

    notes = list(report.notes)
    if report.identity.anonymized:
        notes.append("Share mode: display name and clan removed.")
    return MasteryPlan(
        generated_at=now or datetime.now(UTC),
        snapshot_taken_at=report.snapshot_taken_at,
        display_name=report.identity.display_name,
        platform=report.identity.platform,
        rank=rank,
        estimate=estimate,
        estimate_parts={
            "items": m.from_items,
            "intrinsics": m.from_intrinsics,
            "star_chart": m.from_starchart,
            "steel_path": m.from_steel_path,
            "junctions": m.from_junctions,
        },
        estimate_note=m.note,
        needed_to_target=max(0, rank_threshold(TARGET_RANK) - estimate),
        ranks=ranks,
        tonight=tonight,
        phases=phases,
        moods=mood_names,
        mood_cards=mood_cards,
        budget=budget,
        budget_without_trade=sum(b.mastery for b in budget if not b.trade),
        tests=tests,
        test_rules=list(kb.tests.get("rules", [])),
        tips=[Tip(title=t["title"], text=" ".join(t["text"].split())) for t in kb.routes.get("tips", [])],
        facts=facts,
        sources=kb.sources(),
        notes=notes,
    )
