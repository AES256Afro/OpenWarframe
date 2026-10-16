"""WFCD warframe-drop-data: DE's official drop tables, parsed to JSON (MIT).

https://github.com/WFCD/warframe-drop-data  ->  https://drops.warframestat.us/data/
"""

from __future__ import annotations

from dataclasses import dataclass

from ...http import CachedClient

BASE = "https://drops.warframestat.us/data/"
INFO_URL = BASE + "info.json"
ALL_URL = BASE + "all.json"


@dataclass
class DropData:
    version: str  # WFCD build hash
    modified: int  # DE page last-modified, epoch ms
    data: dict


def fetch_drops(client: CachedClient, *, force: bool = False) -> DropData:
    info = client.get_json(INFO_URL, max_age=3600, force=force)
    version = str(info.get("hash", "unknown"))
    # all.json is large; only refetch when the hash changes (cache key includes it)
    data = client.get_json(f"{ALL_URL}?v={version}", max_age=30 * 86400, force=force)
    return DropData(version=version, modified=int(info.get("modified", 0)), data=data)
