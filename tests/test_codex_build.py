"""Build a tiny codex from synthetic payloads and query it. No network."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openwarframe.codex import Codex, CodexPayloads, build_codex
from openwarframe.sources.static.market import MarketItem
from openwarframe.sources.static.pe_plus import PlusExport
from openwarframe.sources.static.public_export import MANIFESTS, PublicExport
from openwarframe.sources.static.wfcd_drops import DropData

RHINO = "/Lotus/Powersuits/Rhino/RhinoPrime"
CHASSIS = "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeChassisComponent"
CHASSIS_BP = "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeChassisBlueprint"
RHINO_BP = "/Lotus/Types/Recipes/WarframeRecipes/RhinoPrimeBlueprint"
CELL = "/Lotus/Types/Items/MiscItems/OrokinCell"
RELIC = "/Lotus/Types/Game/Projections/T1RhinoPrimeChassisBronze"


def _pe() -> PublicExport:
    manifests = {m: {} for m in MANIFESTS}
    manifests["ExportWarframes"] = {
        "ExportWarframes": [
            {
                "uniqueName": RHINO,
                "name": "Rhino Prime",
                "productCategory": "Suits",
                "masteryReq": 0,
                "description": "Tank.",
            },
            {
                "uniqueName": "/Lotus/Powersuits/Archwing/Amesha",
                "name": "<ARCHWING> Amesha",
                "productCategory": "SpaceSuits",
            },
        ]
    }
    manifests["ExportWeapons"] = {"ExportWeapons": [], "ExportRailjackWeapons": []}
    manifests["ExportResources"] = {
        "ExportResources": [
            {"uniqueName": CHASSIS, "name": "Rhino Prime Chassis"},
            {"uniqueName": CELL, "name": "Orokin Cell"},
        ]
    }
    manifests["ExportRecipes"] = {
        "ExportRecipes": [
            {
                "uniqueName": RHINO_BP,
                "resultType": RHINO,
                "buildPrice": 25000,
                "buildTime": 259200,
                "skipBuildTimePrice": 50,
                "num": 1,
                "ingredients": [{"ItemType": CHASSIS, "ItemCount": 1}, {"ItemType": CELL, "ItemCount": 3}],
            },
            {
                "uniqueName": CHASSIS_BP,
                "resultType": CHASSIS,
                "buildPrice": 15000,
                "buildTime": 43200,
                "num": 1,
                "ingredients": [{"ItemType": CELL, "ItemCount": 1}],
            },
        ]
    }
    manifests["ExportRegions"] = {
        "ExportRegions": [
            {
                "uniqueName": "SolNode94",
                "name": "Apollodorus",
                "systemName": "Mercury",
                "systemIndex": 0,
                "missionIndex": 2,
                "factionIndex": 2,
                "minEnemyLevel": 6,
                "maxEnemyLevel": 11,
                "masteryReq": 0,
            }
        ]
    }
    manifests["ExportRelicArcane"] = {
        "ExportRelicArcane": [
            {
                "uniqueName": RELIC,
                "name": "Lith R2 Relic",
                "relicRewards": [
                    {
                        "rewardName": "/Lotus/StoreItems/Types/Recipes/WarframeRecipes/RhinoPrimeChassisBlueprint",
                        "rarity": "RARE",
                        "tier": 0,
                        "itemCount": 1,
                    }
                ],
            },
            {
                "uniqueName": "/Lotus/Upgrades/CosmeticEnhancers/ArcaneX",
                "name": "Arcane Guardian",
                "rarity": "UNCOMMON",
            },
        ]
    }
    manifests["ExportManifest"] = {
        "Manifest": [{"uniqueName": RHINO, "textureLocation": "/Lotus/Interface/Icons/Rhino.png!00_x"}]
    }
    for m in (
        "ExportUpgrades",
        "ExportSentinels",
        "ExportKeys",
        "ExportGear",
        "ExportDrones",
        "ExportCustoms",
        "ExportFlavour",
        "ExportFusionBundles",
        "ExportSortieRewards",
    ):
        manifests[m] = {m: []}
    manifests["ExportUpgrades"] = {"ExportUpgrades": [], "ExportAvionics": [], "ExportFocusUpgrades": []}
    manifests["ExportRelicArcane"]["ExportRelicArcane"].append(
        {
            "uniqueName": RELIC.replace("Bronze", "Platinum"),
            "name": "Lith R2 Relic",
            "relicRewards": [
                {
                    "rewardName": "/Lotus/StoreItems/Types/Recipes/WarframeRecipes/RhinoPrimeChassisBlueprint",
                    "rarity": "RARE",
                    "tier": 0,
                    "itemCount": 1,
                }
            ],
        }
    )
    return PublicExport(version="test", index=[], manifests=manifests)


def _plus() -> PlusExport:
    return PlusExport(
        version="senpai@test",
        files={
            "ExportRelics": {RELIC: {"era": "Lith", "category": "Standard", "quality": "VPQ_BRONZE"}},
            "ExportMissionTypes": {
                "MT_SURVIVAL": {"index": 2, "name": "/Lotus/Language/Missions/MissionName_Survival"}
            },
            "ExportVendors": {
                "/Lotus/Types/Game/VendorManifests/Deimos/LoidManifest": {
                    "items": [
                        {
                            "storeItem": "/Lotus/StoreItems/Types/Items/MiscItems/OrokinCell",
                            "quantity": 1,
                            "itemPrices": [
                                {"ItemType": "/Lotus/Types/Items/MiscItems/Standing", "ItemCount": 2000}
                            ],
                        }
                    ]
                }
            },
            "ExportSyndicates": {
                "ArbitersSyndicate": {
                    "uniqueName": "/Lotus/Syndicates/ArbitersSyndicate",
                    "name": "/Lotus/Language/Syndicates/ArbitersName",
                    "favours": [
                        {
                            "storeItem": "/Lotus/StoreItems/Types/Items/MiscItems/OrokinCell",
                            "standingCost": 5000,
                            "creditsCost": 0,
                            "requiredLevel": 3,
                        }
                    ],
                }
            },
            "ExportChallenges": {
                "/Lotus/Types/Challenges/X": {
                    "name": "/Lotus/Language/Challenges/X_Name",
                    "description": "/Lotus/Language/Challenges/X_Desc",
                }
            },
            "ExportBounties": {},
        },
        dictionary={
            "/Lotus/Language/Missions/MissionName_Survival": "Survival",
            "/Lotus/Language/Syndicates/ArbitersName": "Arbiters of Hexis",
            "/Lotus/Language/Challenges/X_Name": "Archivist",
            "/Lotus/Language/Challenges/X_Desc": "Scan things.",
        },
    )


def _drops() -> DropData:
    return DropData(
        version="hash",
        modified=0,
        data={
            "missionRewards": {
                "Mercury": {
                    "Apollodorus": {
                        "gameMode": "Survival",
                        "isEvent": False,
                        "rewards": {
                            "A": [
                                {"itemName": "Orokin Cell", "rarity": "Rare", "chance": 2.0},
                                {"itemName": "Mystery Box", "rarity": "Rare", "chance": 1.0},
                            ]
                        },
                    }
                }
            },
            "enemyModTables": [
                {
                    "enemyName": "Tusk Thumper",
                    "enemyModDropChance": "3.00",
                    "mods": [{"modName": "Orokin Cell", "rarity": "Rare", "chance": 1.5}],
                }
            ],
            "cetusBountyRewards": [
                {
                    "bountyLevel": "Level 5 - 15 Cetus Bounty",
                    "rewards": {
                        "A": [
                            {
                                "itemName": "Rhino Prime Chassis Blueprint",
                                "rarity": "Rare",
                                "chance": 5.0,
                                "stage": "Stage 1",
                            }
                        ]
                    },
                }
            ],
            "transientRewards": [
                {
                    "objectiveName": "Arbitrations",
                    "rewards": [
                        {"rotation": "A", "itemName": "Orokin Cell", "rarity": "Common", "chance": 10}
                    ],
                }
            ],
            "sortieRewards": [{"itemName": "Orokin Cell", "rarity": "Common", "chance": 5}],
            "syndicates": {
                "Arbiters of Hexis": [
                    {
                        "item": "Orokin Cell",
                        "place": "Arbiters of Hexis, Rank 1",
                        "standing": 500,
                        "cost": 0,
                        "chance": 100,
                        "rarity": "Common",
                    }
                ]
            },
        },
    )


@pytest.fixture
def codex_path(tmp_path: Path) -> Path:
    path = tmp_path / "codex.sqlite"
    conn = sqlite3.connect(path)
    payloads = CodexPayloads(
        public_export=_pe(),
        plus=_plus(),
        drops=_drops(),
        market=[MarketItem(RHINO, "rhino_prime_set", "Rhino Prime Set", ["prime"])],
    )
    report = build_codex(conn, payloads)
    conn.close()
    assert report.counts["item"] == 9  # 2 frames, 2 resources, 2 relic variants, arcane, 2 currencies
    assert report.counts["relic"] == 1  # refinement variants collapse into one relic
    assert report.counts["recipe"] == 2
    assert report.counts["node_reward"] == 2
    assert "Mystery Box" in report.unresolved
    return path


def test_resolve_and_item(codex_path: Path):
    cx = Codex(codex_path)
    assert cx.resolve("Rhino Prime") == RHINO
    assert cx.resolve("rhino prime chassis blueprint") == CHASSIS_BP
    assert cx.resolve(RHINO) == RHINO
    assert cx.resolve("Amesha") == "/Lotus/Powersuits/Archwing/Amesha"
    it = cx.item(RHINO)
    assert it["category"] == "Warframe"
    assert it["image"].endswith("Rhino.png!00_x")
    assert it["market"]["slug"] == "rhino_prime_set"
    assert cx.item("/Lotus/Powersuits/Archwing/Amesha")["category"] == "Archwing"


def test_crafting_tree_totals(codex_path: Path):
    cx = Codex(codex_path)
    tree = cx.crafting_tree(RHINO)
    assert tree.recipe == RHINO_BP
    totals = cx.tree_totals(tree)
    # 3 cells directly + 1 cell inside the chassis recipe
    assert totals[CELL] == ("Orokin Cell", 4)
    assert cx.is_component(CHASSIS) and not cx.is_component(CELL)
    assert len(cx.what_needs(CELL)) == 2


def test_sources_cover_every_table(codex_path: Path):
    cx = Codex(codex_path)
    kinds = {s.kind for s in cx.sources_for(CELL)}
    assert {"node", "enemy", "transient", "vendor", "syndicate"} <= kinds
    chassis = cx.sources_for(CHASSIS)
    assert any(s.kind == "relic" and "Lith R2" in s.where for s in chassis)
    assert any(s.kind == "bounty" for s in chassis)
    relics = [s for s in chassis if s.kind == "relic"]
    assert len(relics) == 1
    assert relics[0].extra["intact"] == 2.0 and relics[0].extra["radiant"] == 10.0
    assert cx.resolve("Lith R2 Relic") == RELIC
    assert cx.counts()["unresolved_name"] == 1
