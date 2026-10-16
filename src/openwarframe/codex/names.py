"""Name normalization and the display-name -> uniqueName resolver.

Drop tables are keyed by display names ("Rhino Prime Chassis Blueprint"), the game's
own data by paths. The rule set here is deliberately small and explicit so that
unresolved names show up in reports instead of being guessed.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_QTY_PREFIX = re.compile(r"^\d[\d,]*\s*x\s+", re.IGNORECASE)  # "3X 1,500 Credits Cache"
_QTY_SUFFIX = re.compile(r"\s*\(x\d+\)$", re.IGNORECASE)  # "Fosfor Blau (x20) Blueprint"

RELIC_TIERS = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")

# Drop tables list currency as "80 Endo", "3,000 Credits Cache", "2X 10,000 Credits Cache".
# These map to pseudo items so rewards can still be joined and valued.
CURRENCY_ITEMS = {
    "endo": "/OpenWarframe/Currency/Endo",
    "credits": "/OpenWarframe/Currency/Credits",
}
_CURRENCY = re.compile(r"^(?:\d+x\s+)?(\d[\d,]*)\s+(endo|credits)(?:\s+cache)?$", re.IGNORECASE)


def parse_currency(name: str) -> tuple[str, int] | None:
    """'3,000 Credits Cache' -> (pseudo uniqueName, 3000); None if not currency."""
    m = _CURRENCY.match(normalize(name))
    if not m:
        return None
    return CURRENCY_ITEMS[m.group(2).lower()], int(m.group(1).replace(",", ""))


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


class NameResolver:
    """Resolves display names to uniqueNames using maps built from the exports."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}  # normalized name -> item uniqueName
        self.recipes_by_result_name: dict[str, str] = {}  # normalized result name -> recipe uniqueName
        self.relics: dict[str, str] = {}  # "lith r2" -> relic uniqueName
        self.unresolved: dict[str, tuple[int, str]] = {}

    def add_item(self, name: str, unique_name: str) -> None:
        key = normalize(strip_decorations(name))
        # first writer wins: the official export is loaded before community data
        self.items.setdefault(key, unique_name)

    def add_recipe(self, result_name: str, recipe_unique_name: str) -> None:
        self.recipes_by_result_name.setdefault(normalize(strip_decorations(result_name)), recipe_unique_name)

    def add_relic(self, short_name: str, unique_name: str, *, prefer: bool = False) -> None:
        key = normalize(short_name)
        if prefer or key not in self.relics:
            self.relics[key] = unique_name

    def resolve(self, display_name: str, *, source: str = "") -> str | None:
        raw = display_name
        name = _QTY_PREFIX.sub("", display_name)
        name = _QTY_SUFFIX.sub("", name)
        key = normalize(name)

        currency = parse_currency(key)
        if currency:
            return currency[0]

        if key.endswith(" blueprint"):
            base = key[: -len(" blueprint")]
            if base in self.recipes_by_result_name:
                return self.recipes_by_result_name[base]
            # "Forma Blueprint": the blueprint is itself an item named exactly like this
            if key in self.items:
                return self.items[key]
            if base in self.items:
                # component blueprint whose result name equals the item name
                return self.items[base]
        if key in self.items:
            return self.items[key]
        if key.endswith(" relic"):
            short = key[: -len(" relic")]
            if short in self.relics:
                return self.relics[short]
        parts = key.split(" ")
        if len(parts) >= 2 and parts[0] in (t.lower() for t in RELIC_TIERS):
            short = " ".join(parts[:2])
            if short in self.relics:
                return self.relics[short]

        count, _ = self.unresolved.get(raw, (0, source))
        self.unresolved[raw] = (count + 1, source)
        return None
