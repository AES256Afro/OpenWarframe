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


def price_basis(tags) -> dict:
    """What to price an item at, from its warframe.market tags.

    Players mostly hold mods and arcanes unranked and relics intact, so those are priced
    at rank 0 and Intact; a maxed mod or a Radiant relic sells for much more and would
    make every copy look worth that.
    """
    tags = set(tags or [])
    if tags & {"mod", "arcane_enhancement"}:
        return {"rank": 0}
    if "relic" in tags:
        return {"subtype": "intact"}
    return {}


def _matches(order, rank: int | None, subtype: str | None) -> bool:
    if not isinstance(order, dict):
        return False
    if rank is not None and order.get("rank", 0) != rank:  # v2 leaves rank out of unranked orders
        return False
    return subtype is None or order.get("subtype") in (None, subtype)


def top_prices(
    client: CachedClient,
    slug: str,
    *,
    rank: int | None = None,
    subtype: str | None = None,
    max_age: float = 6 * 3600,
) -> dict:
    """Lowest and typical (median of the five cheapest) sell price, and the best buy price.

    ``rank`` / ``subtype``: only orders for that mod rank or relic refinement ("intact").
    The filter is sent to warframe.market and applied again here, so a server that ignores
    it can't mix a maxed mod into an unranked price. ``basis`` says what was priced.
    Raises on network trouble; values are None when nobody is selling or buying.
    """
    query = []
    if rank is not None:
        query.append(f"rank={int(rank)}")
    if subtype:
        query.append(f"subtype={subtype}")
    url = ORDERS_TOP.format(slug=slug) + ("?" + "&".join(query) if query else "")
    top = client.get_json(url, max_age=max_age).get("data", {})
    if not isinstance(top, dict):
        top = {}

    def pick(side: str) -> list:
        orders = top.get(side)
        return [o for o in orders if _matches(o, rank, subtype)] if isinstance(orders, list) else []

    sells = sorted(order_prices(pick("sell")))[:5]
    buys = sorted(order_prices(pick("buy")), reverse=True)[:5]
    basis = f"rank {rank}" if rank is not None else (subtype or None)
    return {
        "low": sells[0] if sells else None,
        "typical": sells[len(sells) // 2] if sells else None,
        "buy": buys[0] if buys else None,
        "basis": basis,
    }
