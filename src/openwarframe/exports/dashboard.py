"""The account dashboard: one self-contained HTML page, plus PDF and Word versions.

The page loads nothing from other sites (fonts fall back to what is installed).

Built only from the Report model, so share mode, numbers and wording match every
other export. Same visual language as the mastery guide (Orokin gold for mastery,
Tenno cyan for things to do next, light and dark themes, a white print theme).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from ..report.build import rank_threshold
from ..report.model import MissingItem, Report
from .extras import RANK_TEST_COOLDOWN, ExportExtras, rank_test_ready
from .tables import best_sources

CSS = """
:root{
  --bg:#eef1f6; --panel:#ffffff; --panel2:#f3f5f9; --fg:#172033; --muted:#566178; --line:#d6dce7;
  --gold:#8f6a17; --gold-soft:#f3e7c9; --cyan:#0d7891; --cyan-soft:#d9f0f5; --track:#e2e6ee;
  --ok:#1f8a55; --warn:#a8650c; --bad:#b4372f; --violet:#5b43c4;
  --display:"Cinzel", "Trajan Pro", Georgia, serif;
  --body:"Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, Consolas, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0a0f1d; --panel:#121a2c; --panel2:#18223a; --fg:#e7ecf6; --muted:#9aa6bf; --line:#27334f;
    --gold:#d9b35b; --gold-soft:#3a3016; --cyan:#4fd1ea; --cyan-soft:#12313b; --track:#222d47;
    --ok:#5fd49a; --warn:#f0b35b; --bad:#f07a70; --violet:#a98cf5; color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0a0f1d; --panel:#121a2c; --panel2:#18223a; --fg:#e7ecf6; --muted:#9aa6bf; --line:#27334f;
  --gold:#d9b35b; --gold-soft:#3a3016; --cyan:#4fd1ea; --cyan-soft:#12313b; --track:#222d47;
  --ok:#5fd49a; --warn:#f0b35b; --bad:#f07a70; --violet:#a98cf5; color-scheme: dark;
}
*{box-sizing:border-box}
body{margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 var(--body)}
.wrap{max-width:1240px; margin:0 auto; padding:24px max(16px, env(safe-area-inset-left, 0px)) 56px; display:grid; grid-template-columns:repeat(12, minmax(0,1fr)); gap:18px}
.wrap > nav, .wrap > footer{grid-column:1 / -1}
h1,h2{font-family:var(--display); margin:0; letter-spacing:.02em; text-wrap:balance}
h1{font-size:clamp(1.8rem, 4vw, 2.6rem); line-height:1.1}
h2{font-size:.78rem; font-family:var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--gold); display:flex; gap:10px; align-items:baseline}
h2 .sub{margin-left:auto; color:var(--muted); letter-spacing:0; text-transform:none; font:400 .82rem var(--body); text-align:right}
.eyebrow{font:600 .72rem/1 var(--mono); letter-spacing:.16em; text-transform:uppercase; color:var(--gold)}
.muted{color:var(--muted)}
.num{font-family:var(--mono); font-variant-numeric:tabular-nums}
.card{background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px 20px; display:grid; gap:14px; align-content:start; min-width:0}
.s12{grid-column:span 12} .tall{grid-row:span 2} .s7{grid-column:span 7} .s5{grid-column:span 5} .s6{grid-column:span 6} .s4{grid-column:span 4} .s8{grid-column:span 8}
.hero{display:grid; grid-template-columns:170px 1fr; gap:24px; align-items:center}
.hero > div{min-width:0}
.ring{position:relative; width:170px; height:170px}
.ring svg{transform:rotate(-90deg); display:block}
.ring .lbl{position:absolute; inset:0; display:grid; place-content:center; text-align:center}
.ring .mr{font:700 3rem/1 var(--display); color:var(--gold)}
.ring .t{font:600 .66rem var(--mono); letter-spacing:.2em; color:var(--muted); margin-top:4px}
.who{display:flex; flex-wrap:wrap; gap:6px 18px; font-family:var(--mono); font-size:.84rem; color:var(--muted); margin:8px 0 14px}
.who b{color:var(--fg); font-weight:600}
.kpis{display:grid; grid-template-columns:repeat(6, minmax(0,1fr)); gap:10px}
.kpi{background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:10px 12px; min-width:0}
.kpi .v{font:700 1.3rem/1.2 var(--mono); font-variant-numeric:tabular-nums}
.kpi .v small{font-size:.8rem; color:var(--muted); font-weight:500}
.kpi .k{font:600 .66rem var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin-top:2px}
.row{display:grid; grid-template-columns:150px 1fr 92px; gap:12px; align-items:center; font-size:.92rem; padding:5px 0; border-bottom:1px dashed var(--line)}
.row:last-child{border-bottom:0}
.row .c{text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums; color:var(--muted)}
.bar{height:12px; border-radius:6px; background:var(--track); overflow:hidden; display:flex}
.bar i{display:block; height:100%}
.m{background:var(--gold)} .o{background:var(--cyan)} .sp{background:var(--violet)} .neg{background:var(--bad)}
.legend{display:flex; flex-wrap:wrap; gap:14px; color:var(--muted); font-size:.8rem}
.legend i{display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; vertical-align:-1px}
.list{display:grid; gap:8px}
.it{display:grid; grid-template-columns:1fr auto; gap:4px 12px; align-items:baseline; background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:9px 12px; min-width:0}
.it b{font-weight:600}
.it .meta{font:600 .72rem var(--mono); color:var(--muted); white-space:nowrap}
.it .mini{grid-column:1/-1; height:6px; border-radius:3px; background:var(--track); overflow:hidden}
.it .mini i{display:block; height:100%; background:var(--cyan)}
.it .src{grid-column:1/-1; font-size:.84rem; color:var(--muted); overflow-wrap:anywhere}
.chip{display:inline-block; font:600 .66rem var(--mono); letter-spacing:.06em; text-transform:uppercase; border-radius:4px; padding:2px 6px; background:var(--cyan-soft); color:var(--cyan); margin-left:6px; white-space:nowrap}
.chip.v{background:var(--gold-soft); color:var(--gold)}
.planets{display:grid; grid-template-columns:repeat(auto-fill, minmax(118px, 1fr)); gap:8px}
.pl{background:var(--panel2); border:1px solid var(--line); border-radius:10px; padding:9px 10px; display:grid; gap:4px; min-width:0}
.pl .p{font-size:.8rem; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.pl .v{font:700 1rem var(--mono)}
.pl .bar{height:6px}
.pl .s{font:600 .7rem var(--mono); color:var(--violet)}
.pl.done{border-color:var(--gold)}
.syn{display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:4px 26px}
.sy{display:grid; grid-template-columns:minmax(0,1fr) 80px 52px; gap:8px; align-items:center; font-size:.86rem}
.sy span:first-child{white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.sy .bar{height:8px}
.sy .r{text-align:right; font-family:var(--mono)}
.notes{display:grid; gap:6px; font-size:.88rem}
.notes p{margin:0; background:var(--cyan-soft); border-radius:8px; padding:8px 12px}
.tools{display:flex; flex-wrap:wrap; gap:8px}
.tool{display:inline-flex; gap:8px; align-items:center; font:600 .86rem var(--body); color:var(--fg); background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:7px 12px; text-decoration:none; cursor:pointer}
.tool .ext{font:600 .68rem var(--mono); letter-spacing:.08em; color:var(--gold)}
.tool:hover{border-color:var(--gold)}
.tool:focus-visible{outline:2px solid var(--cyan); outline-offset:2px}
footer{color:var(--muted); font-size:.78rem; display:flex; flex-wrap:wrap; gap:6px 18px; border-top:1px solid var(--line); padding-top:12px}
@page{size:A4 landscape; margin:10mm}
@media print{
  :root, :root[data-theme="dark"], :root:not([data-theme="light"]){
    --bg:#ffffff; --panel:#ffffff; --panel2:#f4f6f9; --fg:#172033; --muted:#566178; --line:#d6dce7;
    --gold:#8f6a17; --gold-soft:#f6edd6; --cyan:#0d7891; --cyan-soft:#e3f3f7; --track:#e4e8ef;
    --ok:#1f8a55; --warn:#a8650c; --bad:#b4372f; --violet:#5b43c4; color-scheme: light;
  }
  body{font-size:10pt; -webkit-print-color-adjust:exact; print-color-adjust:exact}
  .wrap{max-width:none; padding:0; gap:10px}
  .wrap{gap:10px}
  .tools{display:none !important}
  .card{break-inside:avoid; padding:12px 14px; gap:10px}
}
@media (max-width:900px){
  .s7,.s5,.s6,.s4,.s8{grid-column:span 12}
  .hero{grid-template-columns:1fr}
  .kpis{grid-template-columns:repeat(2, minmax(0,1fr))}
  .syn{grid-template-columns:1fr}
  .tall{grid-row:auto}
  .row{grid-template-columns:110px 1fr 76px}
}
"""

PRINT_SCRIPT = (
    "document.querySelectorAll('[data-print]').forEach(function(b){"
    "b.addEventListener('click',function(){window.print();});});"
)


def _e(v) -> str:
    return escape(str(v), quote=True)


def _pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


@dataclass
class PlanetRow:
    planet: str
    done: int = 0
    total: int = 0
    steel: int = 0


@dataclass
class DashboardData:
    """Everything the page shows, computed once and shared by HTML and Word."""

    title: str
    mastery_total: int
    rank_progress: float  # 0..1 within the current rank
    xp_to_next: int
    test_ready: int | None = None  # rank whose test can be taken now
    closest: list = field(default_factory=list)
    get_next: list[MissingItem] = field(default_factory=list)
    planets: list[PlanetRow] = field(default_factory=list)


def _get_next(report: Report, limit: int) -> list[MissingItem]:
    def score(m: MissingItem) -> tuple:
        order = m.priority()
        return (order if order < 3 else 9, m.category != "Warframe", m.name)

    pool = [m for m in report.missing if not m.above_your_mr and not m.owned]  # owned: nothing to get
    pool = [m for m in pool if score(m)[0] < 9]
    return sorted(pool, key=score)[:limit]


def dashboard_data(report: Report, *, closest: int = 12, get_next: int = 12) -> DashboardData:
    ms = report.mastery
    total = ms.estimated_total or ms.visible_total
    lo, hi = rank_threshold(ms.rank), rank_threshold(ms.rank + 1)
    progress = max(0.0, min(1.0, (total - lo) / max(1, hi - lo)))
    planets: dict[str, PlanetRow] = defaultdict(lambda: PlanetRow(""))
    order: list[str] = []
    for n in report.nodes:
        if n.planet not in planets:
            order.append(n.planet)
        p = planets[n.planet]
        p.planet = n.planet
        p.total += 1
        p.done += n.completed
        p.steel += n.steel_path
    leveling = sorted((o for o in report.owned if not o.mastered), key=lambda o: o.xp_to_30)
    who = report.identity.display_name or "Account"
    return DashboardData(
        title=who,
        mastery_total=total,
        rank_progress=progress,
        xp_to_next=max(0, hi - total),
        test_ready=rank_test_ready(report),
        closest=leveling[:closest],
        get_next=_get_next(report, get_next),
        planets=[planets[p] for p in order],
    )


def _ring(rank: int, progress: float) -> str:
    r = 74
    circ = 2 * 3.14159 * r
    off = circ * (1 - progress)
    return (
        '<div class="ring"><svg width="170" height="170" viewBox="0 0 170 170" aria-hidden="true">'
        f'<circle cx="85" cy="85" r="{r}" fill="none" stroke="var(--track)" stroke-width="12"/>'
        f'<circle cx="85" cy="85" r="{r}" fill="none" stroke="var(--gold)" stroke-width="12" '
        f'stroke-linecap="round" stroke-dasharray="{circ:.1f}" stroke-dashoffset="{off:.1f}"/></svg>'
        f'<div class="lbl"><div class="mr">{rank}</div><div class="t">MASTERY</div></div></div>'
    )


def _xp_line(d: DashboardData, report: Report) -> str:
    ms = report.mastery
    est = "estimated " if ms.estimated_total else ""
    head = f'Mastery XP ({est}total) <span class="num">{d.mastery_total:,}</span>'
    if d.test_ready:
        return f"{head} &nbsp;&middot;&nbsp; <b>Rank {d.test_ready} test ready</b>. {_e(RANK_TEST_COOLDOWN)}"
    return (
        f"{head} &nbsp;&middot;&nbsp; <span class='num'>{d.xp_to_next:,}</span> more to reach rank {ms.rank + 1}"
        f" &nbsp;&middot;&nbsp; rank {ms.rank + 1} is at <span class='num'>{ms.next_rank_threshold:,}</span>"
    )


def render_dashboard_html(
    report: Report,
    *,
    pdf_name: str | None = None,
    docx_name: str | None = None,
    extras: ExportExtras | None = None,
) -> str:
    extras = extras or ExportExtras()
    d = dashboard_data(report)
    h, ms, ident = report.headline, report.mastery, report.identity
    out: list[str] = []
    a = out.append
    a('<!doctype html><html lang="en"><head><meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
    a(f"<title>{_e(d.title)} - Warframe account</title>")
    a(f"<style>{CSS}</style></head><body><main class='wrap'>")

    # toolbar
    a('<nav class="tools" aria-label="Save or share">')
    if pdf_name:
        a(f'<a class="tool" href="{_e(pdf_name)}" target="_blank"><span class="ext">PDF</span>Open PDF</a>')
    else:
        a('<button type="button" class="tool" data-print><span class="ext">PDF</span>Save as PDF</button>')
    if docx_name:
        a(f'<a class="tool" href="{_e(docx_name)}" download><span class="ext">DOCX</span>Word document</a>')
    a("</nav>")

    # hero
    who_bits = [f"<b>{_e(ident.platform.upper())}</b>"]
    if ident.clan:
        who_bits.append(f"Clan <b>{_e(ident.clan)}</b>")
    if ident.created_at:
        who_bits.append(f"Tenno since <b>{ident.created_at:%B %Y}</b>")
    if h.play_time_hours:
        who_bits.append(f"<b>{h.play_time_hours:,.0f}</b> h played")
    if h.missions_completed:
        who_bits.append(f"<b>{h.missions_completed:,}</b> missions")
    who_bits.append(f"snapshot <b>{report.snapshot_taken_at:%Y-%m-%d %H:%M}</b> UTC")
    if extras.standing_left_total is not None:
        who_bits.append(f"<b>{extras.standing_left_total:,}</b> standing left today")
    kpis = [
        (f"{h.items_mastered}<small> / {h.items_total}</small>", "Items mastered"),
        (f"{h.items_leveling}", "Owned, below 30"),
        (f"{h.items_missing}", "Never leveled"),
        (f"{h.starchart_done}<small> / {h.starchart_total}</small>", "Star chart"),
        (f"{h.steel_path_done}<small> / {h.starchart_total}</small>", "Steel Path"),
        (f"{h.syndicates_maxed}", "Syndicates maxed"),
    ]
    a('<section class="card s12"><div class="hero">')
    a(_ring(h.mastery_rank, 1.0 if d.test_ready else d.rank_progress))
    a("<div>")
    a('<div class="eyebrow">OpenWarframe · account dashboard</div>')
    a(f"<h1>{_e(d.title)}</h1>")
    a(f'<div class="who">{"".join(f"<span>{b}</span>" for b in who_bits)}</div>')
    a(
        '<div class="kpis">'
        + "".join(f'<div class="kpi"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in kpis)
        + "</div>"
    )
    a(f'<p class="muted" style="margin:12px 0 0">{_xp_line(d, report)}</p>')
    a("</div></div></section>")

    # arsenal
    a(
        '<section class="card s7"><h2>Arsenal<span class="sub">mastered · owned below rank 30 · never leveled</span></h2><div>'
    )
    for c in report.categories:
        a(
            f'<div class="row"><span>{_e(c.category)}</span><div class="bar">'
            f'<i class="m" style="width:{_pct(c.mastered, c.total)}%"></i>'
            f'<i class="o" style="width:{_pct(c.leveling, c.total)}%"></i></div>'
            f'<span class="c">{c.mastered} / {c.total}</span></div>'
        )
    a(
        '</div><div class="legend"><span><i class="m"></i>mastered</span>'
        '<span><i class="o"></i>owned, below rank 30</span><span><i style="background:var(--track)"></i>never leveled</span></div></section>'
    )

    # closest to done
    a(
        f'<section class="card s5 tall"><h2>Closest to done<span class="sub">{h.items_leveling} owned items below rank 30</span></h2><div class="list">'
    )
    for o in d.closest:
        pct = _pct(o.rank, 30)
        a(
            f'<div class="it"><b>{_e(o.name)}</b><span class="meta">rank {o.rank} · {o.xp_to_30:,} to go</span>'
            f'<div class="mini"><i style="width:{pct}%"></i></div></div>'
        )
    if not d.closest:
        a('<p class="muted">Every item you have leveled is at rank 30.</p>')
    a("</div></section>")

    # most used
    top = report.usage[:10]
    if top:
        a('<section class="card s7"><h2>Most used<span class="sub">lifetime kills</span></h2><div>')
        peak = max((u.kills for u in top), default=1) or 1
        for u in top:
            a(
                f'<div class="row"><span>{_e(u.name)}</span><div class="bar"><i class="o" style="width:{_pct(u.kills, peak)}%"></i></div>'
                f'<span class="c">{u.kills:,}</span></div>'
            )
        a("</div></section>")

    # get next
    a(
        '<section class="card s12"><h2>Get next<span class="sub">never leveled, within your mastery rank, obtainable now: farmable relics, vendors, drops</span></h2>'
    )
    a('<div class="list" style="grid-template-columns:repeat(auto-fill, minmax(min(340px, 100%), 1fr))">')
    for m in d.get_next:
        chip = "v" if m.has("vendor") else ""
        a(
            f'<div class="it"><b>{_e(m.name)}<span class="chip {chip}">{_e(m.acquisition)}</span></b>'
            f'<span class="meta">{_e(m.category)} · MR {m.mastery_req}</span>'
            f'<div class="src">{_e(best_sources(m, limit=1))}</div></div>'
        )
    if not d.get_next:
        a('<p class="muted">Nothing obtainable right now that you have not leveled.</p>')
    a("</div></section>")

    # star chart
    a(
        f'<section class="card s12"><h2>Star chart<span class="sub">{h.starchart_done} of {h.starchart_total} nodes · '
        f'{h.steel_path_done} Steel Path</span></h2><div class="planets">'
    )
    for p in d.planets:
        done = " done" if p.done == p.total else ""
        a(
            f'<div class="pl{done}"><span class="p" title="{_e(p.planet)}">{_e(p.planet)}</span>'
            f'<span class="v">{p.done}/{p.total}</span>'
            f'<div class="bar"><i class="m" style="width:{_pct(p.done, p.total)}%"></i></div>'
            f'<span class="s">SP {p.steel}/{p.total}</span>'
            f'<div class="bar"><i class="sp" style="width:{_pct(p.steel, p.total)}%"></i></div></div>'
        )
    a("</div></section>")

    # syndicates
    shown = [s for s in report.syndicates if not (s.name.startswith("Nightwave") and s.rank <= 0)]
    hidden = len(report.syndicates) - len(shown)
    note = f" · {hidden} empty Nightwave seasons hidden" if hidden else ""
    a(
        f'<section class="card s12"><h2>Syndicates<span class="sub">{h.syndicates_maxed} at max rank{note}</span></h2>'
        '<div class="syn">'
    )
    for s in shown:
        top = max(1, s.max_rank)
        if s.rank >= 0:
            bar = f'<i class="m" style="width:{_pct(min(s.rank, top), top)}%"></i>'
        else:
            bar = f'<i class="neg" style="width:{_pct(min(-s.rank, 2), 2)}%"></i>'
        a(
            f'<div class="sy"><span title="{_e(s.name)}">{_e(s.name)}</span><div class="bar">{bar}</div>'
            f'<span class="r">{s.rank}<span class="muted">/{top}</span></span></div>'
        )
    a("</div></section>")

    # coverage + sources
    a('<section class="card s12"><h2>What this page can and cannot see</h2><div class="notes">')
    for n in report.notes:
        a(f"<p>{_e(n)}</p>")
    a(f"<p>{_e(ms.note)}</p>")
    a("</div></section>")
    a("<footer>")
    for s in report.sources:
        a(f"<span>{_e(s.source)} <span class='num'>{_e(s.version)}</span></span>")
    if ident.anonymized:
        a("<span>share mode: name and clan removed</span>")
    a("<span>Generated by OpenWarframe</span></footer>")
    a(f"</main><script>{PRINT_SCRIPT}</script></body></html>")
    return "".join(out)


# -- Word ------------------------------------------------------------------------------------


def build_dashboard_docx(report: Report, extras: ExportExtras | None = None):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Pt

    from ..guide.word import add_table, muted, style_document

    extras = extras or ExportExtras()
    d = dashboard_data(report, closest=20, get_next=25)
    h, ms = report.headline, report.mastery
    doc = Document()
    style_document(doc, title=f"{d.title} - Warframe account")
    for section in doc.sections:  # tables are wide: landscape, like the PDF
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    doc.add_paragraph(d.title, style="Title")
    sub = [report.identity.platform.upper()]
    if report.identity.created_at:
        sub.append(f"Tenno since {report.identity.created_at:%B %Y}")
    if h.play_time_hours:
        sub.append(f"{h.play_time_hours:,.0f} h played")
    sub.append(f"snapshot {report.snapshot_taken_at:%Y-%m-%d %H:%M} UTC")
    muted(doc, " · ".join(sub))

    doc.add_heading("At a glance", level=1)
    add_table(
        doc,
        ["Measure", "Value"],
        [
            ["Mastery rank", str(h.mastery_rank)],
            [
                "Mastery XP (estimated total)" if ms.estimated_total else "Mastery XP (items + intrinsics)",
                f"{d.mastery_total:,}",
            ],
            (
                [f"Rank {d.test_ready} test", "Ready now"]
                if d.test_ready
                else [f"XP to rank {ms.rank + 1}", f"{d.xp_to_next:,}"]
            ),
            ["Items mastered", f"{h.items_mastered} / {h.items_total}"],
            ["Owned, below rank 30", str(h.items_leveling)],
            ["Never leveled", str(h.items_missing)],
            ["Star chart", f"{h.starchart_done} / {h.starchart_total}"],
            ["Steel Path", f"{h.steel_path_done} / {h.starchart_total}"],
            ["Syndicates at max rank", str(h.syndicates_maxed)],
            *(
                [["Standing left today", f"{extras.standing_left_total:,}"]]
                if extras.standing_left_total is not None
                else []
            ),
        ],
        right={1},
    )

    doc.add_heading("Arsenal", level=1)
    add_table(
        doc,
        ["Category", "Mastered", "Below 30", "Never leveled", "Total", "%"],
        [
            [
                c.category,
                str(c.mastered),
                str(c.leveling),
                str(c.missing),
                str(c.total),
                f"{c.percent_mastered:.0f}%",
            ]
            for c in report.categories
        ],
        right={1, 2, 3, 4, 5},
    )

    doc.add_heading("Closest to done", level=1)
    add_table(
        doc,
        ["Item", "Category", "Rank", "Affinity to 30"],
        [[o.name, o.category, str(o.rank), f"{o.xp_to_30:,}"] for o in d.closest],
        right={2, 3},
    )

    doc.add_heading("Get next", level=1)
    muted(doc, "Never leveled, within your mastery rank, obtainable now.")
    add_table(
        doc,
        ["Item", "Category", "How", "Where"],
        [[m.name, m.category, m.acquisition, best_sources(m, limit=2)] for m in d.get_next],
    )

    doc.add_heading("Star chart", level=1)
    add_table(
        doc,
        ["Planet", "Done", "Steel Path", "Nodes"],
        [[p.planet, str(p.done), str(p.steel), str(p.total)] for p in d.planets],
        right={1, 2, 3},
    )

    doc.add_heading("Syndicates", level=1)
    add_table(
        doc,
        ["Syndicate", "Rank", "Standing"],
        [[s.name, str(s.rank), f"{s.standing:,}"] for s in report.syndicates],
        right={1, 2},
    )

    if report.usage:
        doc.add_heading("Most used", level=1)
        add_table(
            doc,
            ["Item", "Kills", "Headshots", "Hours equipped"],
            [
                [u.name, f"{u.kills:,}", f"{u.headshots:,}", f"{u.equip_hours:,.1f}"]
                for u in report.usage[:15]
            ],
            right={1, 2, 3},
        )

    doc.add_heading("What this report can and cannot see", level=1)
    for n in [*report.notes, ms.note]:
        p = doc.add_paragraph(n, style="List Bullet")
        for r in p.runs:
            r.font.size = Pt(10)
    muted(doc, "Sources: " + "; ".join(f"{s.source} {s.version}" for s in report.sources))
    return doc


# -- bundle ----------------------------------------------------------------------------------


@dataclass
class DashboardFiles:
    html: Path
    pdf: Path | None = None
    docx: Path | None = None
    warnings: list[str] = field(default_factory=list)


def write_dashboard(
    report: Report,
    out_dir: Path,
    *,
    pdf: bool = True,
    docx: bool = True,
    extras: ExportExtras | None = None,
) -> DashboardFiles:
    from ..printing import try_print

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "dashboard.html"
    pdf_path = out_dir / "dashboard.pdf"
    docx_path = out_dir / "dashboard.docx"
    files = DashboardFiles(html=html_path)
    if docx:
        build_dashboard_docx(report, extras).save(docx_path)
        files.docx = docx_path
    # print a version without the toolbar link to itself, then write the final page
    html_path.write_text(
        render_dashboard_html(report, docx_name=docx_path.name if docx else None, extras=extras),
        encoding="utf-8",
    )
    if pdf:
        files.pdf, warning = try_print(html_path, pdf_path)
        if warning:
            files.warnings.append(warning)
    html_path.write_text(
        render_dashboard_html(
            report,
            pdf_name=files.pdf.name if files.pdf else None,
            docx_name=files.docx.name if files.docx else None,
            extras=extras,
        ),
        encoding="utf-8",
    )
    return files
