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


ORDERS_TOP = "https://api.warframe.market/v2/orders/item/{slug}/top"


def top_prices(client: CachedClient, slug: str, *, max_age: float = 6 * 3600) -> dict:
    """Lowest and typical (median of the five cheapest) sell price, and the best buy price.

    Raises on network trouble; values are None when nobody is selling or buying.
    """
    top = client.get_json(ORDERS_TOP.format(slug=slug), max_age=max_age).get("data", {})
    sells = sorted(order_prices(top.get("sell")))[:5]
    buys = sorted(order_prices(top.get("buy")), reverse=True)[:5]
    return {
        "low": sells[0] if sells else None,
        "typical": sells[len(sells) // 2] if sells else None,
        "buy": buys[0] if buys else None,
    }
