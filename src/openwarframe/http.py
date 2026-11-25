"""A small cached HTTP client.

Every remote fetch in OpenWarframe goes through :class:`CachedClient` so that

* requests carry a descriptive User-Agent,
* responses are cached on disk and re-validated with ETag / Last-Modified,
* ``Cache-Control: max-age`` is honored (callers can override it),
* transient failures are retried, and a stale copy is served if the network is down.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import USER_AGENT
from .fsutil import atomic_write_bytes, atomic_write_text

log = logging.getLogger(__name__)

DEFAULT_MAX_AGE = 3600.0
_MAX_AGE_RE = re.compile(r"max-age=(\d+)")


@dataclass
class CacheEntry:
    url: str
    fetched_at: float
    max_age: float
    etag: str | None = None
    last_modified: str | None = None
    status: int = 200

    def is_fresh(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return (now - self.fetched_at) < self.max_age


class CachedClient:
    def __init__(self, cache_dir: Path, *, timeout: float = 60.0, retries: int = 3) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.retries = retries
        self.last_was_network = False  # did the last get() send a request (rate limits care)
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            timeout=timeout,
            follow_redirects=True,
        )

    # -- cache helpers -------------------------------------------------------------
    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _read_meta(self, meta_path: Path) -> CacheEntry | None:
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return CacheEntry(**data)
        except (ValueError, TypeError):
            return None

    def _write(self, url: str, body: bytes, entry: CacheEntry) -> None:
        body_path, meta_path = self._paths(url)
        # body first, then the metadata that vouches for it: a crash in between leaves no
        # metadata pointing at a half-written body
        atomic_write_bytes(body_path, body)
        atomic_write_text(meta_path, json.dumps(entry.__dict__))

    def drop(self, url: str) -> None:
        """Forget the cached copy of ``url``."""
        for p in self._paths(url):
            p.unlink(missing_ok=True)

    def cached(self, url: str) -> bytes | None:
        """Return the cached body regardless of freshness, or None."""
        body_path, _ = self._paths(url)
        return body_path.read_bytes() if body_path.exists() else None

    # -- fetching -------------------------------------------------------------------
    def get(self, url: str, *, max_age: float | None = None, force: bool = False) -> bytes:
        body_path, meta_path = self._paths(url)
        entry = self._read_meta(meta_path)
        self.last_was_network = False
        if entry and body_path.exists() and not force:
            effective = max_age if max_age is not None else entry.max_age
            if (time.time() - entry.fetched_at) < effective:
                return body_path.read_bytes()
        self.last_was_network = True

        headers: dict[str, str] = {}
        if entry and body_path.exists() and not force:
            if entry.etag:
                headers["If-None-Match"] = entry.etag
            if entry.last_modified:
                headers["If-Modified-Since"] = entry.last_modified

        last_error: Exception | None = None
        for attempt in range(self.retries):
            last_try = attempt == self.retries - 1
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:  # network trouble
                last_error = exc
                if not last_try:
                    time.sleep(0.5 * (2**attempt))
                continue
            if resp.status_code == 429:  # rate limited: wait as asked (briefly), then try again
                last_error = httpx.HTTPStatusError(f"429 from {url}", request=resp.request, response=resp)
                if not last_try:
                    time.sleep(_retry_after(resp, default=1.0 * (2**attempt)))
                continue
            if resp.status_code == 304 and entry and body_path.exists():
                entry.fetched_at = time.time()
                entry.max_age = max_age if max_age is not None else _max_age_from(resp, entry.max_age)
                atomic_write_text(meta_path, json.dumps(entry.__dict__))
                return body_path.read_bytes()
            if resp.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
                if not last_try:
                    time.sleep(0.5 * (2**attempt))
                continue
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"{resp.status_code} from {url}", request=resp.request, response=resp
                )
            new_entry = CacheEntry(
                url=url,
                fetched_at=time.time(),
                max_age=max_age if max_age is not None else _max_age_from(resp, DEFAULT_MAX_AGE),
                etag=resp.headers.get("etag"),
                last_modified=resp.headers.get("last-modified"),
                status=resp.status_code,
            )
            self._write(url, resp.content, new_entry)
            return resp.content

        if entry and body_path.exists():
            log.warning("network failed for %s, serving stale cache (%s)", url, last_error)
            return body_path.read_bytes()
        assert last_error is not None
        raise last_error

    def get_json(self, url: str, **kw):
        try:
            return json.loads(self.get(url, **kw).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            # a damaged cache file would otherwise be served until it expires (up to weeks)
            self.drop(url)
            if kw.get("force"):
                raise
            log.warning("cached copy of %s was damaged; downloading it again", url)
            return json.loads(self.get(url, **{**kw, "force": True}).decode("utf-8"))

    def close(self) -> None:
        self._client.close()


def _retry_after(resp: httpx.Response, default: float, cap: float = 10.0) -> float:
    """Seconds a 429 asks us to wait (Retry-After), never more than ``cap``."""
    try:
        return min(cap, max(0.0, float(resp.headers.get("retry-after", default))))
    except ValueError:
        return min(cap, default)


def _max_age_from(resp: httpx.Response, default: float) -> float:
    cc = resp.headers.get("cache-control", "")
    m = _MAX_AGE_RE.search(cc)
    if m:
        return float(m.group(1))
    return default
