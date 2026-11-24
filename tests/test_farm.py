"""What to farm: relic needs, mission ranking and the popular-farm knowledge file."""

from __future__ import annotations

from pathlib import Path

from openwarframe.app.farm import load_popular, rank_missions, relics_with_needs
from openwarframe.codex import Codex
from openwarframe.guide.kb import kb_dir
from test_codex_build import CELL, CHASSIS_BP, RELIC, codex_path  # noqa: F401


def test_relics_with_needs_maps_relic_to_item(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    needs = relics_with_needs(cx.conn, {CHASSIS_BP: "Rhino Prime"})
    assert needs == {RELIC: ["Rhino Prime"]}


def test_missions_rank_direct_part_drops(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    rows = rank_missions(cx.conn, {CELL: "Rhino Prime"}, {}, {})
    assert rows == sorted(rows, key=lambda r: -r["score"])
    top = next(r for r in rows if r["place"].startswith("Apollodorus"))
    assert top["kind"] == "Mission"
    assert top["score"] > 0 and any("Rhino Prime" in g for g in top["gives"])
    # the cell also drops from arbitrations and sorties in the fixture
    assert {r["kind"] for r in rows} >= {"Mission", "Special"}


def test_popular_farms_file_is_valid():
    farms = load_popular(kb_dir())
    assert {"hepit", "ukko", "apollo", "xini"} <= set(farms)
    for f in farms.values():
        assert f["tiers"] and f["why"] and f["planet"]


def test_popular_tag_needs_matching_tiers(codex_path: Path):  # noqa: F811
    cx = Codex(codex_path)
    popular = {"apollodorus": {"place": "Apollodorus", "tiers": ["Axi"], "why": "test"}}
    rows = rank_missions(cx.conn, {CELL: "Rhino Prime"}, {}, popular)
    top = next(r for r in rows if r["place"].startswith("Apollodorus"))
    assert top["popular"] is False  # the fixture node drops no Axi relics
