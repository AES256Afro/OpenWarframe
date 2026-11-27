"""Optional extras for the exports that the report itself does not carry.

The report is built from one snapshot. A few things players asked for need more than
that: what changed since the last sync (two snapshots), the goals set in the app
(app-prefs.json) and how much standing is left today (the raw profile). The CLI
gathers them and passes them in; every export works without them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..report.model import Report

log = logging.getLogger(__name__)

RANK_TEST_COOLDOWN = "If you fail, you can try again after 23 hours."


@dataclass
class ExportExtras:
    diff: object | None = None  # account.store.SnapshotDiff: since the previous snapshot
    goals: list[str] = field(default_factory=list)  # item names, from the app's goals
    standing_left: dict[str, int] = field(default_factory=dict)  # daily standing caps left

    @property
    def standing_left_total(self) -> int | None:
        return sum(self.standing_left.values()) if self.standing_left else None


def rank_test_ready(report: Report) -> int | None:
    """The rank whose test the account can take now (its mastery XP reached the threshold), else None."""
    ms = report.mastery
    total = ms.visible_total  # not the estimate: never announce a test that is not open yet
    return ms.rank + 1 if ms.next_rank_threshold and total >= ms.next_rank_threshold else None


def rank_test_line(report: Report) -> str | None:
    rank = rank_test_ready(report)
    return f"Rank {rank} test available. {RANK_TEST_COOLDOWN}" if rank else None


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def readable_id(unique_name: str) -> str:
    """'/Lotus/Powersuits/Rhino/RhinoPrime' -> 'Rhino Prime': for ids the codex does not know."""
    last = unique_name.rstrip("/").rsplit("/", 1)[-1]
    return _CAMEL.sub(" ", last).strip() or unique_name


def load_goal_names(home: Path, codex=None) -> list[str]:
    """Item goals saved by the app (``app-prefs.json`` in the data folder), as names. Read-only."""
    try:
        data = json.loads((home / "app-prefs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    goals = data.get("goals") if isinstance(data, dict) else None
    if not isinstance(goals, list):
        return []
    names: list[str] = []
    for gid in goals:
        if not isinstance(gid, str) or not gid:
            continue
        name = ""
        if codex is not None:
            try:
                name = codex.name_of(gid)
            except Exception:  # noqa: BLE001 - a damaged codex must not stop the export
                log.debug("goal %s: codex lookup failed", gid, exc_info=True)
        if not name or name == gid.rsplit("/", 1)[-1]:
            name = readable_id(gid)
        if name not in names:
            names.append(name)
    return names


def diff_lines(d, *, limit: int = 12) -> list[str]:
    """Short bullet lines for a SnapshotDiff; empty when nothing changed."""
    if d is None or d.is_empty():
        return []
    out: list[str] = []
    span = f"{d.before:%Y-%m-%d %H:%M} to {d.after:%Y-%m-%d %H:%M} UTC"
    played = f", {d.play_time_h:.1f} h played" if d.play_time_h > 0 else ""
    missions = f", {d.missions_completed} missions" if d.missions_completed > 0 else ""
    out.append(f"Period: {span}{played}{missions}.")
    if d.mastery_rank[0] != d.mastery_rank[1]:
        out.append(f"Mastery rank {d.mastery_rank[0]} -> {d.mastery_rank[1]}.")

    def names(label: str, items: list[str]) -> None:
        if items:
            more = f" and {len(items) - limit} more" if len(items) > limit else ""
            out.append(f"{label}: {', '.join(items[:limit])}{more}.")

    names("Mastered", d.newly_mastered)
    names("Ranked up", [f"{n} {a}->{b}" for n, a, b in d.rank_ups])
    names("Started leveling", [n for n in d.newly_leveled if n not in d.newly_mastered])
    names("New star chart nodes", d.new_nodes)
    names("New Steel Path nodes", d.new_steel_path_nodes)
    names("Standing", [f"{n} {v:+,}" for n, v in d.standing])
    if d.challenges_progressed:
        out.append(f"Achievements progressed: {len(d.challenges_progressed)}.")
    return out


def diff_rows(d) -> list[tuple[str, str]]:
    """(what, detail) rows for a spreadsheet; empty when nothing changed."""
    if d is None or d.is_empty():
        return []
    rows: list[tuple[str, str]] = []
    if d.mastery_rank[0] != d.mastery_rank[1]:
        rows.append(("Mastery rank", f"{d.mastery_rank[0]} -> {d.mastery_rank[1]}"))
    rows += [("Mastered", n) for n in d.newly_mastered]
    rows += [("Ranked up", f"{n} {a} -> {b}") for n, a, b in d.rank_ups]
    rows += [("Started leveling", n) for n in d.newly_leveled if n not in d.newly_mastered]
    rows += [("Star chart node", n) for n in d.new_nodes]
    rows += [("Steel Path node", n) for n in d.new_steel_path_nodes]
    rows += [("Standing", f"{n} {v:+,}") for n, v in d.standing]
    return rows


def export_folder(settings, snap, share: bool) -> Path:
    """data dir/exports/<snapshot time, local>/full or /share: one rule for every export."""
    stamp = snap.taken_at.astimezone().strftime("%Y-%m-%d_%H%M")
    return settings.exports_dir / stamp / ("share" if share else "full")


def gather_extras(settings, store, parsed, codex, *, compare: bool = True) -> ExportExtras:
    """What changed since the previous snapshot, app goals and standing left today. Never fails."""
    extras = ExportExtras()
    try:
        extras.standing_left = dict(parsed.progression.daily_affiliations)
    except Exception:  # noqa: BLE001 - extras are optional
        log.debug("no daily standing", exc_info=True)
    try:
        extras.goals = load_goal_names(settings.home, codex)
    except Exception:  # noqa: BLE001
        log.debug("goals unreadable", exc_info=True)
    if compare:
        try:
            from ..account.store import diff_snapshots
            from ..account.sync import reparse

            previous = reparse(store.load("previous"), codex)
            if previous.taken_at < parsed.taken_at:
                extras.diff = diff_snapshots(previous, parsed)
        except Exception:  # noqa: BLE001 - first snapshot, or an unreadable one
            log.debug("no previous snapshot to compare", exc_info=True)
    return extras
