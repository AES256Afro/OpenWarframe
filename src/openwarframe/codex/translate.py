"""Show item names in another language, after all the English-based logic has run.

Everything inside OpenWarframe works with English names (rules such as "Kuva weapons come
from a Lich" look at them), so translation happens at the very end, on what is shown:

- by uniqueName, where a row carries one (report items, components, usage);
- by exact English name elsewhere (part names in relic drops, Live rewards, how-to lists).
  Only whole names that are known items are replaced, so free text is never touched.

The English name stays available as ``name_en`` on app rows, so search finds both.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from pydantic import BaseModel

# dict keys that hold an item name (app data, Live, how-to, export tables)
NAME_KEYS = ("name", "part", "for", "relic", "what", "final_name", "item")
# list keys whose strings start with an item name followed by " · " or ": " (farm "gives")
LEAD_KEYS = ("gives", "sources")
_LEAD = re.compile(r"^(?P<name>.+?)(?P<rest>(?: · |: ).*)$")


class Translator:
    def __init__(self, lang: str, names: dict[str, str], english: dict[str, str]):
        """``names``: uniqueName -> name in ``lang``; ``english``: uniqueName -> English name."""
        self.lang = lang
        self.names = names
        self.by_english: dict[str, str] = {}
        for uid, en in english.items():
            local = names.get(uid)
            if en and local and en not in self.by_english:
                self.by_english[en] = local

    @classmethod
    def from_codex(cls, conn: sqlite3.Connection, lang: str, names: dict[str, str]) -> Translator:
        english = dict(conn.execute("SELECT unique_name, name FROM item"))
        for uid, name in conn.execute("SELECT unique_name, name FROM relic"):
            # the app and exports call relics "Lith R1" or "Lith R1 Relic"
            if uid in names:
                for key, en in ((uid + "#relic", name), (uid + "#relic-long", f"{name} Relic")):
                    english.setdefault(key, en)
                    names.setdefault(key, names[uid])
        # "<item> Blueprint", the way the app and exports name a recipe
        for rid, result in conn.execute("SELECT unique_name, result_item FROM recipe"):
            if rid in names and english.get(result):
                english.setdefault(rid + "#bp", f"{english[result]} Blueprint")
                names.setdefault(rid + "#bp", names[rid])
        try:
            for uid, name in conn.execute("SELECT unique_name, name FROM market_item"):
                english.setdefault(uid + "#market", name)
                if uid in names:
                    names.setdefault(uid + "#market", names[uid])
        except sqlite3.Error:
            pass
        return cls(lang, names, english)

    def __bool__(self) -> bool:
        return bool(self.names)

    def by_id(self, uid: str | None, fallback: str) -> str:
        return self.names.get(uid or "", fallback)

    def by_name(self, english: str) -> str:
        return self.by_english.get(english, english)

    # -- walkers ------------------------------------------------------------------------
    def strings(self, obj: Any) -> Any:
        """Translate item names in nested dicts and lists in place. Returns ``obj``."""
        if isinstance(obj, list):
            for x in obj:
                self.strings(x)
        elif isinstance(obj, dict):
            uid = obj.get("id") if isinstance(obj.get("id"), str) else obj.get("unique_name")
            for k in NAME_KEYS:
                v = obj.get(k)
                if not isinstance(v, str) or not v:
                    continue
                new = self.names.get(uid, "") if k == "name" and isinstance(uid, str) else ""
                new = new or self.by_name(v)
                if new != v:
                    if k == "name":
                        obj.setdefault("name_en", v)
                    obj[k] = new
            for k in LEAD_KEYS:
                v = obj.get(k)
                if isinstance(v, list):
                    obj[k] = [self._lead(x) if isinstance(x, str) else x for x in v]
            for k, v in obj.items():
                if isinstance(v, (dict, list)) and k not in LEAD_KEYS:
                    self.strings(v)
        return obj

    def _lead(self, s: str) -> str:
        m = _LEAD.match(s)
        if not m:
            return self.by_name(s)
        name = self.by_name(m["name"])
        return name + m["rest"] if name != m["name"] else s

    def model(self, m: BaseModel) -> BaseModel:
        """A translated deep copy of a report model (fields ``unique_name`` + ``name``)."""
        out = m.model_copy(deep=True)
        self._model(out)
        return out

    def _model(self, m: Any) -> None:
        if isinstance(m, BaseModel):
            uid = getattr(m, "unique_name", None)
            for field in type(m).model_fields:
                v = getattr(m, field)
                if isinstance(v, str) and field in NAME_KEYS and v:
                    new = self.by_id(uid, "") if field == "name" and uid else ""
                    new = new or self.by_name(v)
                    if new != v:
                        object.__setattr__(m, field, new)
                elif isinstance(v, (BaseModel, list, dict)):
                    self._model(v)
        elif isinstance(m, list):
            for x in m:
                self._model(x)
        elif isinstance(m, dict):
            for x in m.values():
                self._model(x)


def translator(home, conn: sqlite3.Connection, lang: str | None) -> Translator | None:
    """A translator for ``lang`` from the saved name table, or None (English, or no table yet)."""
    from .languages import load_names

    if not lang or lang == "en":
        return None
    names = load_names(home, lang)
    return Translator.from_codex(conn, lang, dict(names)) if names else None
