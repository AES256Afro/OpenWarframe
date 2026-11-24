"""Live tab matching and finish-card build costs. No network: the world state is faked."""

from __future__ import annotations

from pathlib import Path

from openwarframe.app.farm import build_cost
from openwarframe.app.live import build_live, you_are_here
from openwarframe.codex import Codex
from openwarframe.inventory import parse_inventory
from test_app import INVENTORY
from test_codex_build import CELL, RHINO, codex_path  # noqa: F401

NOW = 1_800_000_000_000


class FakeClient:
    def __init__(self, ws: dict) -> None:
        self.ws = ws

    def get_json(self, url: str, **_):
        return self.ws


def _ms(v: int) -> dict:
    return {"$date": {"$numberLong": str(v)}}


WORLD = {
    "ActiveMissions": [
        {
            "Node": "SolNode94",
            "MissionType": "MT_CAPTURE",
            "Modifier": "VoidT1",
            "Expiry": _ms(NOW + 30 * 60000),
        },
        {
            "Node": "SolNode94",
            "MissionType": "MT_SURVIVAL",
            "Modifier": "VoidT4",
            "Expiry": _ms(NOW + 60 * 60000),
            "Hard": True,
        },
        {"Node": "SolNode94", "MissionType": "MT_DEFENSE", "Modifier": "VoidT2", "Expiry": _ms(NOW - 1)},
    ],
    "VoidStorms": [
        {"Node": "CrewBattleNode509", "ActiveMissionTier": "VoidT1", "Expiry": _ms(NOW + 90 * 60000)}
    ],
    "VoidTraders": [
        {
            "Node": "EarthHUB",
            "Activation": _ms(NOW + 3_600_000),
            "Expiry": _ms(NOW + 7_200_000),
            "Manifest": [],
        }
    ],
    "Invasions": [
        {
            "Node": "SolNode94",
            "Faction": "FC_GRINEER",
            "DefenderFaction": "FC_CORPUS",
            "Count": 0,
            "Goal": 100,
            "Completed": False,
            "AttackerReward": {
                "countedItems": [
                    {"ItemType": "/Lotus/Types/Recipes/Components/OrokinCatalystBlueprint", "ItemCount": 1}
                ]
            },
            "DefenderReward": [],
            "_id": {"$oid": "x"},
        }
    ],
}


def _data(with_inventory: bool) -> dict:
    relics = [
        {
            "id": "L1",
            "name": "Lith Z1",
            "tier": "Lith",
            "count": 2 if with_inventory else None,
            "needed": 3,
            "vaulted_parts": 1,
        },
        {
            "id": "A1",
            "name": "Axi Z1",
            "tier": "Axi",
            "count": 0 if with_inventory else None,
            "needed": 2,
            "vaulted_parts": 0,
        },
    ]
    return {
        "meta": {"inventory": {} if with_inventory else None},
        "relics": relics,
        "items": [],
        "resources": [],
    }


def test_fissures_match_owned_relics_and_skip_expired(codex_path: Path, tmp_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    live = build_live(cx.conn, _data(True), FakeClient(WORLD), now_ms=NOW, log_path=tmp_path / "none.log")
    assert [f["tier"] for f in live["fissures"]] == ["Lith", "Axi"]  # expired Meso dropped, useful first
    lith = live["fissures"][0]
    assert lith["where"] == "Apollodorus (Mercury)" and lith["minutes_left"] == 30 and lith["fast"]
    assert lith["best_relic"] == "Lith Z1" and lith["best_relic_count"] == 2
    assert live["fissures"][1]["useful_relics"] == 0  # Axi relic not owned
    assert live["storms"][0]["where"] == "Railjack void storm"
    assert live["baro"]["here"] is False and live["baro"]["hours_until"] == 1.0
    assert live["invasions"][0]["worth_it"]  # Orokin Catalyst is always worth it
    assert live["here"] is None


def test_without_inventory_any_relic_of_the_tier_counts(codex_path: Path, tmp_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    live = build_live(cx.conn, _data(False), FakeClient(WORLD), now_ms=NOW, log_path=tmp_path / "none.log")
    axi = next(f for f in live["fissures"] if f["tier"] == "Axi")
    assert axi["useful_relics"] == 1 and axi["owned_relics"] is None


def test_you_are_here_reads_the_last_mission(tmp_path: Path):
    log = tmp_path / "EE.log"
    log.write_text(
        '10.000 Sys [Info]: Client loaded {"difficulty":0,"name":"SolNode46_ActiveMission"} with MissionInfo:\n'
        "{\n"
        '    "missionType" : "MT_DEFENSE",\n'
        '    "faction" : "FC_GRINEER"\n'
        "}\n"
        "11.000 Sys [Info]: something else\n",
        encoding="utf-8",
    )
    here = you_are_here(log)
    assert here and here["node"] == "SolNode46_ActiveMission" and here["mission"] == "Defense"


def test_build_cost_counts_credits_and_resources(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    cost = build_cost(cx.conn, RHINO, None)
    assert cost["credits"] == 25000 + 15000  # main blueprint + chassis blueprint
    cells = next(r for r in cost["resources"] if r["name"] == "Orokin Cell")
    assert cells["need"] == 3 + 1
    inv = parse_inventory(INVENTORY)  # holds no chassis, one Orokin Cell
    cost2 = build_cost(cx.conn, RHINO, inv)
    assert next(r for r in cost2["resources"] if r["name"] == "Orokin Cell")["short"] == 3
    assert CELL
