"""Match OCR text to relic reward names and rank the choices.

Names come from the codex: every item in ``relic_reward``, named the way the reward
screen prints it (warframe.market's name when there is one, else the item name, else
"<what the recipe builds> Blueprint"). Matching is plain ``difflib``.

Ranking, best first:
1. the part is still needed for an item you have not mastered (and do not own the part
   or the finished item, when an inventory is loaded)
2. the part is vaulted (no relic that drops it can be farmed now)
3. platinum price, from a dict you pass in (name, market slug or uniqueName -> price)
4. ducats
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MIN_SCORE = 0.62


def normalize(text: str) -> str:
    t = text.upper()
    t = t.replace("0", "O").replace("1", "I").replace("|", "I").replace("5", "S")
    t = re.sub(r"[^A-Z ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class RewardEntry:
    unique_name: str
    name: str
    final_item: str  # what this part ends up building (warframe, weapon, ...)
    final_name: str
    ducats: int | None = None
    vaulted: bool = False
    slug: str | None = None
    relics: list[str] = field(default_factory=list)
    key: str = ""  # normalized name


@dataclass
class Match:
    raw: str
    entry: RewardEntry | None
    score: float


@dataclass
class Ranked:
    slot: int
    match: Match
    needed: bool
    platinum: float | None
    reason: str


def _final_item(conn: sqlite3.Connection, uid: str, depth: int = 0) -> str:
    """Follow recipes upward: part blueprint -> part -> the item it builds."""
    if depth > 4:
        return uid
    row = conn.execute("SELECT result_item FROM recipe WHERE unique_name = ?", (uid,)).fetchone()
    if row:
        uid = row[0]
    up = conn.execute(
        "SELECT r.result_item FROM recipe_ingredient ri JOIN recipe r ON r.unique_name = ri.recipe "
        "WHERE ri.item = ? LIMIT 1",
        (uid,),
    ).fetchone()
    if up and up[0] != uid:
        return _final_item(conn, up[0], depth + 1)
    return uid


class RewardCatalog:
    def __init__(self, entries: list[RewardEntry]):
        self.entries = entries
        for e in entries:
            e.key = normalize(e.name)
        self._by_key = {e.key: e for e in entries}

    @classmethod
    def from_codex(cls, conn: sqlite3.Connection) -> RewardCatalog:
        item_rows = {u: (n, d) for u, n, d in conn.execute("SELECT unique_name, name, data FROM item")}
        market = {u: (s, n) for u, s, n in conn.execute("SELECT unique_name, slug, name FROM market_item")}
        relic_names = dict(conn.execute("SELECT unique_name, name FROM relic"))
        farmable = {
            r[0]
            for r in conn.execute(
                """SELECT item FROM node_reward WHERE item LIKE '%/Projections/%'
                   UNION SELECT item FROM transient_reward WHERE item LIKE '%/Projections/%'
                   UNION SELECT item FROM bounty_reward WHERE item LIKE '%/Projections/%'"""
            )
        }
        relics_of: dict[str, set[str]] = defaultdict(set)
        for relic, item in conn.execute("SELECT relic, item FROM relic_reward"):
            relics_of[item].add(relic)

        def ducats_of(uid: str) -> int | None:
            for u in (
                uid,
                *(r[0] for r in conn.execute("SELECT result_item FROM recipe WHERE unique_name = ?", (uid,))),
            ):
                row = item_rows.get(u)
                if row and row[1]:
                    try:
                        v = json.loads(row[1]).get("primeSellingPrice")
                    except ValueError:
                        v = None
                    if v is not None:
                        return int(v)
            return None

        def name_of(uid: str) -> str:
            if uid in market:
                return market[uid][1]
            if uid in item_rows:
                return item_rows[uid][0]
            row = conn.execute(
                "SELECT i.name FROM recipe r JOIN item i ON i.unique_name = r.result_item "
                "WHERE r.unique_name = ?",
                (uid,),
            ).fetchone()
            if row:
                return f"{row[0]} Blueprint"
            tail = uid.rsplit("/", 1)[-1]
            return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tail.replace("Component", ""))

        entries = []
        for uid, relics in relics_of.items():
            final = _final_item(conn, uid)
            entries.append(
                RewardEntry(
                    unique_name=uid,
                    name=name_of(uid),
                    final_item=final,
                    final_name=(item_rows.get(final) or (final.rsplit("/", 1)[-1], None))[0],
                    ducats=ducats_of(uid),
                    vaulted=not (relics & farmable),
                    slug=market.get(uid, (None,))[0],
                    relics=sorted(relic_names.get(r, r) for r in relics),
                )
            )
        entries.sort(key=lambda e: e.name)
        return cls(entries)

    def match(self, raw: str) -> Match:
        key = normalize(raw)
        if not key:
            return Match(raw, None, 0.0)
        if key in self._by_key:
            return Match(raw, self._by_key[key], 1.0)
        best, best_score = None, 0.0
        sm = SequenceMatcher(autojunk=False)
        sm.set_seq2(key)
        for e in self.entries:
            sm.set_seq1(e.key)
            if sm.real_quick_ratio() < best_score or sm.quick_ratio() < best_score:
                continue
            s = sm.ratio()
            if s > best_score:
                best, best_score = e, s
        if best is None or best_score < MIN_SCORE:
            return Match(raw, None, best_score)
        return Match(raw, best, best_score)

    def match_all(self, raws: list[str]) -> list[Match]:
        return [self.match(r) for r in raws]

    def pick_layout(self, layouts: dict[int, list[str]]) -> tuple[int, list[Match]]:
        """Choose the squad size whose OCR reads best: most fully-matched slots wins."""
        best: tuple[tuple, int, list[Match]] | None = None
        for n, raws in layouts.items():
            ms = self.match_all(raws)
            ok = sum(1 for m in ms if m.entry)
            mean = sum(m.score for m in ms) / max(1, len(ms))
            # a layout only counts when every slot matched; then bigger squads win ties
            key = (ok == len(ms) and ok > 0, mean if ok == len(ms) else ok / max(1, len(ms)), n)
            if best is None or key > best[0]:
                best = (key, n, ms)
        assert best is not None
        return best[1], best[2]


def _price(prices: dict | None, e: RewardEntry) -> float | None:
    if not prices:
        return None
    for k in (e.unique_name, e.slug, e.name, e.name.lower(), e.key):
        if k and k in prices and prices[k] is not None:
            return float(prices[k])
    return None


def rank(
    matches: list[Match],
    *,
    needed_items: set[str] | None = None,
    owned_parts: dict[str, int] | None = None,
    owned_items: set[str] | None = None,
    prices: dict | None = None,
) -> list[Ranked]:
    """Order the rewards best first. Unmatched slots go last.

    ``needed_items``: uniqueNames of finished items you have not mastered. ``owned_parts``
    and ``owned_items`` (from an inventory) drop parts you already have.
    """
    needed_items = needed_items or set()
    owned_parts = owned_parts or {}
    owned_items = owned_items or set()
    out: list[Ranked] = []
    for i, m in enumerate(matches):
        e = m.entry
        if e is None:
            out.append(Ranked(i, m, False, None, "not recognised"))
            continue
        needed = (
            e.final_item in needed_items
            and owned_parts.get(e.unique_name, 0) == 0
            and e.final_item not in owned_items
        )
        plat = _price(prices, e)
        why = []
        if needed:
            why.append(f"needed for {e.final_name}")
        if e.vaulted:
            why.append("vaulted")
        if plat is not None:
            why.append(f"{plat:g}p")
        if e.ducats:
            why.append(f"{e.ducats} ducats")
        out.append(Ranked(i, m, needed, plat, ", ".join(why) or "-"))
    out.sort(
        key=lambda r: (
            r.match.entry is not None,
            r.needed,
            bool(r.match.entry and r.match.entry.vaulted),
            r.platinum or 0.0,
            (r.match.entry.ducats or 0) if r.match.entry else 0,
        ),
        reverse=True,
    )
    return out


def account_needs(settings) -> tuple[set[str], dict[str, int], set[str]]:
    """(not-mastered items, owned parts, owned items) from the latest snapshot + inventory.

    Returns empty sets when there is no snapshot; ranking then skips the "needed" step.
    """
    needed: set[str] = set()
    parts: dict[str, int] = {}
    owned: set[str] = set()
    try:
        from ..account.store import SnapshotStore
        from ..account.sync import reparse
        from ..codex import Codex
        from ..report import build_report

        codex = Codex(settings.codex_path)
        snap = SnapshotStore(settings.snapshots_dir).load("latest")
        report = build_report(reparse(snap, codex), codex)
        needed = {m.unique_name for m in report.missing} | {
            o.unique_name for o in report.owned if not o.mastered
        }
    except Exception:
        return set(), {}, set()
    inv_path = settings.home / "inventory.json"
    if inv_path.exists():
        try:
            from ..inventory import load_inventory

            inv = load_inventory(inv_path)
            parts = {**inv.misc, **inv.recipes}
            owned = {u for u, n in inv.equipment.items() if n > 0}
        except Exception:
            pass
    return needed, parts, owned
