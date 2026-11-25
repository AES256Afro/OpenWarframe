"""Name normalization and the display-name -> uniqueName resolver.

Drop tables are keyed by display names ("Rhino Prime Chassis Blueprint"), the game's
own data by paths. The rule set here is deliberately small and explicit so that
unresolved names show up in reports instead of being guessed: an exact match always
wins, and each fallback below undoes one way drop tables are known to decorate names.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_WS = re.compile(r"\s+")
_QTY_PREFIX = re.compile(r"^\d[\d,]*\s*x\s+", re.IGNORECASE)  # "3X 1,500 Credits Cache"
# Quantity markers after the name, at the end or in front of " Blueprint":
# "Fosfor Blau (x20) Blueprint", "Vosfor Cache (200x)", "Adramal Alloy X20 Blueprint".
_QTY_SUFFIX = re.compile(r"\s*\((?:x\s*\d+|\d+\s*x)\)(?=$|\s+blueprint$)", re.IGNORECASE)
_QTY_BARE = re.compile(r"\s+x\d+(?=\s+blueprint$)", re.IGNORECASE)
_FOOTNOTE = re.compile(r"[*†]+$")  # "Omni Forma*"

RELIC_TIERS = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")

# Drop tables list currency as "80 Endo", "3,000 Credits Cache", "2X 10,000 Credits Cache".
# These map to pseudo items so rewards can still be joined and valued.
CURRENCY_ITEMS = {
    "endo": "/OpenWarframe/Currency/Endo",
    "credits": "/OpenWarframe/Currency/Credits",
}
_CURRENCY = re.compile(r"^(?:\d+x\s+)?(\d[\d,]*)\s+(endo|credits)(?:\s+cache)?$", re.IGNORECASE)
# The Index lists its credit payouts as "Return: 105,000".
_INDEX_RETURN = re.compile(r"^return:\s*(\d[\d,]*)$", re.IGNORECASE)

# Fallback rewrites, each undoing one decoration drop tables add to export names.
_QUALIFIER = re.compile(r"\s*\([^()]*\)$")  # "Abating Link (Trinity)", "Bhisaj-Bal(Paris Prime)"
_CACHE = re.compile(r"^(?:\d[\d,]*\s+)?(.+?)\s+cache$")  # "Vosfor Cache" -> "vosfor"
_ARTICLE = re.compile(r"^the\s+")  # "The Perrin Sequence Stencil"
_CLASS_WORD = re.compile(r"\s+(?:necramech|archwing|warframe)(?=$|\s+blueprint$)")  # "Voidrig Necramech"
# Export names carry a type word the drop tables leave off: "Hood Display Black
# Decoration" is listed as "Hood Display Black", "Seeker of Truth Honoria" as "Seeker of Truth".
_TYPE_SUFFIXES = (" decoration", " honoria")
_BLUEPRINT = " blueprint"

# Short names in drop tables that no rule can derive from the export name.
ALIASES = {
    "ducats": "orokin ducats",  # "1000X Ducats"
}
# Words the drop tables spell differently from the exports.
SPELLINGS = {
    "ventikid": "ventkid",  # "Kubrodon Ventikid Cuirass Blueprint" (Ventkids syndicate cosmetics)
}


def parse_currency(name: str) -> tuple[str, int] | None:
    """'3,000 Credits Cache' -> (pseudo uniqueName, 3000); None if not currency."""
    n = normalize(name)
    m = _CURRENCY.match(n)
    if m:
        return CURRENCY_ITEMS[m.group(2).lower()], int(m.group(1).replace(",", ""))
    m = _INDEX_RETURN.match(n)
    if m:
        return CURRENCY_ITEMS["credits"], int(m.group(1).replace(",", ""))
    return None


def normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip decorative markers."""
    n = name.strip().lower()
    n = n.replace("’", "'")
    n = _WS.sub(" ", n)
    return n


def strip_store_prefix(path: str) -> str:
    """``/Lotus/StoreItems/Types/...`` -> ``/Lotus/Types/...``."""
    return path.replace("/Lotus/StoreItems/", "/Lotus/", 1)


def strip_decorations(name: str) -> str:
    """Remove ``<ARCHWING>`` style prefixes DE puts in some display names."""
    return re.sub(r"^<[A-Z_ ]+>\s*", "", name).strip()


def _compact(key: str) -> str:
    return key.replace(" ", "")


def _strip_cache(key: str) -> str:
    m = _CACHE.match(key)
    return m.group(1) if m else key


_REWRITES = (
    lambda s: _QUALIFIER.sub("", s),
    _strip_cache,
    lambda s: _ARTICLE.sub("", s),
    lambda s: _CLASS_WORD.sub("", s),
    lambda s: ALIASES.get(s, s),
    lambda s: " ".join(SPELLINGS.get(w, w) for w in s.split(" ")),
)


def _stems(key: str) -> list[str]:
    """The key plus every combination of the stripping rewrites, most literal first."""
    stems = [key]
    for rewrite in _REWRITES:
        for s in list(stems):
            r = rewrite(s).strip()
            if r and r not in stems:
                stems.append(r)
    return stems


