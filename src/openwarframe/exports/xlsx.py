"""Styled Excel workbook (openpyxl).

Visual identity follows docs/mockups: navy headers, Orokin gold accents, green for
mastered/farmable, amber for leveling, red for vaulted/missing.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..report.model import Report
from .extras import ExportExtras, diff_rows, rank_test_line
from .tables import Table

NAVY = "1F3B5A"
GOLD = "B58A2E"
INK = "1B2130"
MUTED = "6B7385"
GREEN_BG, GREEN_FG = "C6EFCE", "006100"
AMBER_BG, AMBER_FG = "FFEB9C", "9C5700"
RED_BG, RED_FG = "FFC7CE", "9C0006"
BLUE_BG = "DDEBF7"

HEADER_FILL = PatternFill("solid", fgColor=NAVY)
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=16, color=INK)
SUB_FONT = Font(size=10, color=MUTED, italic=True)
KPI_VALUE = Font(bold=True, size=18, color=INK)
KPI_LABEL = Font(size=9, color=MUTED)
THIN = Side(style="thin", color="D4D4D4")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

WIDTHS = {
    "name": 28,
    "item": 26,
    "part": 26,
    "category": 16,
    "acquisition": 30,
    "best_sources": 50,
    "where": 34,
    "detail": 46,
    "wiki_url": 14,
    "unique_name": 14,
    "item_unique_name": 14,
    "description": 60,
    "planet": 14,
    "mission_type": 16,
    "key": 34,
    "value": 22,
    "source": 22,
    "version": 30,
    "fetched_at": 26,
}
# Column headers spelled the way players write them; anything else is title-cased
HEADERS = {
    "mastery_req": "MR",
    "above_your_mr": "Above your MR",
    "wiki_url": "Wiki",
    "unique_name": "ID",
    "item_unique_name": "Item ID",
    "xp": "XP",
    "xp_to_30": "XP to 30",
    "mastery_xp": "Mastery XP",
    "market_slug": "warframe.market",
    "equip_hours": "Hours equipped",
    "percent_mastered": "% mastered",
}
WRAP = {"best_sources", "detail", "description", "acquisition"}
# True/False columns shown as Yes/No; the formatting rules below match these words
YES, NO = "Yes", "No"
HIDDEN = {"unique_name", "item_unique_name", "key", "tag", "node"}
SHEET_ORDER = [
    "missing_items",
    "missing_sources",
    "owned_items",
    "star_chart",
    "syndicates",
    "achievements",
    "intrinsics",
    "weapon_usage",
    "sources",
]


def _v(v):
    """A cell value openpyxl will accept: control characters in game text would raise."""
    return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v


def _no_formulas(wb: Workbook) -> None:
    """Store every value as data. This workbook writes no formulas of its own, so a cell that
    openpyxl took for one ("=HYPERLINK(...)" in an item name from upstream data) is text."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"


def _fill(color: str) -> PatternFill:
    return PatternFill("solid", fgColor=color)


def header_label(col: str) -> str:
    return HEADERS.get(col) or col.replace("_", " ").capitalize()


_SMALL_WORDS = {"and", "or", "of", "the", "a", "an", "to", "in", "on", "for"}


