"""warframe-public-export-plus is fetched at one commit, so data and version label agree."""

from __future__ import annotations

from pathlib import Path

import httpx

from openwarframe.http import CachedClient
from openwarframe.sources.static import pe_plus

SHA = "0123456789abcdef0123456789abcdef01234567"


def _client(tmp_path: Path, commits: httpx.Response) -> tuple[CachedClient, list[str]]:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if str(req.url) == pe_plus.COMMITS_API:
            return commits
        return httpx.Response(200, json={})

    client = CachedClient(tmp_path, retries=1)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, seen


def test_files_come_from_the_resolved_commit(tmp_path: Path):
    client, seen = _client(tmp_path, httpx.Response(200, json={"sha": SHA}))
    plus = pe_plus.fetch_plus(client)
    assert plus.version == f"senpai@{SHA[:10]}"
    files = [u for u in seen if u != pe_plus.COMMITS_API]
    assert files and all(f"/{SHA}/" in u for u in files)


def test_without_github_the_branch_head_is_used_and_labelled_unknown(tmp_path: Path):
    client, seen = _client(tmp_path, httpx.Response(403, json={"message": "rate limited"}))
    plus = pe_plus.fetch_plus(client)
    assert plus.version == "senpai@unknown"
    assert all("/senpai/" in u for u in seen if u != pe_plus.COMMITS_API)
