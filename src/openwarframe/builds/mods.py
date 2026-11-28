"""Gun mods as numbers: what each mod does at a rank, and which weapons it fits.

The game data gives a mod's effect per rank as text ("+165% Damage", "+90% <DT_FIRE_COLOR>Heat",
"x1.3 Damage to Grineer"). Those lines follow a small set of shapes, parsed here. A line like
"On Kill:" starts a conditional effect: the lines after it (Galvanized stacks, "when Aiming",
...) are kept apart, so a build can count them or not.

Only effects the damage model uses are parsed; others (recoil, zoom, ammo) are ignored, and
the mod is still usable but counts for nothing.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

# damage type tag in the mod text -> our name
DAMAGE_TAGS = {
    "IMPACT": "impact",
    "PUNCTURE": "puncture",
    "SLASH": "slash",
    "FIRE": "heat",
    "FREEZE": "cold",
    "ELECTRICITY": "electricity",
    "POISON": "toxin",
    "EXPLOSION": "blast",
    "RADIATION": "radiation",
    "GAS": "gas",
    "MAGNETIC": "magnetic",
    "VIRAL": "viral",
    "CORROSIVE": "corrosive",
}
PHYSICAL = ("impact", "puncture", "slash")
ELEMENTS = (
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
)
SIMPLE = {
    "Damage": "damage",
    "Melee Damage": "damage",
    "Attack Speed": "fire_rate",
    # melee mods that scale with the combo multiplier or with statuses on the target
    "Critical Chance stacks with Combo Multiplier": "combo_crit",
    "Status Chance per Combo Multiplier": "combo_status",
    "Melee Damage per Status Type affecting the target": "per_status_damage",
    # Galvanized Aptitude, Savvy, Shot: the same bonus as Condition Overload (wiki, 2026-11-28)
    "Direct Damage per Status Type affecting the target": "per_status_damage",
    "Multishot": "multishot",
    "Critical Chance": "crit_chance",
    "Critical Damage": "crit_damage",
    "Status Chance": "status_chance",
    "Status Damage": "status_damage",
    "Fire Rate": "fire_rate",
    "Magazine Capacity": "magazine",
    "Reload Speed": "reload",
    # heavy attacks (Killing Blow, Reflex Coil, wind-up mods)
    "Melee Damage on Heavy Attack": "heavy_damage",
    "Heavy Attack Wind Up Speed": "windup_speed",
    "Heavy Attack Efficiency": "heavy_efficiency",
    # headshots and weak points (wiki Enemy_Body_Parts, Target_Acquired, Primary_Acuity,
    # Meticulous_Aim, read 2026-11-28)
    "to Headshot Multiplier": "headshot_bonus",
    "Headshot Damage": "headshot_bonus",
    "Bodyshot Damage": "body_damage",
    "Weak Point Damage": "weak_point_damage",
    "Weak Point Critical Chance": "weak_point_crit",
}
# effects that only work on weak point or head hits: kept under "head:" and counted when aiming
# for the head
_HEAD_HEADER = re.compile(r"^On (?:Weak Point|Headshot)(?: Hit| Kill)?s?:$", re.IGNORECASE)
_FOR_SECONDS = re.compile(r" for \d+(?:\.\d+)?s$")
_NO_MULTISHOT = ". Multishot cannot be modified."
_ONLY_X = re.compile(r"\(x(?P<n>\d+(?:\.\d+)?) for (?P<what>Heavy Attacks|Bows)\)$")
_PCT = re.compile(
    r"^(?P<v>[+-]?\d+(?:\.\d+)?)% (?P<what>.+?)(?: \(x(?P<bow>\d+(?:\.\d+)?) for (?:Bows|Heavy Attacks)\))?$"
)
_TAG = re.compile(r"^<DT_(?P<tag>[A-Z]+)_COLOR>(?P<name>\w+)$")
_BANE = re.compile(r"^x(?P<v>\d+(?:\.\d+)?) Damage to (?P<faction>[\w ]+)$")
_STACKS = re.compile(r"^(?P<line>.+?) for \d+(?:\.\d+)?s\. Stacks up to (?P<n>\d+)x\.$")
_CONDITION = re.compile(r"^(On [^:]+|During [^:]+|While [^:]+):$|when Aiming|while ", re.IGNORECASE)
# mods for one weapon type, by their compat class's compatName in the export
GROUPS = {
    "Rifle": {"RIFLE", "SNIPER", "BOW", "WIDE_RIFLE", "LAUNCHER"},
    "Assault Rifle": {"RIFLE"},
    "Sniper": {"SNIPER"},
    "Bow": {"BOW"},
    "Shotgun": {"SHOTGUN"},
    "PRIMARY": {"RIFLE", "SNIPER", "BOW", "WIDE_RIFLE", "SHOTGUN", "LAUNCHER"},
}


def parse_line(line: str) -> tuple[str, float] | None:
    """One effect line -> (stat, value as a fraction or a multiplier bonus), or None."""
    line = line.strip()
    m = _BANE.match(line)
    if m:
        faction = m["faction"].strip().removeprefix("The ")
        faction = {"Sentients": "Sentient"}.get(faction, faction)
        return f"bane:{faction}", float(m["v"]) - 1
    m = _PCT.match(line)
    if not m:
        return None
    what, v = m["what"].strip(), float(m["v"]) / 100
    if what in SIMPLE:
        return SIMPLE[what], v
    t = _TAG.match(what)
    if t and t["tag"] in DAMAGE_TAGS:
        return DAMAGE_TAGS[t["tag"]], v
    return None


@dataclass
class ModEffect:
    stats: dict[str, float] = field(default_factory=dict)  # always on
    stacks: dict[str, tuple[float, int]] = field(default_factory=dict)  # per stack, max stacks
    conditional: list[str] = field(default_factory=list)  # other conditions we don't count


def parse_effect(lines: list[str]) -> ModEffect:
    out = ModEffect()
    conditional = head = False
    for raw in lines:
        for line in str(raw).split("\n"):
            line = line.strip()
            if not line or line == "<LINE_SEPARATOR>":
                continue
            if line.endswith(_NO_MULTISHOT):  # Primary / Pistol Acuity
                out.stats["lock_multishot"] = 1.0
                line = line.removesuffix(_NO_MULTISHOT)
            if _HEAD_HEADER.match(line):
                conditional, head = False, True
                continue
            if _CONDITION.search(line) and line.endswith(":"):
                conditional, head = True, False
                continue
            if head:
                _parse_head_line(out, line)
                continue
            s = _STACKS.match(line)
            if s:
                p = parse_line(s["line"])
                if p:
                    out.stacks[p[0]] = (p[1], int(s["n"]))
                else:
                    out.conditional.append(line)
                continue
            if conditional or _CONDITION.search(line):
                out.conditional.append(line)
                continue
            p = parse_line(line)
            if p:
                out.stats[p[0]] = out.stats.get(p[0], 0.0) + p[1]
                h = _ONLY_X.search(line)
                if h:  # "(x2 for Heavy Attacks)" / "(x2 for Bows)": the rest of the bonus, there only
                    k = f"{'heavy' if h['what'] == 'Heavy Attacks' else 'bow'}_{p[0]}"
                    out.stats[k] = out.stats.get(k, 0.0) + p[1] * (float(h["n"]) - 1)
    return out


def _parse_head_line(out: ModEffect, line: str) -> None:
    """A line under "On Weak Point Hit:" and the like. Aiming at heads keeps it up; "when Aiming"
    is taken as met (scopes)."""
    text = line.replace(" when Aiming", "")
    s = _STACKS.match(text)
    if s:
        p = parse_line(s["line"])
        if p:
            out.stacks["head:" + p[0]] = (p[1], int(s["n"]))
            return
    p = parse_line(_FOR_SECONDS.sub("", text))
    if p and "chance for" not in text:
        out.stats["head:" + p[0]] = out.stats.get("head:" + p[0], 0.0) + p[1]
    else:
        out.conditional.append(line)


@dataclass
class GunMod:
    unique_name: str
    name: str
    compat: str  # compatName: Rifle, Shotgun, Pistol, a weapon name for augments
    slot: str  # PRIMARY, SECONDARY or MELEE
    polarity: str | None
    base_drain: int
    max_rank: int
    rarity: str
    ranks: list[list[str]]  # effect text per rank
    exclusive: str = ""  # mods with the same key can't be equipped together
    needs_tags: tuple[str, ...] = ()  # the weapon must have all of these (SEMI_AUTO, BEAM...)
    bans_tags: tuple[str, ...] = ()  # and none of these (SINGLESHOT, AOE...)
    locks_fire_rate: bool = False  # "Fire Rate cannot be modified" (Cannonade mods)
    utility: bool = False  # can go in the Exilus slot (isUtility in the game data)

    def effect(self, rank: int | None = None) -> ModEffect:
        r = self.max_rank if rank is None else max(0, min(rank, self.max_rank))
        return parse_effect(self.ranks[r] if r < len(self.ranks) else [])

    def drain(self, rank: int | None = None) -> int:
        return self.base_drain + (self.max_rank if rank is None else rank)


# Galvanized and Primed mods replace their base mod (the game won't equip both)
EXCLUSIVE = {
    "Galvanized Chamber": "Split Chamber",
    "Galvanized Diffusion": "Barrel Diffusion",
    "Galvanized Hell": "Hell's Chamber",
    "Galvanized Shot": "",  # no base twin
}
SKIP_PATHS = ("/PvPMods/", "/Beginner/", "/Intermediate/", "/Rivens/", "/Randomized/")


def exclusive_key(name: str) -> str:
    if name in EXCLUSIVE and EXCLUSIVE[name]:
        return EXCLUSIVE[name]
    return name.removeprefix("Primed ").removeprefix("Amalgam ")


def load_gun_mods(conn: sqlite3.Connection) -> list[GunMod]:
    """Every primary and secondary mod in the game data (no Conclave, Flawed or Riven mods)."""
    try:
        tags = {
            u: (json.loads(c or "[]"), json.loads(i or "[]"))
            for u, c, i in conn.execute("SELECT * FROM mod_compat")
        }
    except sqlite3.OperationalError:
        tags = {}
    out = []
    for uid, name, data in conn.execute("SELECT unique_name, name, data FROM item WHERE category = 'Mod'"):
        if any(p in uid for p in SKIP_PATHS):
            continue
        # /Expert/ holds the Primed mods, plus unreleased copies that reuse the base mod's name
        if "/Expert/" in uid and not name.startswith("Primed "):
            continue
        try:
            d = json.loads(data or "{}")
        except ValueError:
            continue
        if d.get("type") not in ("PRIMARY", "SECONDARY", "MELEE") or not d.get("levelStats"):
            continue
        out.append(
            GunMod(
                unique_name=uid,
                name=name,
                compat=str(d.get("compatName") or ""),
                slot=d["type"],
                polarity=d.get("polarity"),
                base_drain=int(d.get("baseDrain") or 0),
                max_rank=int(d.get("fusionLimit") or 0),
                rarity=str(d.get("rarity") or ""),
                ranks=[list(x.get("stats") or []) for x in d["levelStats"]],
                exclusive=exclusive_key(name),
                needs_tags=tuple(tags.get(uid, ([], []))[0]),
                bans_tags=tuple(tags.get(uid, ([], []))[1]),
                locks_fire_rate="Fire Rate cannot be modified" in json.dumps(d.get("description") or ""),
                utility=bool(d.get("isUtility")),
            )
        )
    return out


@dataclass
class WeaponClass:
    slot: str  # PRIMARY or SECONDARY
    holster: str | None
    parent: str | None
    name: str
    tags: tuple[str, ...] = ()  # compatibilityTags plus SEMI_AUTO/AUTO from the trigger


def fits(mod: GunMod, w: WeaponClass) -> bool:
    """Can this mod go on this weapon?"""
    if mod.slot != w.slot:
        return False
    if any(t not in w.tags for t in mod.needs_tags) or any(t in w.tags for t in mod.bans_tags):
        return False
    c = mod.compat
    if w.slot == "SECONDARY":
        return c in ("Pistol", "SECONDARY") or _named(c, w)
    if w.slot == "MELEE":
        return c in ("Melee", "MELEE") or _named(c, w)
    if c in GROUPS:
        return (w.holster or "") in GROUPS[c]
    return _named(c, w)


def _named(compat: str, w: WeaponClass) -> bool:
    """A mod for one weapon family (augments, Sobek, Vulkar...): fits that weapon and its variants."""
    if not compat:
        return False
    base = re.sub(
        r"^(Prisma|Vandal|Wraith|Prime|Kuva|Tenet|Coda|Mk1-|Dex|Sancti|Secura|Synoid|Telos|Vaykor|Rakta) ",
        "",
        w.name,
    )
    base = re.sub(r" (Prime|Vandal|Wraith|Prisma)$", "", base)
    return compat.lower() in (w.name.lower(), base.lower())


# -- Riven mods: random stats, typed in as the game shows them --------------------------------
# wiki Riven_Mods (edited 2026-11-24): 2 or 3 positive stats and at most 1 negative; dispositions
# are retired (every weapon 1.2x), so the numbers on a maxed Riven are its final values.
RIVEN_MAX_RANK = 8
RIVEN_LINES = 4
_RIVEN_ALIASES = {
    "Rate of Fire": "Fire Rate",
    "Weakpoint Damage": "Weak Point Damage",
    "Weakpoint Critical Chance": "Weak Point Critical Chance",
    "Melee Damage on Heavy Attacks": "Melee Damage on Heavy Attack",
}
_PLAIN_TYPES = {v.title(): k for k, v in DAMAGE_TAGS.items()} | {
    "Heat": "FIRE",
    "Cold": "FREEZE",
    "Toxin": "POISON",
}
_PCT_FACTION = re.compile(r"^(?P<v>[+-]\d+(?:\.\d+)?)% Damage to (?P<faction>[\w ]+)$")


def riven_line(line: str) -> str:
    """One stat as a player reads it off the Riven ("+120.5% Toxin", "x0.62 Damage to Grineer")
    -> the shape mod text has in the game data."""
    line = re.sub(r"\s+", " ", line.strip().replace("−", "-").replace("×", "x").replace(",", "."))
    m = re.match(r"^(?P<v>[+-]?\d+(?:\.\d+)?)\s*% ?(?P<what>.+)$", line)
    if m:
        what = m["what"].strip()
        what = _RIVEN_ALIASES.get(what, what)
        bow = re.search(r" (\(x\d+(?:\.\d+)? for (?:Bows|Heavy Attacks)\))$", what)
        tail = " " + bow[1] if bow else ""
        core = what[: bow.start()] if bow else what
        if core in _PLAIN_TYPES:
            core = f"<DT_{_PLAIN_TYPES[core]}_COLOR>{core}"
        v = m["v"] if m["v"][0] in "+-" else "+" + m["v"]
        line = f"{v}% {core}{tail}"
        f = _PCT_FACTION.match(line)
        if f:  # "+45% Damage to Corpus" is x1.45
            return f"x{1 + float(f['v']) / 100:g} Damage to {f['faction']}"
    m = re.match(r"^(?P<v>\d+(?:\.\d+)?)\s*x (?P<rest>Damage to .+)$", line)  # "1.45x Damage to Corpus"
    if m:
        return f"x{m['v']} {m['rest']}"
    return line


def riven_mod(text: str, slot: str, drain: int = 18) -> tuple[GunMod, list[str]] | None:
    """A Riven from the stat lines a player typed. Returns the mod (at max rank) and the lines
    the damage model doesn't count (zoom, recoil, range...), or None when nothing was typed."""
    lines = [x.strip() for x in str(text or "").replace(";", "\n").split("\n") if x.strip()][:RIVEN_LINES]
    if not lines:
        return None
    game = [riven_line(x) for x in lines]
    unused = [raw for raw, g in zip(lines, game, strict=True) if parse_line(g) is None]
    drain = max(RIVEN_MAX_RANK, min(RIVEN_MAX_RANK + 18, int(drain)))
    mod = GunMod(
        unique_name="riven",
        name="Riven Mod",
        compat="",
        slot=slot,
        polarity=None,
        base_drain=drain - RIVEN_MAX_RANK,
        max_rank=RIVEN_MAX_RANK,
        rarity="Riven",
        ranks=[game] * (RIVEN_MAX_RANK + 1),
        exclusive="Riven Mod",
    )
    return mod, unused
