"""Take a snapshot from the configured sources."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from ..codex.queries import Codex
from ..config import Settings
from ..fsutil import atomic_write_text
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
    written and the previous path is returned. Failures come back as ProfileError with a
    message for the player; a profile that downloads but can't be read is kept on disk.
    """
    if not settings.account_id:
        raise ProfileError("no account id configured; run `openwarframe account howto`")
    client = CachedClient(settings.cache_dir)
    try:
        data = fetch_profile(client, settings.account_id, settings.platform, force=force)
    except httpx.HTTPError as exc:
        raise ProfileError(
            f"Could not reach Digital Extremes for your profile ({exc}). Check your internet connection."
        ) from None
    except ValueError as exc:  # the body was not JSON
        raise ProfileError(f"The profile came back in a form OpenWarframe can't read ({exc}).") from None
    finally:
        client.close()
    mark_profile_checked(settings)
    store = SnapshotStore(settings.snapshots_dir)
    if skip_unchanged:  # compare the raw payload first: no need to parse an unchanged profile
        latest_path = store.list()[-1] if store.list() else None
        previous = store.latest()
        if previous is not None and latest_path is not None and previous.raw.get("profile") == data:
            return previous, latest_path, False
    codex = Codex(settings.codex_path) if settings.codex_path.exists() else None
    try:
        snapshot = parse_profile(data, platform=settings.platform, codex=codex)
    except Exception as exc:  # noqa: BLE001 - keep the raw data so nothing is lost
        kept = settings.account_dir / "unreadable-profile.json"
        atomic_write_text(kept, json.dumps(data))
        raise ProfileError(
            f"Your profile downloaded but could not be read ({type(exc).__name__}: {exc}); a game update may "
            f"have changed it. The download is kept at {kept} so it can be read once OpenWarframe is updated."
        ) from None
    finally:
        if codex:
            codex.close()
    return snapshot, store.save(snapshot), True


def mark_profile_checked(settings: Settings) -> None:
    """Remember when the profile was last fetched. An unchanged profile writes no new
    snapshot, so without this a player back from a break would look out of date forever."""
    p = profile_checked_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()


def profile_checked_path(settings: Settings) -> Path:
    return settings.account_dir / "profile-checked"


def reparse(snapshot: Snapshot, codex: Codex | None) -> Snapshot:
    """Re-derive a snapshot from its raw profile with the current codex.

    Names and categories come from the codex, which improves over time; the raw
    payload is the source of truth, so exports always use the latest mapping.
    """
    raw = snapshot.raw.get("profile")
    if not raw:
        return snapshot
    return parse_profile(raw, platform=snapshot.identity.platform, codex=codex, taken_at=snapshot.taken_at)
