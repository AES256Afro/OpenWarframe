"""House style for every text file in the repository: no em or en dashes."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
TEXT = {".md", ".py", ".js", ".css", ".html", ".toml", ".yml", ".yaml", ".iss", ".ps1", ".txt", ".spec"}


def test_no_long_dashes():
    try:
        files = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        files = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
    bad = []
    for name in files:
        p = ROOT / name
        if p.suffix not in TEXT or not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "—" in line or "–" in line:
                bad.append(f"{name}:{i}")
    assert not bad, "use a hyphen or a comma instead of a long dash: " + ", ".join(bad[:20])
