"""Planner math and the mastery guide, on a small synthetic report. No network."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwarframe.guide import build_mastery_plan, load_kb, render_mastery_html
from openwarframe.guide.mastery import (
    DRIFTER_COSTS,
    Unit,
    allocate,
    build_test_card,
    drifter_cost,
    intrinsic_steps,
    intrinsic_units,
    item_value,
    partial_units,
    railjack_cost,
    spend_points,
)
from openwarframe.report.build import rank_threshold
from openwarframe.report.model import (
    Headline,
    Identity,
    IntrinsicRow,
    MasteryEstimate,
    MissingItem,
    OwnedItem,
    Report,
    SourceRow,
    SyndicateRow,
)

DRIFTER = {"Combat": 1, "Riding": 1, "Opportunity": 0, "Endurance": 0}
RAILJACK = {"Tactical": 7, "Piloting": 5, "Gunnery": 7, "Engineering": 5, "Command": 6}


# -- intrinsic math ------------------------------------------------------------------


def test_intrinsic_cost_tables():
    assert [drifter_cost(r) for r in range(10)] == list(DRIFTER_COSTS)
    assert sum(DRIFTER_COSTS) == 1020  # one Drifter school 0 -> 10
    assert [railjack_cost(r) for r in range(10)] == [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
    assert sum(railjack_cost(r) for r in range(10)) == 1023  # one Railjack school 0 -> 10


def test_spend_drifter_points_greedy_cheapest_first():
    bought, left = spend_points("Drifter", DRIFTER, 115)
    assert left == 0
    assert [(s.school, s.from_rank, s.cost) for s in bought] == [
        ("Endurance", 0, 20),
        ("Opportunity", 0, 20),
        ("Combat", 1, 25),
        ("Endurance", 1, 25),
        ("Opportunity", 1, 25),
    ]


def test_spend_railjack_points_when_nothing_is_affordable():
    bought, left = spend_points("Railjack", RAILJACK, 25)
    assert bought == [] and left == 25
    cheapest = intrinsic_steps("Railjack", RAILJACK)[0]
    assert (cheapest.school, cheapest.from_rank, cheapest.cost) == ("Engineering", 5, 32)


def test_spend_never_skips_a_rank_and_stops_at_ten():
    bought, left = spend_points("Railjack", {"Command": 9}, 10_000)
    assert [(s.from_rank, s.cost) for s in bought] == [(9, 512)]
    assert left == 10_000 - 512


def test_remaining_steps_cover_every_rank():
    steps = intrinsic_steps("Drifter", DRIFTER)
    assert len(steps) == 40 - 2  # four schools to 10, two ranks already owned
    assert sum(s.cost for s in steps) == 4 * 1020 - 2 * DRIFTER_COSTS[0]


# -- item values and allocation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "category", "value"),
    [
        ("Braton", "Primary", 3000),
        ("Kuva Zarr", "Primary", 4000),
        ("Tenet Envoy", "Primary", 4000),
        ("Paracesis", "Melee", 4000),
        ("Rhino", "Warframe", 6000),
        ("Runway", "K-Drive", 6000),
        ("Lambeo Moa", "Companion", 6000),
        ("Voidrig", "Necramech", 8000),
    ],
)
def test_item_value(name, category, value):
    assert item_value(name, category) == value


def test_allocate_fills_each_rank_and_carries_the_overshoot():
    start = rank_threshold(23) + 10_000  # 1,332,500
    queue = [Unit(route="partial", label=f"w{i}", mastery=3000) for i in range(100)]
    out = allocate(queue, start, 23, target=25)
    (r24, need24, taken24, total24), (r25, need25, taken25, total25) = out
    assert (r24, r25) == (24, 25)
    assert need24 == rank_threshold(24) - start  # 107,500
    assert len(taken24) == 36 and total24 == start + 36 * 3000  # 108,000 >= 107,500
    assert need25 == rank_threshold(25) - total24  # the 500 overshoot counts toward 25
    assert total25 >= rank_threshold(25)


def test_allocate_defers_items_above_the_rank_being_worked_toward():
    queue = [
        Unit(route="market", label="locked", mastery=50_000, mastery_req=25),
        Unit(route="market", label="open", mastery=50_000, mastery_req=0),
        Unit(route="market", label="open2", mastery=200_000, mastery_req=0),
    ]
    out = allocate(queue, rank_threshold(23), 23, target=26)
    assert [u.label for u in out[0][2]] == ["open", "open2"]  # rank 24: locked waits
    assert out[1][2] == []  # rank 25 already covered by the overshoot
    assert [u.label for u in out[2][2]] == ["locked"]  # usable while working toward 26


def test_allocate_reports_zero_need_when_already_there():
    out = allocate([], rank_threshold(25) + 1, 23, target=25)
    assert [need for _, need, _, _ in out] == [0, 0]


# -- report fixture ------------------------------------------------------------------------


def _owned(name, cat, rank, mastered=False, xp_to_30=100_000):
    per = 200 if cat in ("Warframe", "Necramech", "Companion", "Archwing", "K-Drive") else 100
    return OwnedItem(
        unique_name=f"/Test/{name.replace(' ', '')}",
        name=name,
        category=cat,
        rank=rank,
        xp=0,
        mastery_xp=rank * per,
        mastered=mastered,
        xp_to_30=0 if mastered else xp_to_30,
    )


def _missing(name, cat, acquisition, vendor=None, mr=0):
    sources = [SourceRow(kind="syndicate", where=vendor, detail="")] if vendor else []
    return MissingItem(
        unique_name=f"/Test/{name.replace(' ', '')}",
        name=name,
        category=cat,
        mastery_req=mr,
        above_your_mr=False,
        acquisition=acquisition,
        tradeable=False,
        blueprint_sources=sources,
        wiki_url="https://wiki.warframe.com/w/x",
    )


def _report() -> Report:
    owned = [
        _owned("Mag Prime", "Warframe", 30, mastered=True),
        _owned("Vauban Prime", "Warframe", 30, mastered=True),
        _owned("Carrier Prime", "Companion", 30, mastered=True),
        _owned("Mag", "Warframe", 29, xp_to_30=2_049),
        _owned("Lex", "Secondary", 29, xp_to_30=9_233),
        _owned("Odonata", "Archwing", 29, xp_to_30=42_758),
        _owned("Bonewidow", "Necramech", 13, xp_to_30=706_025),
        _owned("Kuva Nukor", "Secondary", 36, mastered=True),
    ]
    missing = [
        _missing("Vaykor Hek", "Primary", "Vendor / standing", vendor="Steel Meridian"),
        _missing("Telos Boltor", "Primary", "Vendor / standing", vendor="Arbiters of Hexis"),
        _missing("Nyx Prime", "Warframe", "Relics (farmable now)"),
        _missing("Braton", "Primary", "Market / dojo / quest (no drop data)"),
        _missing("Kuva Zarr", "Primary", "Market / dojo / quest (no drop data)", mr=15),
        _missing("Prisma Gorgon", "Primary", "Trade"),
    ]
    estimate = rank_threshold(23) + 61_000
    return Report(
        generated_at=datetime(2026, 10, 17, tzinfo=UTC),
        snapshot_taken_at=datetime(2026, 10, 16, 19, 40, tzinfo=UTC),
        coverage=["progression"],
        identity=Identity(display_name="Tester", platform="pc"),
        headline=Headline(
            mastery_rank=23,
            items_mastered=4,
            items_leveling=4,
            items_missing=len(missing),
            items_total=14,
            starchart_done=266,
            starchart_total=269,
            steel_path_done=102,
            syndicates_maxed=1,
            achievements_tracked=0,
        ),
        mastery=MasteryEstimate(
            rank=23,
            rank_threshold=rank_threshold(23),
            next_rank_threshold=rank_threshold(24),
            from_items=0,
            from_intrinsics=48_000,
            visible_total=0,
            from_junctions=18_000,  # 13 normal + 5 Steel Path
            estimated_total=estimate,
            note="test",
        ),
        categories=[],
        owned=owned,
        missing=missing,
        nodes=[],
        syndicates=[
            SyndicateRow(tag="SteelMeridianSyndicate", name="Steel Meridian", rank=5, standing=372_000),
            SyndicateRow(tag="ArbitersSyndicate", name="Arbiters of Hexis", rank=-2, standing=-69_095),
        ],
        achievements=[],
        intrinsics=[
            IntrinsicRow(key="LPP_DRIFTER", name="pool", value=115_000),
            IntrinsicRow(key="LPP_SPACE", name="pool", value=25_685),
            IntrinsicRow(key="LPS_DRIFT_COMBAT", name="c", value=1),
            IntrinsicRow(key="LPS_DRIFT_RIDING", name="r", value=1),
            IntrinsicRow(key="LPS_TACTICAL", name="t", value=7),
            IntrinsicRow(key="LPS_PILOTING", name="p", value=5),
            IntrinsicRow(key="LPS_GUNNERY", name="g", value=7),
            IntrinsicRow(key="LPS_ENGINEERING", name="e", value=5),
            IntrinsicRow(key="LPS_COMMAND", name="c", value=6),
        ],
        usage=[],
        sources=[],
    )


@pytest.fixture(scope="module")
def kb():
    return load_kb()


def test_partial_units_split_necramech_and_kuva_headroom():
    units = partial_units(_report())
    by_label = {u.label: (u.route, u.mastery) for u in units}
    assert by_label["Mag"] == ("partial", 200)
    assert by_label["Lex"] == ("partial", 100)
    assert by_label["Bonewidow"] == ("partial", 17 * 200)
    assert by_label["Bonewidow (Forma to 40)"] == ("extended", 10 * 200)
    assert by_label["Kuva Nukor (Forma to 40)"] == ("extended", 4 * 100)
    assert "Mag Prime" not in by_label  # mastered, nothing left


def test_intrinsic_units_put_banked_ranks_first():
    units = intrinsic_units(_report())
    now = [u for u in units if u.route == "intrinsics"]
    later = [u for u in units if u.route == "intrinsics_grind"]
    assert len(now) == 5  # 115 Drifter points buy five ranks, 25 Railjack points buy none
    assert len(later) == (40 - 2 - 5) + (50 - 30)
    costs = [int(u.detail.split()[0]) for u in later]
    assert costs == sorted(costs)


def test_plan_routes_tonight_and_tests(kb):
    plan = build_mastery_plan(_report(), kb)
    assert [r.rank for r in plan.ranks] == list(range(24, 31))
    assert plan.ranks[0].to_earn == rank_threshold(24) - plan.estimate
    assert plan.needed_to_target == rank_threshold(30) - plan.estimate

    tonight = {t.id: t for t in plan.tonight}
    assert tonight["drifter"].gain == 5 * 1500
    assert "Engineering to 6" in tonight["railjack"].title
    assert tonight["close"].title.startswith("Finish Mag, Lex")
    assert "Vaykor Hek" in tonight["shop"].detail  # Steel Meridian rank 5
    assert "Telos Boltor" not in tonight["shop"].detail  # Arbiters is an enemy

    first = plan.phases[0]
    assert (first.from_rank, first.to_rank) == (23, 24)
    assert first.steps[0].route == "partial"
    assert all(len(p.steps) or p.already_there for p in plan.phases[:1])

    budget = {b.route: b for b in plan.budget}
    assert budget["standing_owned"].mastery == 3000
    assert budget["standing_other"].mastery == 3000  # Telos Boltor
    assert budget["trade"].trade and budget["trade"].mastery == 3000
    assert budget["extended"].mastery == 4000 + 2000 + 400  # Kuva Zarr + two Forma headroom
    assert plan.budget[-1].trade  # trade sorts last
    # Steel Path: 241 - 102 nodes left, plus 8 Steel Path junctions
    assert budget["steel_path"].count == 7 + 8

    cards = {t.rank: t for t in plan.tests}
    assert set(cards) == set(range(24, 31))
    assert cards[28].bring.startswith("Vauban Prime")
    assert cards[27].bring.startswith("Mag Prime") and "Carrier Prime" in cards[27].bring
    assert cards[24].owned_picks == []

    mood_ids = {c.id for c in plan.mood_cards}
    assert {"elite-sanctuary-onslaught", "duviri-undercroft", "shopping"} <= mood_ids
    archwing = next(c for c in plan.mood_cards if c.id == "archwing-salacia")
    assert "1 unfinished" in archwing.levels  # Odonata
    assert "{" not in "".join(c.levels + c.where for c in plan.mood_cards)


def test_test_card_falls_back_when_nothing_matches(kb):
    card = build_test_card(kb.test_for(25), owned={"Excalibur"})
    assert card.owned_picks == []
    assert "Titania" in card.bring


def test_render_html_is_self_contained(kb, tmp_path: Path):
    plan = build_mastery_plan(_report(), kb)
    html = render_mastery_html(plan)
    assert html.startswith("<!doctype html>")
    assert "<title>Road to Mastery 30</title>" in html
    assert "Vaykor Hek" in html and "Operator Test" in html
    assert 'data-mood="survival"' in html
    assert html.count('<article class="phase">') == len(plan.phases) == 7
    assert html.count('<article class="test">') == 7
    assert "{" not in html.split("<style>")[0]


def test_export_format_guide(tmp_path: Path):
    from openwarframe.exports import run_exports

    results = run_exports(_report(), tmp_path, ["guide"])
    assert results[0].format == "guide"
    assert (tmp_path / "mastery-plan.html").stat().st_size > 10_000
