"""warframe-public-export-plus (community, MIT).

Everything DE does not include in the Public Export: relic eras, vendors, syndicates,
challenges (achievements), mission types, bounties, plus the English language
dictionary that resolves ``/Lotus/Language/...`` paths to text.

Repo: https://github.com/calamity-inc/warframe-public-export-plus (branch ``senpai``). Files are
fetched at the commit the branch points to, which is recorded as the version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...http import CachedClient

REPO = "calamity-inc/warframe-public-export-plus"
BRANCH = "senpai"
COMMITS_API = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def raw_base(ref: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{ref}/"


RAW = raw_base(BRANCH)  # kept for callers that want the branch head

FILES = [
    "ExportRelics",
    "ExportVendors",
    "ExportSyndicates",
    "ExportChallenges",
    "ExportMissionTypes",
    "ExportBounties",
    # item names the Public Export lacks (see codex.build.PLUS_ITEM_FILES)
    "ExportArcanes",
    "ExportUpgrades",
    "ExportCustoms",
    "ExportBoosters",
    "ExportBundles",
    "ExportBoosterPacks",
    "ExportCreditBundles",
]
DICT_FILE = "dict.en.json"


@dataclass
class PlusExport:
    version: str
    files: dict[str, dict]
    dictionary: dict[str, str]

    def text(self, key: str | None, default: str | None = None) -> str | None:
        """Resolve a ``/Lotus/Language/...`` key to English text."""
        if not key:
            return default
        return self.dictionary.get(key, default if default is not None else key)


def _resolve_commit(client: CachedClient, *, force: bool = False) -> str | None:
    """The commit the branch points at now, or None when GitHub can't be asked (rate limit, offline)."""
    try:
        sha = str(client.get_json(COMMITS_API, max_age=6 * 3600, force=force).get("sha", ""))
    except Exception:  # noqa: BLE001 - fall back to the branch head below
        return None
    return sha if _SHA.match(sha) else None


def fetch_plus(client: CachedClient, *, force: bool = False) -> PlusExport:
    """Download every file from one commit, so the data and its version label always agree.

    Files at a commit never change, so they are cached for a long time. Only when the commit
    can't be looked up does this fall back to the branch head (labelled ``@unknown``).
    """
    sha = _resolve_commit(client, force=force)
    if sha:
        base, version, max_age = raw_base(sha), f"{BRANCH}@{sha[:10]}", 365 * 86400
    else:
        base, version, max_age = RAW, f"{BRANCH}@unknown", 86400
    files = {name: client.get_json(base + name + ".json", max_age=max_age, force=force) for name in FILES}
    dictionary = client.get_json(base + DICT_FILE, max_age=max_age, force=force)
    return PlusExport(version=version, files=files, dictionary=dictionary)
