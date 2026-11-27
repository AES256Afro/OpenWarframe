"""Readable names for things the game only knows by internal path.

Vendors are stored under the game's manifest path ("/Lotus/Types/Game/VendorManifests/
Ostron/FishmongerVendorManifest") and their prices under the export's own keys
("credits", "platinum", "syndicate"...). Both are turned into words here, at read time,
so databases built by older versions show the same names without a rebuild.
"""

from __future__ import annotations

import re
import sqlite3

# Folder under VendorManifests/ -> where the vendor stands.
VENDOR_PLACES = {
    "Ostron": "Cetus",
    "Solaris": "Fortuna",
    "Deimos": "Necralisk",
    "Zariman": "Chrysalith",
    "EntratiLabs": "Sanctum Anatomica",
    "Duviri": "Dormizone",
    "Kahl": "Drifter's Camp",
    "TheHex": "Höllvania",
    "Hubs": "Relay",
}

# Vendors whose in-game name is not in their file name. Key: "<folder>/<file>".
KNOWN_VENDORS = {
    "Ostron/FishmongerVendorManifest": "Fisher Hai-Luk (Cetus)",
    "Ostron/ProspectorVendorManifest": "Old Man Suumbaat (Cetus)",
    "Ostron/ConservationRewardsManifest": "Master Teasonai (Cetus)",
    "Ostron/MaskSalesmanManifest": "Nakak (Cetus)",
    "Solaris/FishmongerVendorManifest": "The Business (Fortuna)",
    "Solaris/ConservationRewardsManifest": "The Business (Fortuna)",
    "Solaris/ProspectorVendorManifest": "Rude Zuud (Fortuna)",
    "Solaris/DebtTokenVendorManifest": "Ticker (Fortuna)",
    "Solaris/DebtTokenVendorRepossessionsManifest": "Ticker: repossessions (Fortuna)",
    "Solaris/NightcapVendorManifest": "Nightcap (Fortuna)",
    "Solaris/NightcapCosmeticVendorManifest": "Nightcap: cosmetics (Fortuna)",
    "Deimos/FishmongerVendorManifest": "Daughter (Necralisk)",
    "Deimos/ProspectorVendorManifest": "Father (Necralisk)",
    "Deimos/ConservationRewardsManifest": "Son (Necralisk)",
    "Deimos/PetVendorManifest": "Son (Necralisk)",
    "Deimos/HivemindTokenVendorManifest": "Grandmother (Necralisk)",
    "Deimos/OtakLastWishManifest": "Otak (Necralisk)",
    "Duviri/AcrithisVendorManifest": "Acrithis (Dormizone)",
    "Kahl/ChipperVendorManifest": "Chipper (Drifter's Camp)",
    "Hubs/HunhowVendorManifest": "Hunhow",
    "Hubs/TeshinHardModeVendorManifest": "Teshin: Steel Path Honors (Relay)",
    "Hubs/RailjackCrewMemberVendorManifest": "Ticker: Railjack crew (Fortuna)",
    "Hubs/GuildAdvertisementVendorManifest": "Clan advertising (Relay)",
    "Hubs/EliteAlertVendorManifest": "Elite alerts",
    "Events/RadioLegionDummyManifest": "Nightwave",
    "EntratiLabs/EntratiLabVendorManifest": "Cavia (Sanctum Anatomica)",
}

_INTERMISSION = re.compile(r"^RadioLegionIntermission(\d+)")
_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")
_NOISE = {"Vendor", "Manifest", "Products"}


def split_camel(text: str) -> str:
    """'RadioLegionIntermission10' -> 'Radio Legion Intermission 10'."""
    return " ".join(_WORDS.findall(text)) or text


