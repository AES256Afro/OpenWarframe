"""warframe-public-export-plus (community, MIT).

Everything DE does not include in the Public Export: relic eras, vendors, syndicates,
challenges (achievements), mission types, bounties, plus the English language
dictionary that resolves ``/Lotus/Language/...`` paths to text.

Repo: https://github.com/calamity-inc/warframe-public-export-plus (branch ``senpai``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ...http import CachedClient

REPO = "calamity-inc/warframe-public-export-plus"
BRANCH = "senpai"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"
COMMITS_API = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"

FILES = [
    "ExportRelics",
    "ExportVendors",
    "ExportSyndicates",
    "ExportChallenges",
    "ExportMissionTypes",
    "ExportBounties",
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


def _pinned_version(client: CachedClient) -> str:
    try:
        data = client.get_json(COMMITS_API, max_age=6 * 3600)
        sha = data.get("sha", "")
        return f"{BRANCH}@{sha[:10]}" if sha else BRANCH
    except Exception:  # rate limit, offline: version is best effort
        return f"{BRANCH}@unknown"


def fetch_plus(client: CachedClient, *, force: bool = False) -> PlusExport:
    version = _pinned_version(client)
    files = {name: client.get_json(RAW + name + ".json", max_age=86400, force=force) for name in FILES}
    dictionary = client.get_json(RAW + DICT_FILE, max_age=86400, force=force)
    return PlusExport(version=version, files=files, dictionary=dictionary)
