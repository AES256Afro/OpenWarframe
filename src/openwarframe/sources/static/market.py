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
