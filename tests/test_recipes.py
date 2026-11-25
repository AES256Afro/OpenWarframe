"""Milestone 3: the advice is right for the awkward cases. No network.

A tiny codex holds the shapes that broke before: a part a recipe needs twice
(Akstiletto Prime barrels), a dual weapon built from two base weapons listed on two lines
(Akbronco Prime), an item with a resource-only dojo recipe next to the one built from parts,
and a "convert" recipe next to a normal one.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from openwarframe.app.data import _access
from openwarframe.app.extras import build_foundry, build_resources, build_sell
from openwarframe.app.farm import build_cost, needed_parts, rank_missions
from openwarframe.codex import Codex
from openwarframe.codex.build import _node_for
from openwarframe.codex.names import mission_label
from openwarframe.codex.recipes import RecipeGraph
from openwarframe.codex.schema import SCHEMA
from openwarframe.guide.render import track_svg
from openwarframe.inventory import parse_inventory
from openwarframe.report.build import _syndicate_max_ranks, rank_threshold
from openwarframe.report.model import ComponentRow, MissingItem, SourceRow

W = "/Lotus/Weapons/Tenno"
R = "/Lotus/Types/Recipes/Weapons"
AKSTILETTO, AKS_BP = f"{W}/Pistols/AkstilettoPrime", f"{R}/AkstilettoPrimeBlueprint"
AKS_BARREL, AKS_BARREL_BP = f"{R}/WeaponParts/AkstilettoPrimeBarrel", f"{R}/AkstilettoPrimeBarrelBlueprint"
AKS_LINK = f"{R}/WeaponParts/AkstilettoPrimeLink"
BRONCO, BRONCO_BP = f"{W}/Pistol/BroncoPrime", f"{R}/BroncoPrimeBlueprint"
BRONCO_BARREL = f"{R}/WeaponParts/BroncoPrimeBarrel"
AKBRONCO, AKBRONCO_BP = f"{W}/Pistols/AkbroncoPrime", f"{R}/AkbroncoPrimeBlueprint"
AKBRONCO_LINK = f"{R}/WeaponParts/AkbroncoPrimeLink"
SHEEV = f"{W}/Melee/GrineerCombatKnife"
SHEEV_DOJO, SHEEV_SORTIE = f"{R}/GrineerCombatKnifeBlueprint", f"{R}/GrineerCombatKnifeSortieBlueprint"
SHEEV_BLADE = f"{R}/WeaponParts/GrineerCombatKnifeBlade"
NIKANA, DRAGON = f"{W}/Melee/Katana", f"{W}/Melee/DragonNikana"
DRAGON_CONVERT, DRAGON_NORMAL = f"{R}/ConvertKatanaBlueprint", f"{R}/LowKatanaBlueprint"
CELL = "/Lotus/Types/Items/MiscItems/OrokinCell"
SALVAGE = "/Lotus/Types/Items/MiscItems/Salvage"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "codex.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    items = [
        (AKSTILETTO, "Akstiletto Prime", "Secondary", None),
        (AKS_BARREL, "Akstiletto Prime Barrel", "Resource", {"primeSellingPrice": 45}),
        (AKS_LINK, "Akstiletto Prime Link", "Resource", {"primeSellingPrice": 15}),
        (BRONCO, "Bronco Prime", "Secondary", None),
        (BRONCO_BARREL, "Bronco Prime Barrel", "Resource", {"primeSellingPrice": 15}),
        (AKBRONCO, "Akbronco Prime", "Secondary", None),
        (AKBRONCO_LINK, "Akbronco Prime Link", "Resource", None),
        (SHEEV, "Sheev", "Melee", None),
        (SHEEV_BLADE, "Sheev Blade", "Resource", None),
        (NIKANA, "Nikana", "Melee", None),
        (DRAGON, "Dragon Nikana", "Melee", None),
        (CELL, "Orokin Cell", "Resource", None),
        (SALVAGE, "Salvage", "Resource", None),
    ]
    conn.executemany(
        "INSERT INTO item (unique_name, name, category, data) VALUES (?,?,?,?)",
        [(u, n, c, json.dumps(d) if d else None) for u, n, c, d in items],
    )
    recipes = [
        (AKS_BP, AKSTILETTO, 25000),
        (AKS_BARREL_BP, AKS_BARREL, 15000),
        (BRONCO_BP, BRONCO, 15000),
        (AKBRONCO_BP, AKBRONCO, 15000),
        (SHEEV_DOJO, SHEEV, 20000),
        (SHEEV_SORTIE, SHEEV, 20000),
        (DRAGON_CONVERT, DRAGON, 5000),
        (DRAGON_NORMAL, DRAGON, 5000),
    ]
    conn.executemany("INSERT INTO recipe (unique_name, result_item, build_price) VALUES (?,?,?)", recipes)
    ingredients = [
        (AKS_BP, AKS_BARREL, 2),
        (AKS_BP, AKS_LINK, 1),
        (AKS_BP, CELL, 10),
        (AKS_BARREL_BP, SALVAGE, 500),
        (BRONCO_BP, BRONCO_BARREL, 1),
        # the export names the base weapon twice; an older codex stores both lines
        (AKBRONCO_BP, BRONCO, 1),
        (AKBRONCO_BP, BRONCO, 1),
        (AKBRONCO_BP, AKBRONCO_LINK, 1),
        (SHEEV_DOJO, SALVAGE, 1500),
        (SHEEV_SORTIE, SHEEV_BLADE, 1),
        (DRAGON_CONVERT, NIKANA, 1),
        (DRAGON_NORMAL, CELL, 4),
    ]
    conn.executemany("INSERT INTO recipe_ingredient VALUES (?,?,?)", ingredients)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def cx(db: Path) -> Codex:
    return Codex(db)


def _inv(misc: dict | None = None, recipes: dict | None = None, pistols: list[str] | None = None):
    return parse_inventory(
        {
            "Suits": [],
            "Pistols": [{"ItemType": t} for t in pistols or []],
            "MiscItems": [{"ItemType": k, "ItemCount": v} for k, v in (misc or {}).items()],
            "Recipes": [{"ItemType": k, "ItemCount": v} for k, v in (recipes or {}).items()],
        }
    )


# -- the shared graph -----------------------------------------------------------------------


def test_counts_are_summed_and_parts_needed_twice_say_so(cx: Codex):
    g = cx.graph
    assert g.ingredients(AKBRONCO_BP)[BRONCO] == 2  # two lines of one -> two
    assert g.needed_count(AKS_BARREL) == 2
    assert g.needed_count(AKS_BARREL_BP) == 2  # a part blueprint stands for the part
    assert g.needed_count(AKS_BP) == 1  # the item's own blueprint
    assert [r["count"] for r in cx.ingredients(AKBRONCO_BP) if r["item"] == BRONCO] == [2]


def test_parts_belong_to_the_first_masterable_item(cx: Codex):
    g = cx.graph
    assert g.final_item(BRONCO_BARREL) == BRONCO  # not Akbronco Prime, built from two Broncos
    assert g.final_item(BRONCO_BP) == BRONCO
    assert g.final_item(AKS_BARREL_BP) == AKSTILETTO
    assert g.final_item(CELL) == CELL  # a resource stays itself


def test_the_recipe_built_from_parts_wins_and_convert_recipes_lose(cx: Codex):
    g = cx.graph
    assert g.recipe_for(SHEEV) == SHEEV_SORTIE  # parts beat the resource-only dojo recipe
    assert g.recipe_for(DRAGON) == DRAGON_NORMAL  # never "turn a Nikana into this"
    assert cx.recipes_for(SHEEV)[0]["unique_name"] == SHEEV_SORTIE


# -- advice built on it -----------------------------------------------------------------------


def test_sell_list_keeps_both_barrels(cx: Codex):
    rows = {r["id"]: r for r in build_sell(cx.conn, _inv({AKS_BARREL: 2}), cx.graph, set(), {})}
    assert rows[AKS_BARREL]["keep"] == 2 and rows[AKS_BARREL]["spare"] == 0
    assert rows[AKS_BARREL]["status"] == "Keep 2 to build"
    rows = {r["id"]: r for r in build_sell(cx.conn, _inv({AKS_BARREL: 3}), cx.graph, set(), {})}
    assert rows[AKS_BARREL]["spare"] == 1
    mastered = {r["id"]: r for r in build_sell(cx.conn, _inv({AKS_BARREL: 2}), cx.graph, {AKSTILETTO}, {})}
    assert mastered[AKS_BARREL]["spare"] == 2


def test_bronco_parts_are_judged_by_bronco_not_akbronco(cx: Codex):
    # mastered Akbronco Prime but never Bronco Prime: the Bronco barrel is still needed
    names = dict(cx.conn.execute("SELECT unique_name, name FROM item"))
    rows = {r["id"]: r for r in build_sell(cx.conn, _inv({BRONCO_BARREL: 1}), cx.graph, {AKBRONCO}, names)}
    assert rows[BRONCO_BARREL]["for"] == "Bronco Prime" and rows[BRONCO_BARREL]["spare"] == 0


def test_one_barrel_is_not_enough_for_the_farm_planner(cx: Codex):
    missing = MissingItem(
        unique_name=AKSTILETTO,
        name="Akstiletto Prime",
        category="Secondary",
        mastery_req=0,
        above_your_mr=False,
        acquisition="Relics (farmable now)",
        tradeable=False,
        components=[ComponentRow(unique_name=AKS_BARREL, name="Akstiletto Prime Barrel", count=2)],
        wiki_url="",
    )
    report = SimpleNamespace(missing=[missing])
    assert AKS_BARREL in needed_parts(cx.conn, report, _inv({AKS_BARREL: 1}), set(), cx.graph)
    assert AKS_BARREL not in needed_parts(cx.conn, report, _inv({AKS_BARREL: 2}), set(), cx.graph)


def test_two_owned_broncos_count_toward_akbronco(cx: Codex):
    cost = build_cost(cx.conn, AKBRONCO, _inv(pistols=[BRONCO, BRONCO]), cx.graph)
    bronco = next(r for r in cost["resources"] if r["name"] == "Bronco Prime")
    assert bronco == {"name": "Bronco Prime", "need": 2, "have": 2, "short": 0}


def test_resources_count_one_build_per_blueprint_and_skip_what_is_done(cx: Codex):
    def rows(inv, mastered=frozenset()):
        return {
            r["name"]: r for r in build_resources(cx.conn, inv, lambda uid: None, cx.graph, set(mastered))
        }

    assert rows(_inv(recipes={AKS_BP: 34}))["Orokin Cell"]["need"] == 10  # not 340
    assert "Orokin Cell" not in rows(_inv(recipes={AKS_BP: 1}), {AKSTILETTO})
    # a part blueprint whose two barrels are already built needs nothing more
    assert "Salvage" not in rows(_inv({AKS_BARREL: 2}, recipes={AKS_BARREL_BP: 1}))
    assert rows(_inv({AKS_BARREL: 1}, recipes={AKS_BARREL_BP: 1}))["Salvage"]["need"] == 500


def test_foundry_is_not_ready_a_few_minutes_early(cx: Codex):
    now = datetime(2026, 11, 25, 12, tzinfo=UTC)
    soon = int((now + timedelta(minutes=3)).timestamp() * 1000)
    inv = parse_inventory(
        {
            "Suits": [],
            "PendingRecipes": [{"ItemType": AKS_BP, "CompletionDate": {"$date": {"$numberLong": str(soon)}}}],
        }
    )
    row = build_foundry(cx.conn, inv, now=now)[0]
    assert row["hours_left"] == 0.1 and not row["ready"]
    assert build_foundry(cx.conn, inv, now=now + timedelta(minutes=4))[0]["ready"]


def test_mission_drop_chances_never_add_up_past_100(cx: Codex):
    with sqlite3.connect(cx.conn.execute("PRAGMA database_list").fetchone()[2]) as w:
        w.executemany(
            "INSERT INTO node_reward (node, planet, place, rotation, item_name, item, chance) VALUES (?,?,?,?,?,?,?)",
            [(None, "Mars", "Spear", rot, "Barrel", AKS_BARREL, 50.0) for rot in "ABC"],
        )
    rows = rank_missions(cx.conn, {AKS_BARREL: "Akstiletto Prime"}, {}, {})
    assert rows[0]["gives"] == ["part for Akstiletto Prime · 50.0%"]


# -- access, ranks, names -------------------------------------------------------------------


def _syndicate_item(where: str, detail: str) -> MissingItem:
    return MissingItem(
        unique_name="x",
        name="Vaykor Hek",
        category="Primary",
        mastery_req=0,
        above_your_mr=False,
        acquisition="Vendor / standing",
        tradeable=False,
        blueprint_sources=[SourceRow(kind="syndicate", where=where, detail=detail)],
        wiki_url="",
    )


def test_syndicate_items_need_a_pledge_and_the_right_rank():
    m = _syndicate_item("Steel Meridian", "25000 standing - rank 5")
    assert _access(m, {}) == "Needs syndicate standing"  # never pledged
    assert _access(m, {"steel meridian": 2}) == "Needs syndicate standing"
    assert _access(m, {"steel meridian": 5}) == "Available"
    assert _access(_syndicate_item("Kahl's Garrison", "rank 1"), {"garrison": 1}) == "Available"


def test_legendary_rank_thresholds():
    assert rank_threshold(30) == 2_250_000
    assert rank_threshold(31) == 2_397_500
    assert rank_threshold(35) == 2_987_500
    svg = track_svg(33, 2_700_000)
    assert 'points="-' not in svg and 'x="-' not in svg


def test_rank_40_items_are_not_mastered_at_30():
    from openwarframe.account import parse_profile

    def mastered(xp: int) -> bool:
        data = {
            "Results": [
                {
                    "LoadOutInventory": {
                        "XPInfo": [
                            {"ItemType": "/Lotus/Weapons/Grineer/KuvaLich/LongGuns/KuvaZarr", "XP": xp}
                        ]
                    }
                }
            ]
        }
        return parse_profile(data).progression.items[0].mastered

    assert not mastered(450_000)  # rank 30
    assert mastered(800_000)  # rank 40


def test_mission_names_use_the_game_spelling():
    assert mission_label("MT_ARTIFACT") == "Disruption"
    assert mission_label("MT_CORRUPTION") == "Void Flood"
    assert mission_label("MT_EXCAVATE") == "Excavation"
    assert mission_label("MOBILE DEFENSE") == "Mobile Defense"
    assert mission_label("Follie's Hunt") == "Follie's Hunt"


def test_suffixed_drop_places_link_to_their_node():
    nodes = {("adrastea", "jupiter"): "SolNode97"}
    assert _node_for("Adrastea (Caches)", "Jupiter", nodes, {"adrastea": "SolNode97"}) == "SolNode97"
    assert _node_for("Nowhere (Extra)", "Jupiter", nodes, {}) is None


def test_syndicate_max_ranks_come_from_the_codex(cx: Codex):
    with sqlite3.connect(cx.conn.execute("PRAGMA database_list").fetchone()[2]) as w:
        titles = lambda *levels: json.dumps({"titles": [{"level": lv} for lv in levels]})  # noqa: E731
        w.executemany(
            "INSERT INTO syndicate (tag, name, data) VALUES (?,?,?)",
            [
                ("NecraloidSyndicate", "Necraloid", titles(3, 2, 1)),
                ("SteelMeridianSyndicate", "Steel Meridian", titles(5, 4, 3, 2, 1, -1)),
                ("RadioLegion3Syndicate", "Nightwave", titles(*range(210, 0, -1))),
            ],
        )
    tops = _syndicate_max_ranks(SimpleNamespace(conn=cx.conn))
    assert tops == {"NecraloidSyndicate": 3, "SteelMeridianSyndicate": 5, "RadioLegion3Syndicate": 30}


def test_empty_syndicate_costs_are_left_out(cx: Codex):
    with sqlite3.connect(cx.conn.execute("PRAGMA database_list").fetchone()[2]) as w:
        w.execute(
            "INSERT INTO syndicate_drop (syndicate, item_name, item, place, standing, cost) VALUES (?,?,?,?,?,?)",
            ("Vox Solaris", "Barrel", AKS_BARREL, "Agent", 5000, None),
        )
    detail = next(s.detail for s in cx.sources_for(AKS_BARREL) if s.kind == "syndicate")
    assert detail == "Agent - 5000 standing"


def test_graph_works_on_a_bare_connection(db: Path):
    with sqlite3.connect(db) as conn:
        assert RecipeGraph(conn).needed_count(AKS_BARREL) == 2
