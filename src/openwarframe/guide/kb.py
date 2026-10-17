"""Load the curated knowledge base.

The YAML lives in ``kb/`` at the repository root (see docs/KNOWLEDGE_BASE.md). Wheels
ship a copy as ``openwarframe/kb_data``. ``OPENWARFRAME_KB`` overrides both.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
