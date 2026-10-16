"""The public profile endpoint (Tier 1).

The same read-only endpoint the in-game profile viewer uses. It needs only the
24-character account ID and the platform; see docs/ACCOUNT_DATA_ACCESS.md.
"""

from __future__ import annotations

import json
import re

from ...http import CachedClient

HOSTS = {
    "pc": "https://api.warframe.com/cdn/getProfileViewingData.php",
    "ps4": "http://content-ps4.warframe.com/dynamic/getProfileViewingData.php",
    "xb1": "http://content-xb1.warframe.com/dynamic/getProfileViewingData.php",
    "swi": "http://content-swi.warframe.com/dynamic/getProfileViewingData.php",
    "mob": "http://content-mob.warframe.com/dynamic/getProfileViewingData.php",
    "and": "http://content-and.warframe.com/dynamic/getProfileViewingData.php",
}
PLATFORM_LABELS = {
    "pc": "PC",
    "ps4": "PlayStation",
    "xb1": "Xbox",
    "swi": "Nintendo Switch",
    "mob": "iOS",
    "and": "Android",
}
ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{24}$")

HOW_TO_FIND_ID = """How to find your account ID (the `gid` cookie):

  1. Log in at https://www.warframe.com in your browser.
  2. Press F12, open the Application tab (Storage in Firefox).
  3. Cookies -> https://www.warframe.com -> row named `gid`.
  4. Copy its value: 24 lowercase hex characters.

Treat it like a user name, not a password: it only unlocks the same read-only
profile anyone can view in game. Then run:

  openwarframe account set --id <value> --platform pc
"""


class ProfileError(RuntimeError):
    pass


def validate_account_id(account_id: str) -> str:
    aid = account_id.strip().lower()
    if not ACCOUNT_ID_RE.match(aid):
        raise ProfileError("account id must be 24 hex characters (see `openwarframe account howto`)")
    return aid


def profile_url(account_id: str, platform: str = "pc") -> str:
    if platform not in HOSTS:
        raise ProfileError(f"unknown platform {platform!r}; one of {', '.join(HOSTS)}")
    return f"{HOSTS[platform]}?playerId={validate_account_id(account_id)}"


def fetch_profile(
    client: CachedClient, account_id: str, platform: str = "pc", *, force: bool = False
) -> dict:
    """Return the raw profile JSON. The endpoint sets max-age about 600 s."""
    body = client.get(profile_url(account_id, platform), force=force)
    if not body.strip():
        raise ProfileError(
            "empty response: unknown account id for this platform, or the profile is not public"
        )
    data = json.loads(body.decode("utf-8"))
    if not data.get("Results"):
        raise ProfileError("profile response has no Results; account not found")
    return data
