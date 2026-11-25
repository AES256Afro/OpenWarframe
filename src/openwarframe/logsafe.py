"""Keep secrets out of log output.

The game-session inventory request carries the session key (``nonce``) in its URL, and
httpx logs every request URL at INFO level, which ``openwarframe -v`` turns on. People
paste ``-v`` output into bug reports, so the key is masked before any handler sees it.
"""

from __future__ import annotations

import logging
import re

_SECRET = re.compile(r"(?i)(\bnonce=)[^&\s\"'<>]+")
MASK = "<hidden>"


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: m.group(1) + MASK, text)


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken format string is not ours to fix here
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


_FILTER = RedactSecrets()


def install() -> None:
    """Mask secrets in httpx/httpcore records and in every root handler. Safe to call twice."""
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
    for handler in logging.getLogger().handlers:
        if _FILTER not in handler.filters:
            handler.addFilter(_FILTER)
