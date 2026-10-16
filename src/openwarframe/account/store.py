"""Append-only snapshot store and diffs between snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .model import Snapshot


class SnapshotStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: Snapshot) -> Path:
        stamp = snapshot.taken_at.strftime("%Y-%m-%dT%H%M%SZ")
        path = self.directory / f"{stamp}.json"
        path.write_text(snapshot.model_dump_json(indent=1), encoding="utf-8")
        return path

    def list(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    def load(self, ref: str | Path) -> Snapshot:
        path = self._resolve(ref)
        return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def latest(self) -> Snapshot | None:
        paths = self.list()
        return self.load(paths[-1]) if paths else None

    def _resolve(self, ref: str | Path) -> Path:
        p = Path(ref)
        if p.exists():
            return p
        candidates = self.list()
        if ref == "latest" and candidates:
            return candidates[-1]
        if ref == "previous" and len(candidates) >= 2:
            return candidates[-2]
        for c in candidates:
            if c.stem.startswith(str(ref)):
                return c
        raise FileNotFoundError(f"no snapshot matching {ref!r} in {self.directory}")


@dataclass
class SnapshotDiff:
    before: datetime
    after: datetime
    mastery_rank: tuple[int, int]
    play_time_h: float
    missions_completed: int
    newly_mastered: list[str] = field(default_factory=list)
    newly_leveled: list[str] = field(default_factory=list)  # first XP ever
    rank_ups: list[tuple[str, int, int]] = field(default_factory=list)
    new_nodes: list[str] = field(default_factory=list)
    new_steel_path_nodes: list[str] = field(default_factory=list)
    standing: list[tuple[str, int]] = field(default_factory=list)
    challenges_progressed: list[tuple[str, int, int]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.mastery_rank[0] != self.mastery_rank[1],
                self.newly_mastered,
                self.newly_leveled,
                self.rank_ups,
                self.new_nodes,
                self.new_steel_path_nodes,
                self.standing,
                self.challenges_progressed,
            ]
        )


def diff_snapshots(a: Snapshot, b: Snapshot) -> SnapshotDiff:
    """What changed from snapshot ``a`` (older) to ``b`` (newer)."""
    ia = {i.item: i for i in a.progression.items}
    ib = {i.item: i for i in b.progression.items}
    d = SnapshotDiff(
        before=a.taken_at,
        after=b.taken_at,
        mastery_rank=(a.progression.mastery_rank, b.progression.mastery_rank),
        play_time_h=((b.progression.play_time_s or 0) - (a.progression.play_time_s or 0)) / 3600,
        missions_completed=(b.progression.missions_completed or 0) - (a.progression.missions_completed or 0),
    )
    for key, it in ib.items():
        old = ia.get(key)
        if old is None:
            d.newly_leveled.append(it.name)
            if it.mastered:
                d.newly_mastered.append(it.name)
            continue
        if it.mastered and not old.mastered:
            d.newly_mastered.append(it.name)
        elif it.rank > old.rank:
            d.rank_ups.append((it.name, old.rank, it.rank))

    na = {n.node: n for n in a.progression.nodes}
    for n in b.progression.nodes:
        old = na.get(n.node)
        label = f"{n.name} ({n.planet})"
        if old is None:
            d.new_nodes.append(label)
            if n.steel_path:
                d.new_steel_path_nodes.append(label)
        elif n.steel_path and not old.steel_path:
            d.new_steel_path_nodes.append(label)

    sa = {x.tag: x.standing for x in a.progression.affiliations}
    for x in b.progression.affiliations:
        delta = x.standing - sa.get(x.tag, 0)
        if delta:
            d.standing.append((x.name, delta))

    ca = {c.name: c.progress for c in a.progression.challenges}
    for c in b.progression.challenges:
        old = ca.get(c.name, 0)
        if c.progress > old:
            d.challenges_progressed.append((c.name, old, c.progress))
    return d
