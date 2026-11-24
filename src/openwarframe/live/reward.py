"""Glue: screenshot -> OCR -> match -> ranked picks, plus saving recordings for tuning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import ocr
from .match import Match, Ranked, RewardCatalog, rank


@dataclass
class Analysis:
    players: int
    ui_scale: float
    layouts: dict[int, list[str]]  # raw OCR per squad size tried
    matches: list[Match]
    ranked: list[Ranked]

    def to_dict(self) -> dict:
        def m(x: Match) -> dict:
            e = x.entry
            return {
                "raw": x.raw,
                "score": round(x.score, 3),
                "name": e.name if e else None,
                "unique_name": e.unique_name if e else None,
                "for": e.final_name if e else None,
                "vaulted": e.vaulted if e else None,
                "ducats": e.ducats if e else None,
                "slug": e.slug if e else None,
            }

        return {
            "players": self.players,
            "ui_scale": self.ui_scale,
            "ocr": {str(k): v for k, v in self.layouts.items()},
            "slots": [m(x) for x in self.matches],
            "ranked": [
                {
                    "slot": r.slot,
                    "name": r.match.entry.name if r.match.entry else r.match.raw,
                    "why": r.reason,
                }
                for r in self.ranked
            ],
        }


def analyze(
    image: Image.Image,
    catalog: RewardCatalog,
    *,
    players: int | None = None,
    ui_scale: float = 1.0,
    language: str | None = None,
    needs: tuple[set[str], dict[str, int], set[str]] | None = None,
    prices: dict | None = None,
) -> Analysis:
    if players:
        layouts = {players: ocr.read_slots(image, players, ui_scale, language=language)}
    else:
        layouts = ocr.read_all_layouts(image, ui_scale, language=language)
    n, matches = catalog.pick_layout(layouts)
    needed, parts, owned = needs or (set(), {}, set())
    ranked = rank(matches, needed_items=needed, owned_parts=parts, owned_items=owned, prices=prices)
    return Analysis(n, ui_scale, layouts, matches, ranked)


def recordings_dir(home: Path) -> Path:
    return home / "live" / "recordings"


def save_recording(
    home: Path,
    image: Image.Image,
    analysis: Analysis | None,
    *,
    event: dict | None = None,
    log_tail: list[str] | None = None,
    error: str | None = None,
) -> Path:
    """Write screenshot.png, result.json and log.txt into a new timestamped folder."""
    d = recordings_dir(home) / datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    d.mkdir(parents=True, exist_ok=True)
    image.save(d / "screenshot.png")
    out = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "error": error,
        "size": list(image.size),
    }
    if analysis:
        out |= analysis.to_dict()
    (d / "result.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    if log_tail:
        (d / "log.txt").write_text("\n".join(log_tail) + "\n", encoding="utf-8")
    return d
