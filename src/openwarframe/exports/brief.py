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
    a = m.acquisition
    order = 0 if "farmable now" in a else 1 if "Vendor" in a else 2 if ("drops" in a or "Bount" in a) else 3
    cat = MASTERY_CATEGORIES.index(m.category) if m.category in MASTERY_CATEGORIES else 99
    return (m.above_your_mr, order, cat, m.name)


def build_brief(report: Report, budget: str = "compact") -> tuple[str, dict]:
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
    out.append(f"- Syndicates at max rank: {h.syndicates_maxed}. Achievements tracked: {h.achievements_tracked}.")
    out.append(
        f"- Mastery XP visible {ms.visible_total:,}; rank {ms.rank} needs {ms.rank_threshold:,}, "
        f"rank {ms.rank + 1} needs {ms.next_rank_threshold:,}. {ms.note}"
    )
    for n in report.notes:
        out.append(f"- Data note: {n}")
    out += ["", "# Mastery by category", "", "| category | mastered | leveling | never leveled | total |", "|---|---|---|---|---|"]
    for c in report.categories:
        out.append(f"| {c.category} | {c.mastered} | {c.leveling} | {c.missing} | {c.total} |")

    out += ["", "# Closest to done: owned, below rank 30", ""]
    for o in leveling[: (40 if budget == "compact" else 200)]:
        out.append(f"- {o.name} ({o.category}) rank {o.rank}, {o.xp_to_30:,} affinity to 30")

    out += ["", "# Never leveled: how they can be obtained", ""]
    out.append("Counts by route: " + "; ".join(f"{k}: {v}" for k, v in acq.most_common()))
    out += ["", "## Obtainable now or cheaply (within your MR first)", ""]
    header_len = estimate_tokens("\n".join(out))
    shown = 0
    for m in missing:
        line = f"- {m.name} ({m.category}, MR {m.mastery_req}) - {m.acquisition}"
        src = best_sources(m, limit=2)
        if src:
            line += f" - {src}"
        if budget == "compact" and ("vaulted" in m.acquisition or m.acquisition.startswith(("Trade", "Market", "Not in"))):
            continue
        out.append(line)
        shown += 1
        if estimate_tokens("\n".join(out)) > limit * 0.75:
            out.append(f"- ... {len(missing) - shown} more not shown (budget {budget}); see account.json")
            break
    rest = [m for m in missing if "vaulted" in m.acquisition or m.acquisition.startswith(("Trade", "Market", "Not in"))]
    out += ["", "## Vaulted, trade-only or outside the drop tables", ""]
    if budget == "compact":
        by_cat = Counter(m.category for m in rest)
        out.append("- " + ", ".join(f"{c}: {n}" for c, n in by_cat.most_common()))
        out.append("- Examples: " + ", ".join(m.name for m in rest[:25]))
    else:
        for m in rest:
            out.append(f"- {m.name} ({m.category}) - {m.acquisition}" + (f" - {m.market_slug}" if m.market_slug else ""))

    out += ["", "# Star chart", ""]
    if sc_missing:
        out.append("- Not completed: " + ", ".join(f"{n.name} ({n.planet})" for n in sc_missing))
    else:
        out.append("- Every star chart node completed.")
    sp_lines = [f"{p} {d}/{t}" for p, (d, t) in sp_by_planet.items() if d < t]
    if sp_lines:
        out.append("- Steel Path remaining by planet: " + ", ".join(sp_lines))

    out += ["", "# Syndicates", ""]
    out.append("- " + ", ".join(f"{s.name} rank {s.rank} ({s.standing:,})" for s in report.syndicates))

    top_usage = report.usage[:10]
    if top_usage:
        out += ["", "# Most used gear (lifetime kills)", ""]
        out.append("- " + ", ".join(f"{u.name} {u.kills:,}" for u in top_usage))
    text = "\n".join(out) + "\n"

    data = {
        "schema": BRIEF_SCHEMA,
        "budget": budget,
        "snapshot": report.snapshot_taken_at.isoformat(),
        "coverage": report.coverage,
        "headline": report.headline.model_dump(),
        "mastery": report.mastery.model_dump(),
        "categories": [c.model_dump() for c in report.categories],
        "leveling": [{"name": o.name, "category": o.category, "rank": o.rank, "xp_to_30": o.xp_to_30} for o in leveling],
        "missing": [
            {
                "name": m.name,
                "category": m.category,
                "mastery_req": m.mastery_req,
                "acquisition": m.acquisition,
                "sources": best_sources(m, limit=2),
            }
            for m in missing
        ],
        "starchart_missing": [{"node": n.node, "name": n.name, "planet": n.planet} for n in sc_missing],
        "syndicates": [{"name": s.name, "rank": s.rank, "standing": s.standing} for s in report.syndicates],
        "notes": report.notes,
    }
    return text, data


def write_brief(report: Report, directory: Path, budget: str = "compact") -> tuple[Path, Path, int]:
    text, data = build_brief(report, budget)
    md = directory / f"account-brief{'' if budget == 'compact' else '-' + budget}.md"
    js = md.with_suffix(".json")
    md.write_text(text, encoding="utf-8")
    js.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return md, js, estimate_tokens(text)
