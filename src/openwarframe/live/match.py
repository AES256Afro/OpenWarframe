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
import logging
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

log = logging.getLogger(__name__)
MIN_SCORE = 0.62
NEAR_TIE = 0.08  # a runner-up this close means the read could be either item
EXACT_READ = 0.85  # a whole name read with at most small OCR slips


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
    need: int = 1  # how many the build takes (two barrels for Akstiletto Prime)
    makes: str | None = None  # for a part blueprint: the part it builds


@dataclass
class Match:
    raw: str
    entry: RewardEntry | None
    score: float
    # the read fits another name almost as well (or is a cut-off start of the name):
    # show it, but never recommend it as the pick
    unsure_of: str | None = None


@dataclass
class Ranked:
    slot: int
    match: Match
    needed: bool
    platinum: float | None
    reason: str


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
        from ..codex.queries import farmable_relics

        farmable = farmable_relics(conn)
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

        from ..codex.recipes import RecipeGraph

        graph = RecipeGraph(conn)
        entries = []
        for uid, relics in relics_of.items():
            final = graph.final_item(uid)
            made = graph.result.get(uid)
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
                    need=graph.needed_count(uid, final),
                    makes=made if made and made != final else None,
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
        second, second_score = None, 0.0
        sm = SequenceMatcher(autojunk=False)
        sm.set_seq2(key)
        floor = 0.0
        for e in self.entries:
            sm.set_seq1(e.key)
            if sm.real_quick_ratio() < floor or sm.quick_ratio() < floor:
                continue
            s = sm.ratio()
            if s > best_score:
                second, second_score = best, best_score
                best, best_score = e, s
            elif s > second_score and e is not best:
                second, second_score = e, s
            floor = second_score  # a candidate that can't beat the runner-up can't matter
        if best is None or best_score < MIN_SCORE:
            return Match(raw, None, best_score)
        unsure = None
        if second is not None and second.key != best.key and best_score - second_score < NEAR_TIE:
            unsure = second.name
        elif best.key.startswith(key) and len(key) < len(best.key):
            unsure = best.name  # a cut-off read: "SARYN PRIME" could be any Saryn Prime part
        return Match(raw, best, best_score, unsure)

    def match_all(self, raws: list[str]) -> list[Match]:
        return [self.match(r) for r in raws]

    def pick_layout(self, layouts: dict[int, list[str]]) -> tuple[int, list[Match]]:
        """Choose the squad size the screen shows.

        Every layout's boxes sit somewhere on the screen, and boxes that straddle two names
        (or half of one) still fuzzy-match something: half of "Forma Blueprint" matches
        Forma Blueprint. The smaller layouts also reuse the bigger ones' boxes (2 players =
        the middle two of 4, 1 player = the middle of 3), so "every slot matched" would
        shrink a 4-player screen with one bad read to 2 players and drop two rewards.

        What tells the right layout apart is whole names read almost exactly. So, in order:
        the most near-exact reads; then the most recognised text (sum of match scores);
        then the fewest boxes with no text at all (a 2-player screen read as 4 has two
        empty boxes); then the bigger squad.
        """
        best: tuple[tuple, int, list[Match]] | None = None
        for n, raws in layouts.items():
            ms = self.match_all(raws)
            exact = sum(1 for m in ms if m.entry and m.score >= EXACT_READ)
            recognised = round(sum(m.score for m in ms if m.entry), 3)
            empty = sum(1 for r in raws if not normalize(r))
            key = (exact, recognised, -empty, n)
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
        held = owned_parts.get(e.unique_name, 0) + (owned_parts.get(e.makes, 0) if e.makes else 0)
        needed = e.final_item in needed_items and held < e.need and e.final_item not in owned_items
        plat = _price(prices, e)
        why = []
        if m.unsure_of:
            why.append(f"unsure: read '{m.raw}'")
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
            r.match.unsure_of is None,  # never recommend a guess over a sure read
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
        try:  # close it: an open codex blocks the game-data update on Windows
            snap = SnapshotStore(settings.snapshots_dir).load("latest")
            report = build_report(reparse(snap, codex), codex)
        finally:
            codex.close()
        needed = {m.unique_name for m in report.missing} | {
            o.unique_name for o in report.owned if not o.mastered
        }
    except Exception as exc:  # noqa: BLE001 - ranking still works without account data
        log.info("reward ranking without account data: %s", exc)
        return set(), {}, set()
    inv_path = settings.inventory_path
    if inv_path.exists():
        try:
            from ..inventory import load_inventory

            inv = load_inventory(inv_path)
            parts = {**inv.misc, **inv.recipes}
            owned = {u for u, n in inv.equipment.items() if n > 0}
        except Exception:
            pass
    return needed, parts, owned
