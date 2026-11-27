"""A gun's base stats from the game data, the way the damage model needs them."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .mods import WeaponClass

# order of the 20 numbers in the export's damagePerShot (checked against named damage in
# warframe-public-export-plus behaviours)
DAMAGE_ORDER = (
    "impact",
    "puncture",
    "slash",
    "heat",
    "cold",
    "electricity",
    "toxin",
    "blast",
    "radiation",
    "gas",
    "magnetic",
    "viral",
    "corrosive",
    "void",
    "tau",
)
SLOTS = {"LongGuns": "PRIMARY", "Pistols": "SECONDARY"}


@dataclass
class Gun:
    unique_name: str
    name: str
    slot: str  # PRIMARY or SECONDARY
    holster: str | None
    parent: str | None
    damage: dict[str, float]  # per shot, by type
    crit_chance: float
    crit_multiplier: float
    status_chance: float
    fire_rate: float
    multishot: float
    magazine: int
    reload: float
    trigger: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(self.damage.values())

    @property
    def cls(self) -> WeaponClass:
        tags = set(self.tags)
        if self.trigger == "SEMI":
            tags.add("SEMI_AUTO")
        return WeaponClass(self.slot, self.holster, self.parent, self.name, tuple(sorted(tags)))


class NotAGun(ValueError):
    pass


def load_gun(conn: sqlite3.Connection, uid: str) -> Gun:
    row = conn.execute("SELECT name, data FROM item WHERE unique_name = ?", (uid,)).fetchone()
    if not row:
        raise NotAGun("That item isn't in the game data.")
    name, data = row
    d = json.loads(data or "{}")
    slot = SLOTS.get(str(d.get("productCategory")))
    dps = d.get("damagePerShot")
    if not slot or not isinstance(dps, list):
        raise NotAGun(f"{name} isn't a primary or secondary gun; builds cover those for now.")
    try:
        holster, parent, tags = conn.execute(
            "SELECT holster, parent, tags FROM weapon_class WHERE unique_name = ?", (uid,)
        ).fetchone() or (None, None, "[]")
    except sqlite3.OperationalError as exc:  # a game database from before builds
        raise NotAGun(
            "Update the game data first (Settings > Update game data): builds need newer data."
        ) from exc
    damage = {t: float(v) for t, v in zip(DAMAGE_ORDER, dps, strict=False) if v}
    return Gun(
        unique_name=uid,
        name=name,
        slot=slot,
        holster=holster,
        parent=parent,
        damage=damage,
        crit_chance=float(d.get("criticalChance") or 0),
        crit_multiplier=float(d.get("criticalMultiplier") or 1),
        status_chance=float(d.get("procChance") or 0),
        fire_rate=float(d.get("fireRate") or 1),
        multishot=float(d.get("multishot") or 1),
        magazine=int(d.get("magazineSize") or 1),
        reload=float(d.get("reloadTime") or 0),
        trigger=str(d.get("trigger") or ""),
        tags=json.loads(tags or "[]"),
    )
