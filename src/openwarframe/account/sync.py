"""Take a snapshot from the configured sources."""

from __future__ import annotations

from pathlib import Path

from ..codex.queries import Codex
from ..config import Settings
from ..http import CachedClient
from ..sources.account.profile import ProfileError, fetch_profile
from .model import Snapshot
from .parse import parse_profile
from .store import SnapshotStore


def sync_profile(
    settings: Settings, *, force: bool = False, skip_unchanged: bool = True
) -> tuple[Snapshot, Path, bool]:
    """Fetch, parse and store a snapshot.

    Returns ``(snapshot, path, written)``. When the profile payload is identical to the
    latest stored snapshot (the endpoint caches for about 10 minutes) nothing new is
    written and the previous path is returned.
    """
    if not settings.account_id:
        raise ProfileError("no account id configured; run `openwarframe account howto`")
    client = CachedClient(settings.cache_dir)
    try:
        data = fetch_profile(client, settings.account_id, settings.platform, force=force)
    finally:
        client.close()
    codex = Codex(settings.codex_path) if settings.codex_path.exists() else None
    try:
        snapshot = parse_profile(data, platform=settings.platform, codex=codex)
    finally:
        if codex:
            codex.close()
    store = SnapshotStore(settings.snapshots_dir)
    if skip_unchanged:
        paths = store.list()
        if paths:
            previous = store.load(paths[-1])
            if previous.raw.get("profile") == data:
                return previous, paths[-1], False
    return snapshot, store.save(snapshot), True
