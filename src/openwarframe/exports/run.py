"""Run a set of exporters for one report into one directory."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from ..report.model import Report
from .brief import write_brief
from .data import write_csv, write_json, write_sqlite
from .extras import ExportExtras
from .tables import build_tables
from .xlsx import write_xlsx

FORMATS = ("json", "sqlite", "csv", "xlsx", "llm", "dashboard", "guide")
# Formats that print a PDF with the browser. Each print starts the browser and mostly waits
# on it, so these run side by side instead of one after another.
PRINTING = ("llm", "dashboard", "guide")

log = logging.getLogger(__name__)


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
    report: Report,
    out_dir: Path,
    formats: list[str],
    *,
    brief_budget: str = "compact",
    guide_pdf: bool = True,
    guide_docx: bool = True,
    copy_to: list[str] | None = None,
    share: bool = False,
    extras: ExportExtras | None = None,
    translator=None,
) -> list[ExportResult]:
    """``translator`` (codex.translate.Translator): item names in another language."""
    unknown = set(formats) - set(FORMATS)
    if unknown:
        raise ValueError(f"unknown formats: {sorted(unknown)}; choose from {', '.join(FORMATS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    extras = extras or ExportExtras()
    if translator:
        import dataclasses

        report = translator.model(report)
        extras = dataclasses.replace(extras, goals=[translator.by_name(g) for g in extras.goals])
        diff = extras.diff
        if diff is not None and dataclasses.is_dataclass(diff):
            extras.diff = dataclasses.replace(
                diff,
                newly_mastered=[translator.by_name(n) for n in diff.newly_mastered],
                newly_leveled=[translator.by_name(n) for n in diff.newly_leveled],
                rank_ups=[(translator.by_name(n), a, b) for n, a, b in diff.rank_ups],
            )
    tables = build_tables(report)
    if translator:
        for t in tables:
            translator.strings(t.rows)
    stamp = report.snapshot_taken_at.strftime("%Y-%m-%d")
    rows = sum(len(t.rows) for t in tables)

    def one(fmt: str) -> list[ExportResult]:
        # one format failing (a workbook open in Excel, a missing knowledge base) must not
        # cost the player every format after it
        results: list[ExportResult] = []
        try:
            _run_one(
                fmt,
                report,
                out_dir,
                tables,
                rows,
                stamp,
                results,
                brief_budget,
                guide_pdf,
                guide_docx,
                copy_to,
                share,
                extras,
            )
        except PermissionError as exc:
            name = Path(exc.filename).name if exc.filename else fmt
            results.append(
                ExportResult(
                    "warning", out_dir, f"{fmt}: {name} is open in another program; close it and export again"
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported in the result table instead
            log.debug("%s export failed", fmt, exc_info=True)
            results.append(ExportResult("warning", out_dir, f"{fmt} failed: {exc}"))
        return results

    parallel = [f for f in formats if f in PRINTING] if guide_pdf else []
    done: dict[str, list[ExportResult]] = {}
    if len(parallel) > 1:
        with ThreadPoolExecutor(max_workers=len(parallel)) as pool:
            futures = {f: pool.submit(one, f) for f in parallel}
            for f in formats:
                if f not in futures:
                    done[f] = one(f)
            for f, fut in futures.items():
                done[f] = fut.result()
    else:
        for f in formats:
            done[f] = one(f)
    return [r for f in formats for r in done[f]]


def _run_one(
    fmt: str,
    report: Report,
    out_dir: Path,
    tables,
    rows: int,
    stamp: str,
    results: list[ExportResult],
    brief_budget: str,
    guide_pdf: bool,
    guide_docx: bool,
    copy_to: list[str] | None,
    share: bool,
    extras: ExportExtras,
) -> None:
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
        p = write_xlsx(report, tables, out_dir / f"OpenWarframe-{stamp}.xlsx", extras)
        sheets = len(tables) - 1 + (1 if extras.diff is not None and not extras.diff.is_empty() else 0)
        results.append(ExportResult("xlsx", p, f"{sheets} sheets, {rows:,} rows"))
    elif fmt == "llm":
        md, js, tokens = write_brief(report, out_dir, brief_budget, extras)
        results.append(ExportResult("llm", md, f"{brief_budget}, about {tokens:,} tokens (+ {js.name})"))
        from .brief_pdf import write_brief_documents

        who = report.identity.display_name or "Account"
        _html, pdf_path, warning = write_brief_documents(md, pdf=guide_pdf, title=f"{who} - planning brief")
        if pdf_path:
            results.append(ExportResult("llm-pdf", pdf_path, "planning brief as PDF, for agents"))
        if warning:
            results.append(ExportResult("warning", md, warning))
    elif fmt == "dashboard":
        from .dashboard import write_dashboard

        files = write_dashboard(report, out_dir, pdf=guide_pdf, docx=guide_docx, extras=extras)
        results.append(ExportResult("dashboard", files.html, "account dashboard, single HTML file"))
        if files.pdf:
            results.append(ExportResult("dashboard-pdf", files.pdf, "dashboard as PDF"))
        if files.docx:
            results.append(ExportResult("dashboard-docx", files.docx, "dashboard as Word document"))
        for w in files.warnings:
            results.append(ExportResult("warning", files.html, w))
    elif fmt == "guide":
        from ..guide import build_mastery_plan, load_kb, write_guide_bundle

        plan = build_mastery_plan(report, load_kb())
        bundle = write_guide_bundle(
            plan, out_dir, pdf=guide_pdf, docx=guide_docx, copy_to=copy_to, share=share
        )
        results.append(
            ExportResult("guide", bundle.html, f"road to MR {plan.target_rank}, {len(plan.phases)} phases")
        )
        if bundle.docx:
            results.append(ExportResult("guide-docx", bundle.docx, "Word version of the guide"))
        if bundle.pdf:
            results.append(ExportResult("guide-pdf", bundle.pdf, "PDF version of the guide"))
        for target, folder in bundle.cloud.items():
            results.append(ExportResult(f"copy-{target}", folder, "guide files copied for sync"))
        for w in bundle.warnings:
            results.append(ExportResult("warning", bundle.html, w))
