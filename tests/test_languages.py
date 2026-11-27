"""Reward names in the game's language: name tables, Unicode matching, the setting."""

from __future__ import annotations

import json
import lzma
from pathlib import Path

import pytest

from openwarframe.codex import languages
from openwarframe.live.match import RewardCatalog, RewardEntry, normalize

EM = chr(0x2014)  # Polish uses one in its blueprint pattern


def test_normalize_keeps_every_script_and_folds_accents():
    assert normalize("Rhino Prime: Chassis") == "RHINO PRIME CHASSIS"
    assert normalize("rhino prime systems") == normalize("RHINO PRIME SYSTEMS")
    assert normalize("Rhino Prime (Schéma)") == normalize("RHINO PRIME (SCHEMA)")  # OCR drops accents
    assert normalize("ЧЕРТЁЖ: Рино Прайм") == normalize("ЧЕРТЕЖ РИНО ПРАЙМ")
    assert normalize("Rhino Primeの設計図") == "RHINO PRIMEの設計図"
    assert normalize("ガ") != normalize("カ")  # kana marks are part of the letter
    assert normalize(f"Rhino Prime {EM} SCHEMAT") == "RHINO PRIME SCHEMAT"
    assert normalize("N0VA PR1ME") == "NOVA PRIME"  # OCR digit slips still fixed
    assert normalize("  ") == "" and normalize("--") == ""


def _entry(uid, name, read=""):
    return RewardEntry(unique_name=uid, name=name, final_item="/F", final_name="F", read_name=read)


def test_catalog_matches_the_game_language_and_shows_english():
    cat = RewardCatalog(
        [
            _entry("/a", "Rhino Prime Chassis", "Рино Прайм: Каркас"),
            _entry("/b", "Rhino Prime Blueprint", "ЧЕРТЁЖ: Рино Прайм"),
            _entry("/c", "Forma Blueprint"),  # no translation: matched in English
        ]
    )
    m = cat.match("РИНО ПРАЙМ: КАРКАС")
    assert m.entry.unique_name == "/a" and m.entry.name == "Rhino Prime Chassis" and m.score == 1.0
    assert cat.match("ЧЕРТЕЖ: РИНО ПРАИМ").entry.unique_name == "/b"  # small OCR slips
    assert cat.match("FORMA BLUEPRINT").entry.unique_name == "/c"


class FakeClient:
    """Serves a tiny German Public Export and dictionary."""

    def __init__(self, version="1"):
        self.version = version
        self.calls = 0

    def _index(self):
        names = [
            f"ExportResources_de.json!00_{self.version}",
            "ExportRecipes_de.json!00_x",
            "ExportWeapons_de.json!00_y",
        ]
        text = "\n".join(names).encode()
        raw = lzma.compress(text, format=lzma.FORMAT_ALONE)
        return raw

    def get(self, url, **_):
        self.calls += 1
        if url.endswith("index_de.txt.lzma"):
            return self._index()
        if "ExportResources" in url:
            return json.dumps(
                {
                    "ExportResources": [
                        {"uniqueName": "/R/RhinoPrimeChassisComponent", "name": "Rhino Prime: Chassis"}
                    ]
                }
            ).encode()
        if "ExportWeapons" in url:
            return json.dumps({"ExportWeapons": [{"uniqueName": "/W/Rhino", "name": "Rhino Prime"}]}).encode()
        if "ExportRecipes" in url:
            return json.dumps(
                {"ExportRecipes": [{"uniqueName": "/R/RhinoPrimeBlueprint", "resultType": "/W/Rhino"}]}
            ).encode()
        raise AssertionError(url)

    def get_json(self, url, **_):
        assert url.endswith("dict.de.json")
        return {languages.BLUEPRINT_KEY: "|ITEM| BLAUPAUSE"}


def test_build_and_cache_names(tmp_path: Path):
    client = FakeClient()
    names = languages.load_names(tmp_path, "de", client)
    assert names == {
        "/R/RhinoPrimeChassisComponent": "Rhino Prime: Chassis",
        "/W/Rhino": "Rhino Prime",
        "/R/RhinoPrimeBlueprint": "Rhino Prime BLAUPAUSE",
    }
    assert languages.load_names(tmp_path, "de") == names  # saved: no client needed
    calls = client.calls
    assert (
        languages.load_names(tmp_path, "de", client) == names and client.calls == calls
    )  # not fetched again
    assert languages.load_names(tmp_path, "en") == {} and languages.load_names(tmp_path, "xx") == {}


def test_offline_keeps_the_saved_table(tmp_path: Path):
    languages.load_names(tmp_path, "de", FakeClient())

    class Offline:
        def get(self, *a, **k):
            raise OSError("offline")

    assert languages.load_names(tmp_path, "de", Offline(), refresh=True)["/W/Rhino"] == "Rhino Prime"
    assert languages.load_names(tmp_path / "other", "de", Offline()) == {}


def test_every_language_has_an_ocr_tag():
    assert languages.ocr_tag("ja") == "ja-JP" and languages.ocr_tag("tc") == "zh-Hant"
    assert languages.ocr_tag("nope") == "en-US"
    assert set(languages.LANGUAGES) >= languages.CJK


def test_cjk_boxes_are_taller():
    from openwarframe.live import ocr

    latin = ocr.slot_boxes(1920, 1080, 4)[0]
    cjk = ocr.slot_boxes(1920, 1080, 4, cjk=True)[0]
    assert (cjk.bottom - cjk.top) > (latin.bottom - latin.top)


def test_setting_the_language(tmp_path: Path, monkeypatch):
    from openwarframe.app.server import AppState
    from openwarframe.config import Settings

    state = AppState(Settings(home=tmp_path))
    assert state.rewards.language == "en" and ["de", "Deutsch"] in state.reward_status()["languages"]
    assert "Unknown" in state.set_game_language("xx")["error"]
    monkeypatch.setattr(languages, "load_names", lambda home, lang, client=None, **_: {})
    assert "Could not download" in state.set_game_language("de")["error"]
    assert state.rewards.language == "en"  # unchanged when the names can't be had
    monkeypatch.setattr(languages, "load_names", lambda home, lang, client=None, **_: {"/x": "y"})
    st = state.set_game_language("de")
    assert "error" not in st and st["language"] == "de" and state.rewards.language == "de"
    assert AppState(Settings(home=tmp_path)).rewards.language == "de"  # kept across restarts
    state.save_prefs(b'{"settings": {"game_language": "ja"}}', from_page=True)  # the page can't set it
    assert state.get_prefs()["settings"]["game_language"] == "de"


def test_cli_follows_the_app_setting(tmp_path: Path):
    from openwarframe.config import Settings
    from openwarframe.live.cli import _ocr_lang

    s = Settings(home=tmp_path)
    assert _ocr_lang(s, None) == ("en-US", False)
    (tmp_path / "app-prefs.json").write_text('{"settings": {"game_language": "ko"}}')
    assert _ocr_lang(s, None) == ("ko-KR", True)
    assert _ocr_lang(s, "de-DE") == ("de-DE", True)


def test_page_offers_the_language():
    from openwarframe.app.server import page_source

    page = page_source()
    assert 'id="rw-lang"' in page and '"/api/reward/language"' in page


@pytest.mark.parametrize("lang", sorted(languages.LANGUAGES))
def test_sample_fonts_exist_for_each_script(lang):
    from openwarframe.live.synthetic import _font

    assert _font(20, lang) is not None
