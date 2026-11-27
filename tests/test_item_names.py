"""Item names in another language in the app and exports, applied after the English logic."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from openwarframe.codex import Codex, languages
from openwarframe.codex.translate import Translator, translator
from test_codex_build import CHASSIS, RELIC, RHINO, RHINO_BP, codex_path  # noqa: F401

DE = {
    RHINO: "Rhino Prime",
    CHASSIS: "Rhino Prime: Chassis",
    RHINO_BP: "Rhino Prime BLAUPAUSE",
    RELIC: "Lith-Relikt: R2",
}


@pytest.fixture
def tr(codex_path: Path) -> Translator:  # noqa: F811
    with Codex(codex_path) as cx:
        return Translator.from_codex(cx.conn, "de", dict(DE))


def test_by_id_and_by_english_name(tr: Translator, codex_path: Path):  # noqa: F811
    assert tr.by_id(CHASSIS, "x") == "Rhino Prime: Chassis" and tr.by_id("/nope", "x") == "x"
    assert tr.by_name("Rhino Prime Chassis") == "Rhino Prime: Chassis"
    assert tr.by_name("Rhino Prime Blueprint") == "Rhino Prime BLAUPAUSE"  # recipe: "<item> Blueprint"
    assert tr.by_name("Not an item at all") == "Not an item at all"
    con = sqlite3.connect(codex_path)
    relic_en = con.execute("SELECT name FROM relic").fetchone()[0]
    assert tr.by_name(relic_en) == "Lith-Relikt: R2" and tr.by_name(relic_en + " Relic") == "Lith-Relikt: R2"


def test_strings_translates_known_names_only(tr: Translator):
    data = {
        "items": [
            {"id": RHINO, "name": "Rhino Prime"},
            {"id": CHASSIS, "name": "Rhino Prime Chassis", "category": "Resource"},
        ],
        "relics": [
            {
                "id": "/x",
                "name": "Lith R9",
                "drops": [{"part": "Rhino Prime Chassis", "for": "Rhino Prime", "rarity": "Rare"}],
            }
        ],
        "farm": {
            "missions": [
                {
                    "place": "Apollodorus (Mercury)",
                    "gives": ["Rhino Prime Chassis · 11.0%", "Lith R1 (Rhino) · 2%"],
                }
            ]
        },
        "note": "Rhino Prime Chassis drops here",  # free text is never touched
    }
    tr.strings(data)
    row = data["items"][1]
    assert row["name"] == "Rhino Prime: Chassis" and row["name_en"] == "Rhino Prime Chassis"
    assert row["category"] == "Resource"
    assert "name_en" not in data["items"][0]  # same in both languages
    assert data["relics"][0]["drops"][0]["part"] == "Rhino Prime: Chassis"
    assert data["farm"]["missions"][0]["gives"][0] == "Rhino Prime: Chassis · 11.0%"
    assert data["farm"]["missions"][0]["place"] == "Apollodorus (Mercury)"
    assert data["note"] == "Rhino Prime Chassis drops here"


def test_report_models_translate_by_unique_name(tr: Translator, codex_path: Path):  # noqa: F811
    from openwarframe.report.model import ComponentRow

    row = ComponentRow(unique_name=CHASSIS, name="Rhino Prime Chassis", count=1)
    out = tr.model(row)
    assert out.name == "Rhino Prime: Chassis" and row.name == "Rhino Prime Chassis"  # a copy


def test_translator_needs_a_saved_table(tmp_path: Path, codex_path: Path):  # noqa: F811
    with Codex(codex_path) as cx:
        assert translator(tmp_path, cx.conn, "en") is None
        assert translator(tmp_path, cx.conn, "de") is None  # nothing downloaded yet
        p = languages.names_path(tmp_path, "de")
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"lang": "de", "version": "1", "names": DE}), encoding="utf-8")
        t = translator(tmp_path, cx.conn, "de")
        assert t and t.by_id(CHASSIS, "") == "Rhino Prime: Chassis"


def test_app_setting_rebuilds_with_names(tmp_path: Path, codex_path: Path, monkeypatch):  # noqa: F811
    from openwarframe.app.server import AppState
    from openwarframe.config import Settings

    state = AppState(Settings(home=codex_path.parent))
    built = []
    monkeypatch.setattr(state, "build", lambda force=False: built.append(force) or {"meta": {}})
    assert "Unknown" in state.set_names_lang("xx")["error"]
    monkeypatch.setattr(languages, "load_names", lambda home, lang, client=None, **_: {})
    assert "Could not download" in state.set_names_lang("de")["error"]
    assert state.names_lang == "en"
    monkeypatch.setattr(languages, "load_names", lambda home, lang, client=None, **_: DE)
    state.set_names_lang("de")
    assert state.names_lang == "de" and built == [True]
    fp = state._fingerprint()
    state.save_prefs(b'{"settings": {"names_lang": "ja"}}', from_page=True)  # the page can't set it
    assert state.names_lang == "de" and state._fingerprint() == fp
    state.set_names_lang("en")
    assert state._fingerprint() != fp  # a cached build in German isn't served in English


def test_exports_use_the_names(tmp_path: Path, tr: Translator):
    from openwarframe.exports import run_exports
    from test_guide import _report

    report = _report()
    tr.names[report.missing[0].unique_name] = "Übersetzt"
    run_exports(report, tmp_path, ["json", "csv"], translator=tr)
    data = json.loads((tmp_path / "account.json").read_text(encoding="utf-8"))
    assert "Übersetzt" in json.dumps(data, ensure_ascii=False)
    assert report.missing[0].name != "Übersetzt"  # the caller's report is untouched


def test_page_has_the_setting():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'id="st-names"' in page and '"/api/names"' in page and "r.name_en" in page
