"""Run a set of exporters for one report into one directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..report.model import Report
from .brief import write_brief
from .data import write_csv, write_json, write_sqlite
from .tables import build_tables
from .xlsx import write_xlsx

FORMATS = ("json", "sqlite", "csv", "xlsx", "llm", "guide")


@dataclass
class ExportResult:
    format: str
    path: Path
    detail: str

    @property
    def size(self) -> int:
        if self.path.is_dir():
            return sum(p.stat().st_size for p in self.path.glob("*"))
        return self.path.stat().st_size if self.path.exists() else 0


def run_exports(
    report: Report, out_dir: Path, formats: list[str], *, brief_budget: str = "compact"
) -> list[ExportResult]:
    unknown = set(formats) - set(FORMATS)
    if unknown:
        raise ValueError(f"unknown formats: {sorted(unknown)}; choose from {', '.join(FORMATS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = build_tables(report)
    stamp = report.snapshot_taken_at.strftime("%Y-%m-%d")
    results: list[ExportResult] = []
    rows = sum(len(t.rows) for t in tables)
    for fmt in formats:
        if fmt == "json":
            p = write_json(report, out_dir / "account.json")
            results.append(ExportResult("json", p, f"schema {report.schema_version}"))
        elif fmt == "sqlite":
            p = write_sqlite(tables, report, out_dir / "account.sqlite")
            results.append(ExportResult("sqlite", p, f"{len(tables) + 1} tables, {rows:,} rows"))
        elif fmt == "csv":
            p = write_csv(tables, out_dir / "csv")
            results.append(ExportResult("csv", p, f"{len(tables)} files"))
        elif fmt == "xlsx":
            p = write_xlsx(report, tables, out_dir / f"OpenWarframe-{stamp}.xlsx")
            results.append(ExportResult("xlsx", p, f"{len(tables) - 1} sheets, {rows:,} rows"))
        elif fmt == "llm":
            md, js, tokens = write_brief(report, out_dir, brief_budget)
            results.append(ExportResult("llm", md, f"{brief_budget}, about {tokens:,} tokens (+ {js.name})"))
        elif fmt == "guide":
            from ..guide import build_mastery_plan, load_kb, write_mastery_html

            plan = build_mastery_plan(report, load_kb())
            p = write_mastery_html(plan, out_dir / "mastery-plan.html")
            results.append(
                ExportResult("guide", p, f"road to MR {plan.target_rank}, {len(plan.phases)} phases")
            )
    return results
