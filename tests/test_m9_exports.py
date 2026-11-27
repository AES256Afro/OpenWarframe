"""Export polish: readable workbook, right file names, rank tests, offline pages, safer helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from openwarframe import printing
from openwarframe.account import parse_profile
from openwarframe.account.store import diff_snapshots
from openwarframe.cli import app, shortcut_script
from openwarframe.exports import run_exports
from openwarframe.exports.brief import build_brief, write_brief
from openwarframe.exports.brief_pdf import write_brief_documents
from openwarframe.exports.extras import ExportExtras, load_goal_names, rank_test_ready, readable_id
from openwarframe.exports.xlsx import header_label, tidy_caps
from openwarframe.report import Report, build_report

from .test_exports import _codex, _profile

RED = "FFC7CE"


@pytest.fixture
def report(tmp_path: Path) -> Report:
    cx = _codex(tmp_path)
    snap = parse_profile(_profile(), codex=cx, taken_at=datetime(2026, 10, 16, tzinfo=UTC))
    return build_report(snap, cx)


def _test_ready(report: Report) -> Report:
    t = report.mastery.next_rank_threshold + 10
    ms = report.mastery.model_copy(update={"visible_total": t, "estimated_total": t})
    return report.model_copy(update={"mastery": ms})


def test_rank_test_not_announced_on_the_estimate_alone(report: Report):
    """The estimate can be off by a few thousand; only the counted XP opens a test."""
    from openwarframe.exports.extras import rank_test_ready

    t = report.mastery.next_rank_threshold
    ms = report.mastery.model_copy(update={"visible_total": t - 100, "estimated_total": t + 500})
    assert rank_test_ready(report.model_copy(update={"mastery": ms})) is None


# -- workbook -----------------------------------------------------------------------------------


def test_headers_are_spelled_for_players():
    assert header_label("above_your_mr") == "Above your MR"
    assert header_label("mastery_req") == "MR"
    assert header_label("wiki_url") == "Wiki"
    assert header_label("xp_to_30") == "XP to 30"
    assert header_label("unique_name") == "ID"
    assert header_label("best_sources") == "Best sources"
    assert tidy_caps("EXTERMINATE") == "Exterminate"
    assert tidy_caps("Mobile Defense") == "Mobile Defense"


def test_workbook_reads_yes_no_and_leaves_not_yet_plain(report: Report, tmp_path: Path):
    run_exports(report, tmp_path, ["xlsx"], guide_pdf=False)
    wb = load_workbook(next(tmp_path.glob("*.xlsx")))
    ws = wb["Never leveled"]
    heads = [c.value for c in ws[1]]
    assert "MR" in heads and "Above your MR" in heads and "Wiki" in heads
    assert "Above Your Mr" not in heads and "Wiki Url" not in heads
    col = heads.index("Above your MR")
    values = {r[col].value for r in ws.iter_rows(min_row=2)}
    assert values <= {"Yes", "No"} and values
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            assert not any(isinstance(c.value, bool) for c in row), sheet.title
    assert ws.page_setup.orientation == "landscape" and ws.print_title_rows
    assert ws.column_dimensions[chr(ord("A") + heads.index("Best sources"))].width <= 50

    star = wb["Star chart"]
    for rng in star.conditional_formatting:
        for rule in rng.rules:
            fill = rule.dxf.fill.fgColor.rgb if rule.dxf and rule.dxf.fill else ""
            assert RED not in str(fill), "not-yet nodes must not be red"

    summary = wb["Summary"]
    numbers = [summary.cell(row=5, column=c).value for c in range(2, 14, 2)]
    assert any(isinstance(v, int) for v in numbers)  # counts are numbers, not text


def test_workbook_and_brief_show_rank_test_ready(report: Report, tmp_path: Path):
    ready = _test_ready(report)
    assert rank_test_ready(report) is None and rank_test_ready(ready) == report.mastery.rank + 1
    text, data = build_brief(ready)
    assert f"Rank {report.mastery.rank + 1} test available" in text and "23 hours" in text
    assert data["rank_test_ready"] == report.mastery.rank + 1
    run_exports(ready, tmp_path, ["xlsx"], guide_pdf=False)
    ws = load_workbook(next(tmp_path.glob("*.xlsx")))["Summary"]
    cells = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert any("test available" in v for v in cells)


# -- brief ----------------------------------------------------------------------------------------


def test_full_brief_documents_use_their_own_names(report: Report, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(printing, "find_browser", lambda: None)
    md, js, _ = write_brief(report, tmp_path, "full")
    assert md.name == "account-brief-full.md" and js.name == "account-brief-full.json"
    html_path, pdf_path, warning = write_brief_documents(md)
    assert html_path.name == "account-brief-full.html" and pdf_path is None
    page = html_path.read_text(encoding="utf-8")
    assert "account-brief-full.md" in page and "account-brief.md" not in page
    assert warning == printing.NO_BROWSER_WARNING
    assert "#8f6a17" in page and "Cinzel" in page  # same theme as the dashboard and guide


def test_compact_json_matches_markdown_and_is_smaller(report: Report, tmp_path: Path):
    _, small, _ = write_brief(report, tmp_path, "compact")
    _, full, _ = write_brief(report, tmp_path, "full")
    assert small.stat().st_size < full.stat().st_size
    data = json.loads(small.read_text(encoding="utf-8"))
    assert "hard_to_get" in data and "missing_not_shown" in data


def test_brief_extras_goals_changes_and_standing(report: Report, tmp_path: Path):
    (tmp_path / "c").mkdir()
    cx = _codex(tmp_path / "c")
    older = parse_profile(_profile(), codex=cx, taken_at=datetime(2026, 10, 15, tzinfo=UTC))
    newer_profile = _profile()
    newer_profile["Results"][0]["Affiliations"][0]["Standing"] = 5000
    newer = parse_profile(newer_profile, codex=cx, taken_at=datetime(2026, 10, 16, tzinfo=UTC))
    extras = ExportExtras(
        diff=diff_snapshots(older, newer),
        goals=["Braton", "Rhino Prime"],
        standing_left={"Default": 16000, "Cetus": 4000},
    )
    text, data = build_brief(report, extras=extras)
    assert "# Your goals" in text and "- Rhino Prime" in text
    assert "# Since last sync" in text and "+4,000" in text
    assert "Standing left today: 20,000 (main syndicates: 16,000)" in text
    assert data["goals"] == ["Braton", "Rhino Prime"] and data["standing_left_today"] == 20000

    run_exports(report, tmp_path / "x", ["xlsx"], guide_pdf=False, extras=extras)
    wb = load_workbook(next((tmp_path / "x").glob("*.xlsx")))
    assert "Since last sync" in wb.sheetnames


def test_goal_names_come_from_the_codex_or_the_id(tmp_path: Path):
    (tmp_path / "app-prefs.json").write_text(
        json.dumps(
            {"goals": ["/Lotus/Weapons/Tenno/Rifle/Braton", "/Lotus/Powersuits/Odd/RhinoPrimeThing", 5]}
        ),
        encoding="utf-8",
    )
    cx = _codex(tmp_path)
    assert load_goal_names(tmp_path, cx) == ["Braton", "Rhino Prime Thing"]
    assert load_goal_names(tmp_path / "nowhere") == []
    assert readable_id("/Lotus/Types/AKVasto") == "AK Vasto"


# -- dashboard and guide pages ---------------------------------------------------------------


def test_pages_load_no_web_fonts(report: Report):
    from openwarframe.exports.dashboard import render_dashboard_html
    from openwarframe.guide import build_mastery_plan, load_kb, render_mastery_html

    assert "fonts.googleapis.com" not in render_dashboard_html(report)
    guide = render_mastery_html(build_mastery_plan(report, load_kb()))
    assert "fonts.googleapis.com" not in guide and "size:A4" in guide


def test_dashboard_rank_test_and_empty_usage(report: Report):
    from openwarframe.exports.dashboard import render_dashboard_html

    ready = _test_ready(report).model_copy(update={"usage": []})
    html = render_dashboard_html(ready, extras=ExportExtras(standing_left={"Default": 1234}))
    assert f"Rank {report.mastery.rank + 1} test ready" in html and "0 more" not in html
    assert "Most used" not in html
    assert "1,234</b> standing left today" in html


def test_word_files_are_a4_with_author(report: Report, tmp_path: Path):
    from docx import Document

    from openwarframe.guide import build_mastery_plan, load_kb, write_mastery_docx

    path = write_mastery_docx(build_mastery_plan(report, load_kb()), tmp_path / "g.docx")
    doc = Document(str(path))
    assert round(doc.sections[0].page_width.cm) == 21 and round(doc.sections[0].page_height.cm) == 30
    assert doc.core_properties.author == "OpenWarframe" and doc.core_properties.title
    assert "PAGE" in doc.sections[0].footer._element.xml


def test_printing_formats_run_together_and_say_one_short_line(report: Report, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(printing, "find_browser", lambda: None)
    results = run_exports(report, tmp_path, ["llm", "json", "dashboard"], guide_pdf=True, guide_docx=False)
    kinds = [r.format for r in results]
    assert kinds[0] == "llm" and "json" in kinds and kinds.index("json") < kinds.index("dashboard")
    warnings = [r.detail for r in results if r.format == "warning"]
    assert warnings and all(w == printing.NO_BROWSER_WARNING for w in warnings)


def test_failed_print_keeps_browser_output_out_of_the_message(tmp_path: Path, monkeypatch):
    fake = tmp_path / "chrome"
    fake.write_text("", encoding="utf-8")
    page = tmp_path / "p.html"
    page.write_text("<p>x</p>", encoding="utf-8")

    class Done:
        stderr, stdout = "[1234:ERROR] something noisy", ""

    monkeypatch.setattr(printing.subprocess, "run", lambda *a, **k: Done())
    pdf, warning = printing.try_print(page, tmp_path / "p.pdf", browser=fake)
    assert pdf is None and "noisy" not in warning and "p.pdf" in warning


# -- command line ---------------------------------------------------------------------------------


def test_shortcut_script_escapes_quotes():
    script = shortcut_script(
        r"C:\Users\O'Brien\Desktop\OpenWarframe.lnk", "C:\\x'y.exe", "C:\\Users\\O'Brien", "i"
    )
    assert "O''Brien" in script and "x''y.exe" in script
    assert "'C:\\Users\\O'Brien" not in script


def test_tasklist_runs_by_full_path(monkeypatch):
    from openwarframe.sources.account.session import tasklist_path

    monkeypatch.setenv("SYSTEMROOT", "D:\\Win")
    assert tasklist_path().replace("\\", "/").endswith("Win/System32/tasklist.exe")


def test_schema_needs_out_and_is_hidden(home: Path, tmp_path: Path):
    runner = CliRunner()
    assert runner.invoke(app, ["schema"]).exit_code != 0
    assert "schema" not in runner.invoke(app, ["--help"]).output.split("Commands")[-1]
    out = tmp_path / "s.json"
    assert runner.invoke(app, ["schema", "--out", str(out)]).exit_code == 0 and out.exists()


def test_account_show_prints_not_set(home: Path):
    result = CliRunner().invoke(app, ["account", "show"])
    assert result.exit_code == 0 and "[not set]" in result.output


def test_platform_help_names_the_consoles():
    result = CliRunner().invoke(app, ["account", "set", "--help"])
    assert "Switch" in " ".join(result.output.split()) and "Android" in result.output


def test_export_choices_are_remembered(home: Path):
    from openwarframe.config import load_settings, save_settings

    s = load_settings()
    s.remember_export(budget="full", pdf=False, nonsense=1)
    save_settings(s)
    again = load_settings()
    assert again.export_prefs == {"budget": "full", "pdf": False}


# -- profile over HTTPS ---------------------------------------------------------------------------


def test_console_profile_falls_back_to_http_only_when_https_cannot_connect():
    from openwarframe.sources.account.profile import fetch_profile

    seen: list[str] = []

    class Client:
        def get(self, url, force=False):
            seen.append(url)
            if url.startswith("https://"):
                raise httpx.ConnectError("no route")
            return b'{"Results": [{"DisplayName": "x"}]}'

    assert fetch_profile(Client(), "a" * 24, "ps4")["Results"]
    assert seen[0].startswith("https://content-ps4") and seen[1].startswith("http://content-ps4")

    class Pc(Client):
        pass

    with pytest.raises(httpx.ConnectError):
        fetch_profile(Pc(), "a" * 24, "pc")