def _inflections(stem: str) -> Iterator[str]:
    """Singular/plural of the last word ("Universal Medallions", "Keratinos Blade
    Blueprint") and the type words drop tables omit."""
    base, bp = (stem[: -len(_BLUEPRINT)], _BLUEPRINT) if stem.endswith(_BLUEPRINT) else (stem, "")
    yield (base[:-1] if base.endswith("s") else base + "s") + bp
    for suffix in _TYPE_SUFFIXES:
        yield stem + suffix


class NameResolver:
    """Resolves display names to uniqueNames using maps built from the exports."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}  # normalized name -> item uniqueName
        self.recipes_by_result_name: dict[str, str] = {}  # normalized result name -> recipe uniqueName
        self.relics: dict[str, str] = {}  # "lith r2" -> relic uniqueName
        self.compact: dict[str, str] = {}  # normalized name without spaces -> item uniqueName
        self.unresolved: dict[str, tuple[int, str]] = {}

    def add_item(self, name: str, unique_name: str) -> None:
        key = normalize(strip_decorations(name))
        # first writer wins: the official export is loaded before community data
        self.items.setdefault(key, unique_name)
        self.compact.setdefault(_compact(key), unique_name)

    def add_recipe(self, result_name: str, recipe_unique_name: str) -> None:
        self.recipes_by_result_name.setdefault(normalize(strip_decorations(result_name)), recipe_unique_name)

    def add_relic(self, short_name: str, unique_name: str, *, prefer: bool = False) -> None:
        key = normalize(short_name)
        if prefer or key not in self.relics:
            self.relics[key] = unique_name

    def _lookup(self, key: str) -> str | None:
        if key.endswith(_BLUEPRINT):
            base = key[: -len(_BLUEPRINT)]
            if base in self.recipes_by_result_name:
                return self.recipes_by_result_name[base]
            # "Forma Blueprint": the blueprint is itself an item named exactly like this
            if key in self.items:
                return self.items[key]
            if base in self.items:
                # component blueprint whose result name equals the item name
                return self.items[base]
        return self.items.get(key)

    def resolve(self, display_name: str, *, source: str = "") -> str | None:
        raw = display_name
        name = _FOOTNOTE.sub("", display_name.strip())
        name = _QTY_PREFIX.sub("", name)
        name = _QTY_SUFFIX.sub("", name)
        name = _QTY_BARE.sub("", name)
        key = normalize(name)

        currency = parse_currency(key)
        if currency:
            return currency[0]

        # Relics first: every refinement variant shares the display name, and the
        # relic table's canonical variant must win over the generic item map.
        parts = key.split(" ")
        if len(parts) >= 2 and parts[0] in (t.lower() for t in RELIC_TIERS):
            short = " ".join(parts[:2])
            if short in self.relics and (len(parts) == 2 or parts[2].startswith(("relic", "("))):
                return self.relics[short]

        found = self._lookup(key)
        if found:
            return found

        stems = _stems(key)
        for candidate in [*stems[1:], *(i for s in stems for i in _inflections(s))]:
            found = self._lookup(candidate)
            if found:
                return found
        # last resort: spacing differs ("AstralBond (companion)")
        for s in stems:
            if _compact(s) in self.compact:
                return self.compact[_compact(s)]

        count, _ = self.unresolved.get(raw, (0, source))
        self.unresolved[raw] = (count + 1, source)
        return None


# World-state mission codes -> the names the game shows (WFCD warframe-worldstate-data).
MISSION_TYPES = {
    "MT_ASSASSINATION": "Assassination",
    "MT_EXTERMINATION": "Exterminate",
    "MT_SURVIVAL": "Survival",
    "MT_RESCUE": "Rescue",
    "MT_SABOTAGE": "Sabotage",
    "MT_CAPTURE": "Capture",
    "MT_INTEL": "Spy",
    "MT_DEFENSE": "Defense",
    "MT_MOBILE_DEFENSE": "Mobile Defense",
    "MT_TERRITORY": "Interception",
    "MT_RETRIEVAL": "Hijack",
    "MT_HIVE": "Hive",
    "MT_EXCAVATE": "Excavation",
    "MT_SALVAGE": "Infested Salvage",
    "MT_ARENA": "Rathuum",
    "MT_PURSUIT": "Pursuit",
    "MT_RACE": "Rush",
    "MT_SECTOR": "Dark Sector",
    "MT_EVACUATION": "Defection",
    "MT_ASSAULT": "Assault",
    "MT_ARTIFACT": "Disruption",
    "MT_LANDSCAPE": "Free Roam",
    "MT_JUNCTION": "Junction",
    "MT_CORRUPTION": "Void Flood",
    "MT_VOID_CASCADE": "Void Cascade",
    "MT_ARMAGEDDON": "Void Armageddon",
    "MT_ALCHEMY": "Alchemy",
    "MT_ASCENSION": "Ascension",
    "MT_DEFAULT": "",
}


def mission_label(value: str | None) -> str:
    """One spelling for a mission type, whatever the source.

    The world state uses codes (MT_ARTIFACT is Disruption, MT_CORRUPTION is Void Flood),
    the node list uses capitals (MOBILE DEFENSE) and the drop tables use title case.
    """
    if not value:
        return ""
    if value.startswith("MT_"):
        return MISSION_TYPES.get(value, value.removeprefix("MT_").replace("_", " ").title())
    return value.title() if value.isupper() else value
