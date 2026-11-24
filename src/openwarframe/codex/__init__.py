"""The codex: a local SQLite database of everything in the game, keyed by uniqueName."""

from .build import CodexPayloads, build_codex, update_codex
from .queries import Codex


def codex_schema_version(path) -> int:
    """Schema version stored in a codex file; 0 when missing or unreadable."""
    import sqlite3
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return 0
    try:
        conn = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT version FROM source_version WHERE source = 'schema'").fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
    except (sqlite3.Error, ValueError):
        return 0


__all__ = ["Codex", "CodexPayloads", "build_codex", "codex_schema_version", "update_codex"]
