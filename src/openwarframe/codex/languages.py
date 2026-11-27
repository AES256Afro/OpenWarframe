"""Item names in the game's other languages, for reading reward screens.

The reward screen prints names in the game client's language ("RHINO PRIME: CHASSIS" in
German). DE's Public Export is published per language (``index_<lang>.txt.lzma``) with
the same ``uniqueName`` keys, so one download gives every item's name in that language.
Recipes carry no name; their names come from the game's own "|ITEM| Blueprint" pattern,
which warframe-public-export-plus ships per language (``dict.<lang>.json``, key
``/Lotus/Language/Items/BlueprintAndItem``).

The table is kept in ``<data folder>/names/<lang>.json`` (about 1 MB), apart from the game
database, so rebuilding the database doesn't lose it. It is built again when the language's
Public Export changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from ..fsutil import atomic_write_text
from ..http import CachedClient
from ..sources.static.pe_plus import raw_base
from ..sources.static.public_export import (
    BASE,
    MANIFEST_URL,
    decode_index,
    manifest_base_name,
    parse_manifest_json,
)

log = logging.getLogger(__name__)

# game language code (DE's file suffix) -> (shown name, OCR language tag)
LANGUAGES: dict[str, tuple[str, str]] = {
    "en": ("English", "en-US"),
    "de": ("Deutsch", "de-DE"),
    "es": ("Español", "es-ES"),
    "fr": ("Français", "fr-FR"),
    "it": ("Italiano", "it-IT"),
    "ja": ("日本語", "ja-JP"),
    "ko": ("한국어", "ko-KR"),
    "pl": ("Polski", "pl-PL"),
    "pt": ("Português", "pt-BR"),
    "ru": ("Русский", "ru-RU"),
    "th": ("ไทย", "th-TH"),
    "tr": ("Türkçe", "tr-TR"),
    "uk": ("Українська", "uk-UA"),
    "zh": ("简体中文", "zh-Hans"),
    "tc": ("繁體中文", "zh-Hant"),
}
CJK = {"ja", "ko", "zh", "tc"}  # taller reward-name lines on screen
NAMED_MANIFESTS = (
    "ExportResources",
    "ExportWarframes",
    "ExportWeapons",
    "ExportSentinels",
    "ExportRelicArcane",
    "ExportUpgrades",
    "ExportGear",
    "ExportCustoms",
    "ExportKeys",
    "ExportDrones",
)
BLUEPRINT_KEY = "/Lotus/Language/Items/BlueprintAndItem"


def ocr_tag(lang: str) -> str:
    return LANGUAGES.get(lang, LANGUAGES["en"])[1]


def names_path(home: Path, lang: str) -> Path:
    return Path(home) / "names" / f"{lang}.json"


def build_names(client: CachedClient, lang: str, *, force: bool = False) -> dict:
    """{"lang", "version", "blueprint", "names": {uniqueName: name}} from DE's export for ``lang``."""
    if lang not in LANGUAGES or lang == "en":
        raise ValueError(f"no name table for {lang!r}")
    index = decode_index(client.get(BASE + f"index_{lang}.txt.lzma", max_age=3600, force=force))
    version = hashlib.sha1("\n".join(index).encode("utf-8")).hexdigest()[:12]
    names: dict[str, str] = {}
    recipes: list[dict] = []
    for file_name in index:
        base = manifest_base_name(file_name)
        if base not in (*NAMED_MANIFESTS, "ExportRecipes"):
            continue
        data = parse_manifest_json(client.get(MANIFEST_URL + file_name, max_age=30 * 86400).decode("utf-8"))
        for rows in data.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("uniqueName"), str):
                    continue
                if base == "ExportRecipes":
                    recipes.append(row)
                elif isinstance(row.get("name"), str) and row["name"].strip():
                    names[row["uniqueName"]] = row["name"].strip()
    pattern = client.get_json(raw_base("senpai") + f"dict.{lang}.json", max_age=7 * 86400).get(BLUEPRINT_KEY)
    if not isinstance(pattern, str) or "|ITEM|" not in pattern:
        pattern = "|ITEM|"  # unknown pattern: the item name alone still matches most of the read
    for r in recipes:
        made = names.get(str(r.get("resultType")))
        if made and r["uniqueName"] not in names:
            names[r["uniqueName"]] = pattern.replace("|ITEM|", made)
    return {"lang": lang, "version": version, "blueprint": pattern, "names": names}


def load_names(
    home: Path, lang: str, client: CachedClient | None = None, *, refresh: bool = False
) -> dict[str, str]:
    """{uniqueName: name} in ``lang``; empty for English (the game database has those).

    Uses the saved table; with a ``client`` it is built (or rebuilt, when ``refresh`` and DE's
    export for that language changed) and saved first. Without a client and no saved table:
    empty, and the caller falls back to English names.
    """
    if lang == "en" or lang not in LANGUAGES:
        return {}
    path = names_path(home, lang)
    saved: dict | None = None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = None
    if client is not None and (saved is None or refresh):
        try:
            fresh = build_names(client, lang)
            if saved is None or fresh["version"] != saved.get("version"):
                atomic_write_text(path, json.dumps(fresh, ensure_ascii=False))
            saved = fresh
        except Exception as exc:  # noqa: BLE001 - offline: keep what we have
            log.warning("could not get %s item names: %s", lang, exc)
    return dict((saved or {}).get("names") or {})
