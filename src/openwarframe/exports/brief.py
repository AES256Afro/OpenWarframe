"""LLM planning brief: Markdown with YAML front matter plus a compact JSON twin.

Written so a model with no other context can plan sessions: what the account has,
what is closest to done, what is missing and how to get it, and what the data
cannot see. Two budgets: compact (about 8k tokens) and full (everything).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from ..account.summary import MASTERY_CATEGORIES
from ..report.model import MissingItem, Report
from .extras import ExportExtras, diff_lines, rank_test_line, rank_test_ready
from .tables import best_sources

BRIEF_SCHEMA = "openwarframe.brief/1"
BUDGETS = {"compact": 8000, "full": 60000}

INSTRUCTIONS = """You are helping a Warframe player plan what to do next. Use only the data below plus
general game knowledge. Prefer recommendations that (1) finish items closest to done,
(2) use sources available right now (farmable relics, vendors where standing is the
only cost, mission drops), and (3) respect the player's mastery rank. Say when the
data cannot answer something (for example resource counts, owned blueprints or relic
inventory are not visible in a profile-only snapshot)."""


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def _priority(m: MissingItem) -> tuple:
    order = -1 if m.owned else m.priority()  # owned already: only needs leveling
    cat = MASTERY_CATEGORIES.index(m.category) if m.category in MASTERY_CATEGORIES else 99
    return (m.above_your_mr, order, cat, m.name)


def brief_name(budget: str = "compact") -> str:
    """File stem: ``account-brief`` for compact, ``account-brief-full`` for full."""
    return "account-brief" if budget == "compact" else f"account-brief-{budget}"


def build_brief(
    report: Report, budget: str = "compact", extras: ExportExtras | None = None
) -> tuple[str, dict]:
    extras = extras or ExportExtras()
    compact = budget == "compact"
    h, ms = report.headline, report.mastery
    limit = BUDGETS[budget]
    who = report.identity.display_name or "the player"

    leveling = sorted((o for o in report.owned if not o.mastered), key=lambda o: o.xp_to_30)
    missing = sorted(report.missing, key=_priority)
    sc_missing = [n for n in report.nodes if not n.completed]
    sp_by_planet: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for n in report.nodes:
        sp_by_planet[n.planet][1] += 1
        if n.steel_path:
            sp_by_planet[n.planet][0] += 1
    acq = Counter(m.acquisition for m in report.missing)

    fm = [
        "---",
        f"schema: {BRIEF_SCHEMA}",
        f"generated: {report.generated_at.isoformat(timespec='minutes')}",
        f"snapshot: {report.snapshot_taken_at.isoformat(timespec='minutes')}",
        f"budget: {budget}",
        f"coverage: [{', '.join(report.coverage)}]",
        "sources: {" + ", ".join(f"{s.source}: {s.version}" for s in report.sources) + "}",
        "---",
    ]
    out = list(fm)
    out += ["", "# How to use this brief", "", INSTRUCTIONS, ""]
    out += ["# Account", ""]
    age = f", playing {h.account_age_days // 365} years" if h.account_age_days else ""
    hours = f", {h.play_time_hours:,.0f} h played" if h.play_time_hours else ""
    out.append(f"- {who}: Mastery Rank {h.mastery_rank} on {report.identity.platform}{age}{hours}.")
    out.append(
        f"- Items: {h.items_mastered} mastered, {h.items_leveling} owned but below rank 30, "
        f"{h.items_missing} never leveled, of {h.items_total} masterable."
    )
    out.append(
        f"- Star chart {h.starchart_done}/{h.starchart_total} nodes; Steel Path {h.steel_path_done}/{h.starchart_total}."
    )
    out.append(
        f"- Syndicates at max rank: {h.syndicates_maxed}. Achievements tracked: {h.achievements_tracked}."
    )
    out.append(
        f"- Mastery XP from items {ms.from_items:,} + intrinsics {ms.from_intrinsics:,} = {ms.visible_total:,}; "
        f"rank {ms.rank} needs {ms.rank_threshold:,}, rank {ms.rank + 1} needs {ms.next_rank_threshold:,}."
    )
    out.append(
        f"- Estimated total mastery XP (ESTIMATE) about {ms.estimated_total:,}: adds star chart "
        f"{ms.from_starchart:,}, Steel Path {ms.from_steel_path:,} and junctions {ms.from_junctions:,}. {ms.note}"
    )
    test = rank_test_line(report)
    if test:
        out.append(f"- {test}")
    if extras.standing_left_total is not None:
        main = extras.standing_left.get("Default")
        main_text = (
            f" (main syndicates: {main:,})" if main is not None and len(extras.standing_left) > 1 else ""
        )
        out.append(f"- Standing left today: {extras.standing_left_total:,}{main_text}.")
    for n in report.notes:
        out.append(f"- Data note: {n}")
    if extras.goals:
        out += ["", "# Your goals", ""]
        out.append("Items the player marked as goals in the OpenWarframe app. Plan around these first.")
        out.append("")
        out += [f"- {g}" for g in extras.goals]
    changes = diff_lines(extras.diff)
    if changes:
        out += ["", "# Since last sync", ""]
        out += [f"- {line}" for line in changes]
    out += [
        "",
        "# Mastery by category",
        "",
        "| category | mastered | leveling | never leveled | total |",
        "|---|---|---|---|---|",
    ]
    for c in report.categories:
        out.append(f"| {c.category} | {c.mastered} | {c.leveling} | {c.missing} | {c.total} |")

    out += ["", "# Closest to done: owned, below rank 30", ""]
    for o in leveling[: (40 if compact else 200)]:
        out.append(f"- {o.name} ({o.category}) rank {o.rank}, {o.xp_to_30:,} affinity to 30")

    out += ["", "# Never leveled: how they can be obtained", ""]
    out.append("Counts by route: " + "; ".join(f"{k}: {v}" for k, v in acq.most_common()))
    out += ["", "## Obtainable now or cheaply (within your MR first)", ""]
    shown = 0
    shown_items: list[MissingItem] = []
    for m in missing:
        line = f"- {m.name} ({m.category}, MR {m.mastery_req}) - {m.acquisition}"
        src = best_sources(m, limit=2)
        if src:
            line += f" - {src}"
        if compact and m.hard_to_get():
            continue
        out.append(line)
        shown += 1
        shown_items.append(m)
        if estimate_tokens("\n".join(out)) > limit * 0.75:
            out.append(f"- ... {len(missing) - shown} more not shown (budget {budget}); see account.json")
            break
    rest = [m for m in missing if m.hard_to_get()]
    out += ["", "## Vaulted, trade-only or outside the drop tables", ""]
    if compact:
        by_cat = Counter(m.category for m in rest)
        out.append("- " + ", ".join(f"{c}: {n}" for c, n in by_cat.most_common()))
        out.append("- Examples: " + ", ".join(m.name for m in rest[:25]))
    else:
        for m in rest:
            out.append(
                f"- {m.name} ({m.category}) - {m.acquisition}"
                + (f" - {m.market_slug}" if m.market_slug else "")
            )

    out += ["", "# Star chart", ""]
    if sc_missing:
        out.append("- Not completed: " + ", ".join(f"{n.name} ({n.planet})" for n in sc_missing))
    else:
        out.append("- Every star chart node completed.")
    sp_lines = [f"{p} {d}/{t}" for p, (d, t) in sp_by_planet.items() if d < t]
    if sp_lines:
        out.append("- Steel Path progress by planet (done/total): " + ", ".join(sp_lines))

    out += ["", "# Syndicates", ""]
    out.append("- " + ", ".join(f"{s.name} rank {s.rank} ({s.standing:,})" for s in report.syndicates))

    top_usage = report.usage[:10]
    if top_usage:
        out += ["", "# Most used gear (lifetime kills)", ""]
        out.append("- " + ", ".join(f"{u.name} {u.kills:,}" for u in top_usage))
    text = "\n".join(out) + "\n"

    def missing_row(m: MissingItem) -> dict:
        return {
            "name": m.name,
            "category": m.category,
            "mastery_req": m.mastery_req,
            "acquisition": m.acquisition,
            "sources": best_sources(m, limit=2),
        }

    data: dict = {
        "schema": BRIEF_SCHEMA,
        "budget": budget,
        "snapshot": report.snapshot_taken_at.isoformat(),
        "coverage": report.coverage,
        "headline": report.headline.model_dump(),
        "mastery": report.mastery.model_dump(),
        "rank_test_ready": rank_test_ready(report),
        "standing_left_today": extras.standing_left_total,
        "goals": extras.goals,
        "since_last_sync": changes,
        "categories": [c.model_dump() for c in report.categories],
    }
    if compact:
        # the same content as the Markdown, so the JSON twin stays about as small
        data["leveling"] = [
            {"name": o.name, "category": o.category, "rank": o.rank, "xp_to_30": o.xp_to_30}
            for o in leveling[:40]
        ]
        data["missing"] = [missing_row(m) for m in shown_items]
        data["missing_not_shown"] = len(missing) - len(shown_items) - len(rest)
        data["hard_to_get"] = {
            "by_category": dict(Counter(m.category for m in rest).most_common()),
            "examples": [m.name for m in rest[:25]],
        }
        data["starchart_missing"] = [{"name": n.name, "planet": n.planet} for n in sc_missing]
        data["usage"] = [{"name": u.name, "kills": u.kills} for u in top_usage]
    else:
        data["leveling"] = [
            {"name": o.name, "category": o.category, "rank": o.rank, "xp_to_30": o.xp_to_30} for o in leveling
        ]
        data["missing"] = [missing_row(m) for m in missing]
        data["starchart_missing"] = [{"node": n.node, "name": n.name, "planet": n.planet} for n in sc_missing]
        data["usage"] = [{"name": u.name, "kills": u.kills} for u in report.usage]
    data["syndicates"] = [{"name": s.name, "rank": s.rank, "standing": s.standing} for s in report.syndicates]
    data["notes"] = report.notes
    return text, data


def write_brief(
    report: Report, directory: Path, budget: str = "compact", extras: ExportExtras | None = None
) -> tuple[Path, Path, int]:
    text, data = build_brief(report, budget, extras)
    md = directory / f"{brief_name(budget)}.md"
    js = md.with_suffix(".json")
    md.write_text(text, encoding="utf-8")
    if budget == "compact":
        js.write_text(json.dumps(data, separators=(",", ":"), default=str), encoding="utf-8")
    else:
        js.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return md, js, estimate_tokens(text)
