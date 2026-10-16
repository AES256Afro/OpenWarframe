from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENWARFRAME_HOME", str(tmp_path / "home"))
    return Path(os.environ["OPENWARFRAME_HOME"])
