"""M10: weekly world-state content, Varzia, Linux log paths and the trust docs."""

from __future__ import annotations

import os
from pathlib import Path

from openwarframe.app.live import _words, build_varzia, build_weekly
from openwarframe.live import paths

NOW = 1_795_800_000_000
DOCS = Path(__file__).parents[1] / "docs"


def _d(ms: int) -> dict:
    return {"$date": {"$numberLong": str(ms)}}


WS = {
    "LiteSorties": [
        {
            "Activation": _d(NOW - 10**8),
            "Expiry": _d(NOW + 2 * 86_400_000),
            "Boss": "SORTIE_BOSS_BOREAL",
            "Missions": [{"missionType": "MT_DEFENSE", "node": "SolNode39"}],
        }
    ],
    "EndlessXpSchedule": [
        {
            "Activation": _d(NOW - 10**8),
            "Expiry": _d(NOW + 86_400_000),
            "CategoryChoices": [
                {"Category": "EXC_NORMAL", "Choices": ["Garuda", "Baruuk"]},
                {"Category": "EXC_HARD", "Choices": ["Boltor", "CeramicDagger"]},
            ],
        }
    ],
    "PrimeVaultTraders": [
        {
            "Activation": _d(NOW - 10**8),
            "Expiry": _d(NOW + 3 * 86_400_000),
            "Manifest": [
                {"ItemType": "/Lotus/StoreItems/Powersuits/Wraith/SevagothPrime", "PrimePrice": 3},
                {"ItemType": "/Lotus/StoreItems/Types/Game/Projections/T1VoidProjectionX", "RegularPrice": 1},
                {
                    "ItemType": "/Lotus/Types/StoreItems/Packages/MegaPrimeVault/MPVSevagothPrimeSinglePack",
                    "PrimePrice": 6,
                },
            ],
            "EvergreenManifest": [
                {"ItemType": "/Lotus/StoreItems/Weapons/Tenno/Rifle/BratonPrime", "PrimePrice": 1},
                {"ItemType": "/Lotus/StoreItems/Upgrades/Skins/Scarves/SomeScarf", "PrimePrice": 2},
            ],
        }
    ],
}
DATA = {
    "items": [
        {"id": "g", "name": "Garuda", "mastery": "Never leveled", "owned": None},
        {"id": "b", "name": "Baruuk", "mastery": "Mastered", "owned": None},
        {"id": "bp", "name": "Boltor Prime", "mastery": "Mastered", "owned": True},
        {"id": "/Lotus/Powersuits/Wraith/SevagothPrime", "name": "Sevagoth Prime", "mastery": "Never leveled", "owned": False},
        {"id": "/Lotus/Weapons/Tenno/Rifle/BratonPrime", "name": "Braton Prime", "mastery": "Mastered", "owned": True},
    ],
    "relics": [{"id": "/Lotus/Types/Game/Projections/T1VoidProjectionX", "name": "Lith X1 Relic", "needed": 2}],
    "meta": {"standing_left": {"Default": 12000, "Cetus": 0}},
}  # fmt: skip


def place(node):
    return {"where": {"SolNode39": "Kappa (Sedna)"}.get(node, node)}


def test_weekly_rows():
    rows = {r["id"]: r for r in build_weekly(WS, DATA, place, NOW)}
    archon = rows["archon"]
    assert archon["what"] == "Archon Boreal" and "azure" in archon["note"]
    assert "Defense on Kappa (Sedna)" in archon["detail"] and archon["hours_left"] == 48.0
    assert rows["circuit|Garuda"]["for_you"] and not rows["circuit|Baruuk"]["for_you"]
    boltor = rows["circuit-sp|Boltor"]
    assert boltor["for_you"] and "Boltor Prime" in boltor["note"]  # the adapter fits the Prime too
    assert rows["circuit-sp|CeramicDagger"]["what"] == "Ceramic Dagger Incarnon Genesis"
    assert not rows["circuit-sp|CeramicDagger"]["for_you"]
    assert rows["standing|Default"]["what"] == "Main syndicates" and rows["standing|Default"]["for_you"]
    assert not rows["standing|Cetus"]["for_you"]


def test_expired_weekly_content_is_dropped():
    rows = build_weekly(WS, DATA, place, NOW + 5 * 86_400_000)
    assert [r["kind"] for r in rows] == ["Standing today", "Standing today"]


def test_varzia_flags_what_you_need():
    v = build_varzia(WS, DATA, {}, NOW)
    assert v["here"] and v["days_left"] == 3.0
    by = {s["name"]: s for s in v["stock"]}
    assert by["Sevagoth Prime"]["for_you"] and by["Sevagoth Prime"]["regal_aya"] == 3
    assert by["Lith X1 Relic"]["kind"] == "Relic" and by["Lith X1 Relic"]["aya"] == 1
    assert "2 parts" in by["Lith X1 Relic"]["why"]
    assert by["Sevagoth Prime Single Pack"]["kind"] == "Pack or cosmetic"
    assert "Braton Prime" in by and not by["Braton Prime"]["for_you"]  # evergreen gear, mastered
    assert not any("Scarf" in n for n in by)  # evergreen cosmetics are left out
    assert v["stock"][0]["for_you"]  # what you need comes first


def test_words():
    assert _words("CeramicDagger") == "Ceramic Dagger"
    assert _words("MPVSevagothPrimeSinglePack") == "Sevagoth Prime Single Pack"


def test_linux_finds_the_proton_log(tmp_path: Path, monkeypatch):
    home = tmp_path
    lib2 = tmp_path / "games" / "SteamLibrary"
    steam = home / ".local" / "share" / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "0" {{ "path" "{steam}" }}\n "1" {{ "path" "{lib2}" }}\n}}\n'
    )
    old = steam / "steamapps/compatdata/230410/pfx/drive_c/users/steamuser/AppData/Local/Warframe"
    new = lib2 / "steamapps/compatdata/230410/pfx/drive_c/users/steamuser/AppData/Local/Warframe"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "EE.log").write_text("x")
    os.utime(old / "EE.log", (1, 1))
    cands = paths.linux_candidates(home)
    assert old in cands and new in cands
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("OPENWARFRAME_WARFRAME_DIR", raising=False)
    monkeypatch.setattr(paths, "linux_candidates", lambda: cands)
    assert paths.warframe_dir() == new  # newest EE.log wins


def test_trust_docs_exist_and_are_linked():
    for name in ("LEGAL.md", "ACCESSIBILITY.md", "I18N.md"):
        assert (DOCS / name).exists()
    readme = (DOCS.parent / "README.md").read_text(encoding="utf-8")
    for name in ("docs/LEGAL.md", "docs/ACCESSIBILITY.md", "docs/I18N.md", "Linux"):
        assert name in readme
    page = (DOCS.parent / "src/openwarframe/app/static/index.html").read_text(encoding="utf-8")
    assert "not affiliated with Digital Extremes" in page
