"""warframe.market v2 item list.

Each item carries ``gameRef`` (the game's uniqueName) and a ``slug`` for later price
lookups. Docs: https://warframe.market/api_docs
"""

from __future__ import annotations

from dataclasses import dataclass

from ...http import CachedClient

ITEMS_URL = "https://api.warframe.market/v2/items"


@dataclass
class MarketItem:
    unique_name: str
    slug: str
    name: str
    tags: list[str]


def fetch_market_items(client: CachedClient, *, force: bool = False) -> list[MarketItem]:
    payload = client.get_json(ITEMS_URL, max_age=86400, force=force)
    out: list[MarketItem] = []
    for it in payload.get("data", []):
        ref = it.get("gameRef")
        if not ref:
            continue
        name = (it.get("i18n", {}).get("en", {}) or {}).get("name") or it.get("slug", "")
        out.append(
            MarketItem(unique_name=ref, slug=it.get("slug", ""), name=name, tags=list(it.get("tags", [])))
        )
    return out


def order_prices(orders) -> list[float]:
    """Platinum prices from a warframe.market order list, ignoring anything not a number.

    The prices are shown in the app, so a malformed or hostile response must not be able
    to put text there.
    """
    out: list[float] = []
    for o in orders if isinstance(orders, list) else []:
        v = o.get("platinum") if isinstance(o, dict) else None
        if isinstance(v, int | float) and not isinstance(v, bool) and v == v and abs(v) != float("inf"):
            out.append(v)
    return out
