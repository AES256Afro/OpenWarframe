"""Parse the game's inventory JSON (the document the client receives from inventory.php).

Field reference: SpaceNinjaServer ``IInventoryClient``. Only the sections the app needs
are read; everything else is ignored, so newer game versions keep working.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Arrays that hold built equipment (each entry has ItemType and usually XP).
EQUIPMENT_SECTIONS = (
    "Suits",
    "LongGuns",
    "Pistols",
    "Melee",
    "SpaceSuits",
    "SpaceGuns",
    "SpaceMelee",
    "Sentinels",
    "SentinelWeapons",
    "KubrowPets",
    "MoaPets",
    "MechSuits",
    "Hoverboards",
    "OperatorAmps",
    "CrewShipHarnesses",
    "CrewShips",
)

REFINEMENTS = (("Platinum", "Radiant"), ("Gold", "Flawless"), ("Silver", "Exceptional"), ("Bronze", "Intact"))


def refinement_of(relic_path: str) -> str:
    for suffix, label in REFINEMENTS:
        if relic_path.endswith(suffix):
            return label
    return "Intact"


def relic_base(relic_path: str) -> str:
    """Canonical relic id used by the codex (the Intact / Bronze variant)."""
    for suffix, _ in REFINEMENTS:
        if relic_path.endswith(suffix):
            return relic_path[: -len(suffix)] + "Bronze"
    return relic_path


@dataclass
class Inventory:
    loaded_at: datetime
    source: str
    equipment: dict[str, int] = field(default_factory=dict)  # uniqueName -> copies built
    equipment_xp: dict[str, int] = field(default_factory=dict)  # uniqueName -> highest XP seen
    misc: dict[str, int] = field(default_factory=dict)  # MiscItems: resources, parts, relics
    recipes: dict[str, int] = field(default_factory=dict)  # owned blueprints
    relics: dict[str, dict[str, int]] = field(default_factory=dict)  # canonical relic -> refinement -> count
    pending: list[dict] = field(default_factory=list)  # foundry queue
    credits: int | None = None
    platinum: int | None = None
    endo: int | None = None
    regal_aya: int | None = None
    mods: dict[str, dict] = field(default_factory=dict)  # uniqueName -> {"unranked": n, "ranks": [lvl, ...]}

    def owns(self, unique_name: str) -> bool:
        return self.equipment.get(unique_name, 0) > 0

    def count(self, unique_name: str) -> int:
        return (
            self.misc.get(unique_name, 0)
            + self.recipes.get(unique_name, 0)
            + self.equipment.get(unique_name, 0)
        )


def _date(v) -> str | None:
    try:
        ms = int(v["$date"]["$numberLong"])
        return datetime.fromtimestamp(ms / 1000, UTC).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def parse_inventory(data: dict, *, source: str = "file") -> Inventory:
    if "Suits" not in data and "MiscItems" not in data:
        raise ValueError("this does not look like a Warframe inventory (no Suits or MiscItems section)")
    inv = Inventory(loaded_at=datetime.now(UTC), source=source)
    for section in EQUIPMENT_SECTIONS:
        for e in data.get(section) or []:
            t = e.get("ItemType")
            if not t:
                continue
            inv.equipment[t] = inv.equipment.get(t, 0) + 1
            inv.equipment_xp[t] = max(inv.equipment_xp.get(t, 0), int(e.get("XP") or 0))
    for e in data.get("MiscItems") or []:
        t, n = e.get("ItemType"), int(e.get("ItemCount") or 0)
        if not t or n <= 0:
            continue
        inv.misc[t] = inv.misc.get(t, 0) + n
        if "/Projections/" in t:
            base = relic_base(t)
            inv.relics.setdefault(base, {})
            ref = refinement_of(t)
            inv.relics[base][ref] = inv.relics[base].get(ref, 0) + n
    for e in data.get("Recipes") or []:
        t, n = e.get("ItemType"), int(e.get("ItemCount") or 0)
        if t and n > 0:
            inv.recipes[t] = inv.recipes.get(t, 0) + n
    for e in data.get("PendingRecipes") or []:
        inv.pending.append({"recipe": e.get("ItemType"), "ready_at": _date(e.get("CompletionDate"))})
    for e in data.get("RawUpgrades") or []:
        t, n = e.get("ItemType"), int(e.get("ItemCount") or 0)
        if t and n > 0:
            inv.mods.setdefault(t, {"unranked": 0, "ranks": []})["unranked"] += n
    for e in data.get("Upgrades") or []:
        t = e.get("ItemType")
        if not t:
            continue
        try:
            lvl = int(json.loads(e.get("UpgradeFingerprint") or "{}").get("lvl", 0))
        except (ValueError, AttributeError, TypeError):
            lvl = 0
        inv.mods.setdefault(t, {"unranked": 0, "ranks": []})["ranks"].append(lvl)
    # wallet values end up on screen: only whole numbers get through, whatever the file says
    inv.endo = _amount(data.get("FusionPoints"))
    inv.regal_aya = _amount(data.get("PrimeTokens"))
    inv.credits = _amount(data.get("RegularCredits"))
    paid, free = _amount(data.get("PremiumCredits")), _amount(data.get("PremiumCreditsFree"))
    inv.platinum = None if paid is None and free is None else (paid or 0) + (free or 0)
    return inv


def _amount(v) -> int | None:
    """A wallet amount as an int, or None when it is missing or not a number."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v and abs(v) != float("inf"):
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    if isinstance(v, dict):  # MongoDB-style {"$numberLong": "123"}
        return _amount(v.get("$numberLong") or v.get("$numberInt"))
    return None


def unwrap(data):
    """The inventory itself. Some tools wrap it as {"InventoryJson": <object or JSON text>}."""
    if isinstance(data, dict) and "InventoryJson" in data:
        raw = data["InventoryJson"]
        return json.loads(raw) if isinstance(raw, str) else raw
    return data


def load_inventory(path: Path) -> Inventory:
    data = unwrap(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    return parse_inventory(data, source=str(path))