def vendor_display_name(path: str | None) -> str:
    """A vendor's manifest path (or a bare file name) as players know it."""
    if not path:
        return "Vendor"
    parts = path.rstrip("/").split("/")
    file = parts[-1]
    folder = parts[-2] if len(parts) >= 2 else ""
    known = KNOWN_VENDORS.get(f"{folder}/{file}")
    if known:
        return known
    m = _INTERMISSION.match(file)
    if m:
        return f"Nightwave: Intermission {m.group(1)}"
    base = file.removesuffix("Manifest")
    words = [w for w in split_camel(base).split() if w not in _NOISE]
    if words[:2] == ["Radio", "Legion"]:
        words = ["Nightwave", *words[2:]]
    name = " ".join(words) or file
    place = VENDOR_PLACES.get(folder)
    if folder == "FocusSchools":
        return f"{name} focus school"
    return f"{name} ({place})" if place else name


# price key -> label. The Public Export+ uses credits / platinum / syndicate / focusXpCost;
# older databases and the world state use regularPrice / premiumPrice / primePrice.
PRICE_LABELS = {
    "credits": "Credits",
    "regularPrice": "Credits",
    "platinum": "Platinum",
    "premiumPrice": "Platinum",
    "primePrice": "Ducats",
    "ducats": "Ducats",
    "standing": "Standing",
}
FOCUS_SCHOOLS = {
    "AP_ATTACK": "Madurai",
    "AP_DEFENSE": "Vazarin",
    "AP_TACTIC": "Naramon",
    "AP_POWER": "Zenurik",
    "AP_WARD": "Unairu",
}


def price_label(key: str) -> str:
    """'premiumPrice' -> 'Platinum'; unknown keys are split into words."""
    return PRICE_LABELS.get(key) or split_camel(key[:1].upper() + key[1:])


def _amount(v) -> str | None:
    """A number, or a {minValue, maxValue} range, as text. None when it is neither."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,}"
    if isinstance(v, dict):
        lo, hi = _amount(v.get("minValue")), _amount(v.get("maxValue"))
        if lo and hi:
            return lo if lo == hi else f"{lo}–{hi}"
        return lo or hi
    return None


def price_parts(prices: dict, syndicate_names: dict[str, str] | None = None) -> list[str]:
    """Readable cost lines for a vendor offer's non-item prices ('500 Platinum')."""
    out: list[str] = []
    for key in ("credits", "regularPrice", "platinum", "premiumPrice", "primePrice", "standing"):
        amount = _amount(prices.get(key))
        if amount and amount != "0":
            out.append(f"{amount} {price_label(key)}")
    syn = prices.get("syndicate")
    if isinstance(syn, dict) and syn.get("tag"):
        name = (syndicate_names or {}).get(syn["tag"]) or split_camel(
            str(syn["tag"]).removesuffix("Syndicate")
        )
        cost = _amount(syn.get("standingCost"))
        rank = syn.get("minRank")
        bits = []
        if cost and cost != "0":
            bits.append(f"{cost} {name} Standing")
        if isinstance(rank, int) and rank > 0:
            bits.append(f"{name} rank {rank}")
        out.extend(bits)
    focus = prices.get("focusXpCost")
    if isinstance(focus, dict):
        amount = _amount(focus.get("cost"))
        if amount:
            school = FOCUS_SCHOOLS.get(str(focus.get("polarity")), "")
            out.append(f"{amount} {school} Focus".replace("  ", " "))
    return out


def display_name_for(conn: sqlite3.Connection, unique_name: str) -> str:
    """The best display name for any uniqueName the app may hold (goals, rewards...).

    Items and blueprints use the codex name; vendors their in-game name; anything unknown
    its last path segment split into words, never a raw path.
    """
    row = conn.execute("SELECT name FROM item WHERE unique_name = ?", (unique_name,)).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT i.name FROM recipe r JOIN item i ON i.unique_name = r.result_item WHERE r.unique_name = ?",
        (unique_name,),
    ).fetchone()
    if row:
        return f"{row[0]} Blueprint"
    row = conn.execute("SELECT name FROM relic WHERE unique_name = ?", (unique_name,)).fetchone()
    if row:
        return row[0]
    if "/VendorManifests/" in unique_name:
        return vendor_display_name(unique_name)
    row = conn.execute("SELECT name FROM challenge WHERE unique_name = ?", (unique_name,)).fetchone()
    if row:
        return row[0]
    tail = unique_name.rstrip("/").rsplit("/", 1)[-1]
    return split_camel(tail) if tail else unique_name
