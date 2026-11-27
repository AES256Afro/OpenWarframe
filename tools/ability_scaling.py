"""Build kb/builds/abilities.json: which stats each Warframe ability scales with.

Facts only (does an ability have a Strength / Duration / Range value; its energy cost; is it
channeled), taken from Warframe Wiki pages: each ability page's AbilityU10.3 template and
Module:Ability/data. The wiki is CC BY-NC-SA 3.0 (https://wiki.warframe.com, Weird Gloop);
the output keeps the attribution and the page edit dates.

The wiki's terms don't allow automated access without consent, so OpenWarframe never fetches
it while running. This script reads page sources saved by hand:

    uv run python tools/ability_scaling.py <folder with batch*.json> <Module_Ability_data.lua> \
        <Module_Warframes_data.lua>

``batch*.json`` are MediaWiki API query results (pages with revisions, main slot content).
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).parents[1] / "kb" / "builds" / "abilities.json"
FIELD = re.compile(r"^\|\s*(\w+)\s*=\s*(.*?)\s*$", re.M)
EMPTY = {"", "n/a", "na", "-", "none", "{{{1|}}}"}


def pages(folder: str) -> dict[str, tuple[str, str]]:
    out = {}
    for f in sorted(glob.glob(str(Path(folder) / "batch*.json"))):
        q = json.loads(Path(f).read_text(encoding="utf-8"))["query"]["pages"]
        for p in q.values() if isinstance(q, dict) else q:
            r = p.get("revisions") or []
            if r:
                main = r[0]["slots"]["main"]
                out[p["title"]] = (main.get("*") or main.get("content") or "", r[0].get("timestamp", ""))
    return out


def template(text: str) -> dict[str, str] | None:
    i = text.find("{{AbilityU10.3")
    if i < 0:
        return None
    block = text[i : text.find("|info", i) if "|info" in text[i:] else i + 4000]
    return {k.lower(): v for k, v in FIELD.findall(block)}


def module_abilities(lua: str) -> dict[str, dict]:
    """Name -> {Powersuit, Key, InternalName, IsChanneled} for current (not Archived) abilities."""
    archived = lua.find("Archived = {")
    current = lua.find("\n\tAbilities", archived) if archived >= 0 else 0
    body = lua[current:] if current > 0 else lua
    out = {}
    for m in re.finditer(r'\["([^"]+)"\]\s*=\s*\{(.*?)\n\t\t\}', body, re.S):
        fields = dict(re.findall(r"(\w+)\s*=\s*\"?([^\",\n]+)\"?,?", m.group(2)))
        if "Powersuit" in fields:
            out[m.group(1)] = fields
    return out


def module_frames(lua: str) -> list[dict]:
    """Each frame's current abilities (in key order) and its internal name."""
    out = []
    for m in re.finditer(
        r"\n\t\t(?:\[\"([^\"]+)\"\]|(\w+)) = \{\n\t\t\tAbilities = \{([^}]*)\}(.*?)\n\t\t\}", lua, re.S
    ):
        name = m.group(1) or m.group(2)
        abilities = re.findall(r'"([^"]+)"', m.group(3))
        internal = re.search(r'InternalName = "([^"]+)"', m.group(4))
        if abilities and internal:
            stats = {}
            for k in ("Health", "Shield", "Armor", "Energy"):
                v = re.search(rf"\n\t\t\t{k} = ([\d.]+)", m.group(4))
                if v:
                    stats[k.lower()] = float(v.group(1))
            out.append({"frame": name, "unique_name": internal.group(1), "abilities": abilities, **stats})
    return out


def main(folder: str, lua_path: str, frames_path: str) -> None:
    lua = Path(lua_path).read_text(encoding="utf-8")
    mod = module_abilities(lua)
    frames = module_frames(Path(frames_path).read_text(encoding="utf-8"))
    rows = []
    for title, (text, edited) in pages(folder).items():
        t = template(text)
        if not t or title not in mod:
            continue
        m = mod[title]

        def has(k: str, t: dict = t) -> bool:
            v = re.sub(r"<[^>]+>", "", t.get(k, "")).strip().lower()
            return v not in EMPTY

        try:
            energy = float(re.findall(r"\d+(?:\.\d+)?", t.get("energy", ""))[0])
        except IndexError:
            energy = 0.0
        rows.append(
            {
                "frame": m["Powersuit"].strip(),
                "ability": title,
                "key": int(m.get("Key", "0") or 0),
                "unique_name": m.get("InternalName", "").strip(),
                "energy": energy,
                "channeled": m.get("IsChanneled", "").strip() == "true",
                "strength": has("strength"),
                "duration": has("duration"),
                "range": has("range"),
                "page_edited": edited[:10],
            }
        )
    rows.sort(key=lambda r: (r["frame"], r["key"], r["ability"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "source": "Warframe Wiki (https://wiki.warframe.com), ability pages and Module:Ability/data",
                "license": "CC BY-NC-SA 3.0; facts extracted (which stats an ability scales with), see docs/LEGAL.md",
                "last_verified": "2026-11-27",
                "abilities": rows,
                "frames": frames,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(rows)} abilities, {len(frames)} frames -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
