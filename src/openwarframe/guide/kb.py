"""Load the curated knowledge base.

The YAML lives in ``kb/`` at the repository root (see docs/KNOWLEDGE_BASE.md). Wheels
ship a copy as ``openwarframe/kb_data``. ``OPENWARFRAME_KB`` overrides both.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


def kb_dir() -> Path:
    env = os.environ.get("OPENWARFRAME_KB")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    candidates = [here.parents[3] / "kb", here.parents[1] / "kb_data"]
    for c in candidates:
        if (c / "mastery").is_dir():
            return c
    raise FileNotFoundError(
        "knowledge base not found; expected kb/ at the repository root or set OPENWARFRAME_KB"
    )


# Game updates change rank tests and farms; past this age the guide says its advice may be stale.
STALE_AFTER_DAYS = 180


@dataclass
class MasteryKB:
    tests: dict  # tests.yaml
    farms: dict  # farms.yaml
    routes: dict  # routes.yaml
    path: Path = field(default_factory=Path)

    def test_for(self, rank: int) -> dict | None:
        return next((t for t in self.tests.get("tests", []) if t["rank"] == rank), None)

    def route(self, key: str) -> dict:
        return self.routes["routes"][key]

    @property
    def route_order(self) -> list[str]:
        return list(self.routes["order"])

    def verified(self) -> list[tuple[str, date | None]]:
        """(file, last_verified) for each knowledge-base file."""
        out = []
        for name, doc in (("tests", self.tests), ("farms", self.farms), ("routes", self.routes)):
            v = doc.get("last_verified")
            if isinstance(v, str):
                try:
                    v = date.fromisoformat(v)
                except ValueError:
                    v = None
            out.append((name, v if isinstance(v, date) else None))
        return out

    def stale(self, today: date | None = None, max_days: int = STALE_AFTER_DAYS) -> list[str]:
        """Files not checked against the game for ``max_days`` (or never): advice may be out of date."""
        today = today or date.today()
        return [
            f"{name}.yaml" + (f" (checked {v.isoformat()})" if v else " (never checked)")
            for name, v in self.verified()
            if v is None or (today - v).days > max_days
        ]

    def sources(self) -> list[dict]:
        out: list[dict] = []
        for doc in (self.tests, self.farms, self.routes):
            for s in doc.get("sources", []):
                if s not in out:
                    out.append(s)
        return out


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_kb(root: Path | None = None) -> MasteryKB:
    root = root or kb_dir()
    m = root / "mastery"
    kb = MasteryKB(
        tests=_read(m / "tests.yaml"),
        farms=_read(m / "farms.yaml"),
        routes=_read(m / "routes.yaml"),
        path=root,
    )
    missing = set(kb.route_order) - set(kb.routes.get("routes", {}))
    if missing:
        raise ValueError(f"routes.yaml order names unknown routes: {sorted(missing)}")
    return kb