def tidy_caps(text: str) -> str:
    """'EXTERMINATE' -> 'Exterminate', 'ARCHWING DEFENSE' -> 'Archwing Defense'. Mixed case is kept."""
    if not isinstance(text, str) or not text.isupper():
        return text
    words = text.lower().split(" ")
    return " ".join(w if i and w in _SMALL_WORDS else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _print_setup(ws: Worksheet, header_row: int | None = 1) -> None:
    """Landscape A4, fit to one page wide, the header row repeated on every printed page."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    if header_row:
        ws.print_title_rows = f"{header_row}:{header_row}"
    ws.print_options.horizontalCentered = True


def _write_table(ws: Worksheet, t: Table, *, start_row: int = 1) -> int:
    for ci, col in enumerate(t.columns, start=1):
        c = ws.cell(row=start_row, column=ci, value=header_label(col))
        c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BOX
        c.alignment = Alignment(vertical="center")
        letter = get_column_letter(ci)
        ws.column_dimensions[letter].width = WIDTHS.get(col, max(10, min(22, len(col) + 4)))
        if col in HIDDEN:
            ws.column_dimensions[letter].hidden = True
    for ri, row in enumerate(t.rows, start=start_row + 1):
        for ci, col in enumerate(t.columns, start=1):
            v = row.get(col)
            if isinstance(v, list | dict):
                v = str(v)
            elif isinstance(v, bool):
                v = YES if v else NO
            elif col == "mission_type":
                v = tidy_caps(v)
            cell = ws.cell(row=ri, column=ci, value=_v(v))
            if col == "wiki_url" and v:
                cell.hyperlink = v
                cell.value = "wiki"
                cell.font = Font(color="0563C1", underline="single")
            elif col in WRAP:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    last = start_row + len(t.rows)
    ws.freeze_panes = ws.cell(row=start_row + 1, column=2)
    if t.rows:
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(t.columns))}{last}"
    _print_setup(ws, start_row)
    return last


def _col(t: Table, name: str) -> str:
    return get_column_letter(t.columns.index(name) + 1)


def _summary_sheet(wb: Workbook, report: Report, tables: dict[str, Table], extras: ExportExtras) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False
    h = report.headline
    who = report.identity.display_name or "Account"
    ws["B2"] = _v(f"{who} · Mastery Rank {h.mastery_rank}")
    ws["B2"].font = TITLE_FONT
    sub = f"{report.identity.platform.upper()}"
    if h.account_age_days:
        sub += f" · {h.account_age_days // 365} years"
    if h.play_time_hours:
        sub += f" · {h.play_time_hours:,.0f} hours played"
    sub += f" · snapshot {report.snapshot_taken_at:%Y-%m-%d %H:%M} UTC"
    ws["B3"] = sub
    ws["B3"].font = SUB_FONT

    # plain counts are stored as numbers; "x / y" pairs stay text
    kpis: list[tuple[int | str, str]] = [
        (f"{h.items_mastered} / {h.items_total}", "Items mastered"),
        (h.items_leveling, "Owned, not rank 30"),
        (h.items_missing, "Never leveled"),
        (f"{h.starchart_done} / {h.starchart_total}", "Star chart"),
        (f"{h.steel_path_done} / {h.starchart_total}", "Steel Path"),
        (h.syndicates_maxed, "Syndicates maxed"),
    ]
    for i, (value, label) in enumerate(kpis):
        col = 2 + i * 2
        v = ws.cell(row=5, column=col, value=value)
        v.font = KPI_VALUE
        v.alignment = Alignment(horizontal="left")
        if isinstance(value, int):
            v.number_format = "#,##0"
        lab = ws.cell(row=6, column=col, value=label)
        lab.font = KPI_LABEL
        for r in (5, 6):
            ws.cell(row=r, column=col).fill = _fill("F3F5FA")
            ws.cell(row=r, column=col + 1).fill = _fill("F3F5FA")
    for c in range(2, 14):
        ws.column_dimensions[get_column_letter(c)].width = 13

    # categories table
    cat = tables["categories"]
    ws.cell(row=8, column=2, value="Mastery by category").font = Font(bold=True, color=GOLD, size=12)
    headers = ["Category", "Mastered", "Leveling", "Never leveled", "Total", "% mastered"]
    for i, hd in enumerate(headers):
        c = ws.cell(row=9, column=2 + i, value=hd)
        c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BOX
    ws.column_dimensions["B"].width = 18
    for ri, row in enumerate(cat.rows, start=10):
        vals = [
            row["category"],
            row["mastered"],
            row["leveling"],
            row["missing"],
            row["total"],
            row["percent_mastered"] / 100,
        ]
        for i, v in enumerate(vals):
            c = ws.cell(row=ri, column=2 + i, value=_v(v))
            c.border = BOX
            if i == 5:
                c.number_format = "0%"
    last = 9 + len(cat.rows)
    ws.conditional_formatting.add(
        f"G10:G{last}",
        FormulaRule(formula=["G10>=0.75"], fill=_fill(GREEN_BG), font=Font(color=GREEN_FG)),
    )
    ws.conditional_formatting.add(
        f"G10:G{last}",
        FormulaRule(formula=["G10<0.25"], fill=_fill(RED_BG), font=Font(color=RED_FG)),
    )

    chart = BarChart()
    chart.type = "bar"
    chart.grouping = "stacked"
    chart.overlap = 100
    chart.title = "Mastered / leveling / never leveled"
    chart.height = 9
    chart.width = 18
    data = Reference(ws, min_col=3, max_col=5, min_row=9, max_row=last)
    cats = Reference(ws, min_col=2, min_row=10, max_row=last)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    for series, color in zip(chart.series, ("B58A2E", "4FD1EA", "D4D8E2"), strict=False):
        series.graphicalProperties.solidFill = color
        series.graphicalProperties.line.solidFill = color
    chart.y_axis.majorGridlines = None
    ws.add_chart(chart, "I8")

    # notes and mastery estimate
    row = last + 3
    m = report.mastery
    ws.cell(row=row, column=2, value="Mastery XP").font = Font(bold=True, color=GOLD, size=12)
    test = rank_test_line(report)
    lines = [
        f"Items + intrinsics: {m.visible_total:,} (items {m.from_items:,} + intrinsics {m.from_intrinsics:,})",
        f"Estimated total: {m.estimated_total:,} (estimate; adds star chart {m.from_starchart:,}, "
        f"Steel Path {m.from_steel_path:,}, junctions {m.from_junctions:,})",
        test
        or f"Rank {m.rank} needs {m.rank_threshold:,}; rank {m.rank + 1} needs {m.next_rank_threshold:,}",
        m.note,
    ] + report.notes
    for i, line in enumerate(lines, start=1):
        c = ws.cell(row=row + i, column=2, value=_v(line))
        c.font = Font(color=MUTED if i > 3 else INK, size=10, bold=bool(test) and i == 3)
    ws.cell(
        row=row + len(lines) + 2,
        column=2,
        value="Sheets: "
        + ", ".join(t.title for t in tables.values() if t.name not in ("summary", "categories")),
    ).font = SUB_FONT
    _print_setup(ws, None)


def _changes_sheet(wb: Workbook, extras: ExportExtras) -> None:
    """'Since last sync': what changed from the previous snapshot, when there is one."""
    rows = diff_rows(extras.diff)
    if not rows:
        return
    d = extras.diff
    ws = wb.create_sheet("Since last sync", 1)
    ws["A1"] = "Since last sync"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"{d.before:%Y-%m-%d %H:%M} to {d.after:%Y-%m-%d %H:%M} UTC"
    ws["A2"].font = SUB_FONT
    for ci, head in enumerate(("What", "Detail"), start=1):
        c = ws.cell(row=4, column=ci, value=head)
        c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BOX
    for ri, (what, detail) in enumerate(rows, start=5):
        ws.cell(row=ri, column=1, value=_v(what))
        ws.cell(row=ri, column=2, value=_v(detail))
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 60
    ws.freeze_panes = "A5"
    _print_setup(ws, 4)


def write_xlsx(report: Report, tables: list[Table], path: Path, extras: ExportExtras | None = None) -> Path:
    extras = extras or ExportExtras()
    by_name = {t.name: t for t in tables}
    wb = Workbook()
    _summary_sheet(wb, report, by_name, extras)
    for name in SHEET_ORDER:
        t = by_name[name]
        ws = wb.create_sheet(t.title[:31])
        last = _write_table(ws, t)
        first = 2
        if name == "missing_items" and t.rows:
            col = _col(t, "acquisition")
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                FormulaRule(
                    formula=[f'ISNUMBER(SEARCH("farmable now",{col}{first}))'],
                    fill=_fill(GREEN_BG),
                    font=Font(color=GREEN_FG),
                ),
            )
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                FormulaRule(formula=[f'ISNUMBER(SEARCH("Vendor",{col}{first}))'], fill=_fill(BLUE_BG)),
            )
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                FormulaRule(
                    formula=[f'ISNUMBER(SEARCH("vaulted",{col}{first}))'],
                    fill=_fill(AMBER_BG),
                    font=Font(color=AMBER_FG),
                ),
            )
            above = _col(t, "above_your_mr")
            ws.conditional_formatting.add(
                f"A{first}:A{last}",
                FormulaRule(formula=[f'${above}{first}="{YES}"'], font=Font(color="9AA0AE", italic=True)),
            )
        if name == "missing_sources" and t.rows:
            col = _col(t, "farmable")
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                CellIsRule(
                    operator="equal", formula=[f'"{YES}"'], fill=_fill(GREEN_BG), font=Font(color=GREEN_FG)
                ),
            )
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                CellIsRule(
                    operator="equal", formula=[f'"{NO}"'], fill=_fill(RED_BG), font=Font(color=RED_FG)
                ),
            )
        if name == "owned_items" and t.rows:
            col = _col(t, "mastered")
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                CellIsRule(
                    operator="equal", formula=[f'"{YES}"'], fill=_fill(GREEN_BG), font=Font(color=GREEN_FG)
                ),
            )
            ws.conditional_formatting.add(
                f"{col}{first}:{col}{last}",
                CellIsRule(
                    operator="equal", formula=[f'"{NO}"'], fill=_fill(AMBER_BG), font=Font(color=AMBER_FG)
                ),
            )
            for c in ("xp", "xp_to_30", "mastery_xp"):
                letter = _col(t, c)
                for r in range(first, last + 1):
                    ws[f"{letter}{r}"].number_format = "#,##0"
        if name == "star_chart" and t.rows:
            for c, (yes_bg, yes_fg) in (
                ("completed", (GREEN_BG, GREEN_FG)),
                ("steel_path", ("E4DCFB", "4B2FB0")),
            ):
                letter = _col(t, c)
                ws.conditional_formatting.add(
                    f"{letter}{first}:{letter}{last}",
                    CellIsRule(
                        operator="equal", formula=[f'"{YES}"'], fill=_fill(yes_bg), font=Font(color=yes_fg)
                    ),
                )
                # "not yet" stays plain: a red sea of unplayed nodes reads as failure
        if name == "syndicates" and t.rows:
            letter = _col(t, "rank")
            ws.conditional_formatting.add(
                f"{letter}{first}:{letter}{last}",
                CellIsRule(
                    operator="greaterThanOrEqual",
                    formula=["5"],
                    fill=_fill(GREEN_BG),
                    font=Font(color=GREEN_FG),
                ),
            )
            ws.conditional_formatting.add(
                f"{letter}{first}:{letter}{last}",
                CellIsRule(operator="lessThan", formula=["0"], fill=_fill(RED_BG), font=Font(color=RED_FG)),
            )
            for r in range(first, last + 1):
                ws[f"{_col(t, 'standing')}{r}"].number_format = "#,##0"
        if name == "weapon_usage" and t.rows:
            for c in ("kills", "headshots", "xp"):
                letter = _col(t, c)
                for r in range(first, last + 1):
                    ws[f"{letter}{r}"].number_format = "#,##0"
    _changes_sheet(wb, extras)
    wb.properties.title = "OpenWarframe account export"
    wb.properties.creator = "OpenWarframe"
    _no_formulas(wb)
    wb.save(path)
    return path
