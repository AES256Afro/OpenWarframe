"""Render a MasteryPlan as a single self-contained HTML page (mastery-plan.html).

The design follows the hand-made "Road to Mastery 30" guide: one reading column,
Orokin gold for mastery and Tenno cyan for actions, light and dark themes. The page
works offline; the Google Fonts link only improves the type when online.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from ..report.build import rank_threshold
from .mastery import MasteryPlan

CSS = """
:root{
  --bg:#eef1f6; --panel:#ffffff; --panel2:#f6f8fb; --fg:#172033; --muted:#566178; --line:#d6dce7;
  --gold:#8f6a17; --gold-soft:#f3e7c9; --cyan:#0d7891; --cyan-soft:#d9f0f5;
  --ok:#1f8a55; --warn:#a8650c; --bad:#b4372f;
  --display:"Cinzel", "Trajan Pro", Georgia, serif;
  --body:"Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, Consolas, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0a0f1d; --panel:#121a2c; --panel2:#18223a; --fg:#e7ecf6; --muted:#9aa6bf; --line:#27334f;
    --gold:#d9b35b; --gold-soft:#3a3016; --cyan:#4fd1ea; --cyan-soft:#12313b;
    --ok:#5fd49a; --warn:#f0b35b; --bad:#f07a70; color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0a0f1d; --panel:#121a2c; --panel2:#18223a; --fg:#e7ecf6; --muted:#9aa6bf; --line:#27334f;
  --gold:#d9b35b; --gold-soft:#3a3016; --cyan:#4fd1ea; --cyan-soft:#12313b;
  --ok:#5fd49a; --warn:#f0b35b; --bad:#f07a70; color-scheme: dark;
}
*{box-sizing:border-box}
body{margin:0; background:var(--bg); color:var(--fg); font:17px/1.55 var(--body);}
.wrap{max-width:980px; margin:0 auto; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); padding-block:28px 64px; display:grid; gap:44px;}
h1,h2,h3{font-family:var(--display); text-wrap:balance; margin:0; letter-spacing:.02em}
h1{font-size:clamp(2rem, 5vw, 3.1rem); font-weight:700; line-height:1.05}
h2{font-size:1.55rem; font-weight:700}
h3{font-size:1.08rem; font-weight:700}
p{margin:0; max-width:68ch}
.eyebrow{font:600 .74rem/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; color:var(--gold)}
.muted{color:var(--muted)}
.num{font-family:var(--mono); font-variant-numeric:tabular-nums}
section{display:grid; gap:16px; min-width:0}
.lede{font-size:1.1rem}
header{display:grid; gap:14px}
.who{display:flex; flex-wrap:wrap; gap:8px 18px; font-family:var(--mono); font-size:.86rem; color:var(--muted)}
.who b{color:var(--fg); font-weight:600}
.track{background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 18px 10px; display:grid; gap:10px}
.track svg{width:100%; height:auto; display:block}
.t-lbl{font:600 13px var(--mono); fill:var(--muted)}
.t-rank{font:700 15px var(--display); fill:var(--fg)}
.t-you{font:600 13px var(--mono); fill:var(--cyan)}
.kv{display:flex; flex-wrap:wrap; gap:8px 24px; font-size:.95rem}
.kv b{font-family:var(--mono); font-variant-numeric:tabular-nums}
.tbl{overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:var(--panel)}
table{border-collapse:collapse; width:100%; font-size:.95rem}
table.wide{min-width:560px}
th,td{text-align:left; padding:9px 14px; border-bottom:1px solid var(--line); vertical-align:top}
th{font:600 .72rem var(--mono); letter-spacing:.1em; text-transform:uppercase; color:var(--muted); background:var(--panel2)}
tr:last-child td{border-bottom:0}
td.r,th.r{text-align:right}
.title-cell{font-family:var(--display); font-weight:700}
.note{background:var(--cyan-soft); border-radius:10px; padding:12px 16px; font-size:.95rem}
.check{display:grid; gap:8px}
.check label{display:grid; grid-template-columns:22px 1fr auto; gap:12px; align-items:start; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; cursor:pointer}
.check input{width:18px; height:18px; margin-top:3px; accent-color:var(--gold)}
.check .gain{font:600 .85rem var(--mono); color:var(--gold); white-space:nowrap}
.check label:has(input:checked){opacity:.6}
.check label:has(input:checked) .what{text-decoration:line-through}
.check small{display:block; color:var(--muted); font-size:.88rem; margin-top:2px}
.check input:focus-visible{outline:2px solid var(--cyan); outline-offset:2px}
.path{display:grid; gap:14px}
.phase{background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px; display:grid; gap:12px}
.phase-head{display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 14px}
.badge{font:700 .8rem var(--mono); color:var(--bg); background:var(--gold); border-radius:6px; padding:3px 8px}
.need{font:600 .85rem var(--mono); color:var(--muted)}
.test-chip{font:600 .82rem var(--mono); color:var(--cyan)}
.phase ol{margin:0; padding-left:1.2em; display:grid; gap:8px}
.phase li{max-width:74ch}
.phase li .m{font:600 .82rem var(--mono); color:var(--gold); margin-left:6px}
.branches{display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:10px}
.br{border-radius:8px; padding:10px 12px; background:var(--panel2); font-size:.92rem; min-width:0}
.br b{display:block; font:600 .7rem var(--mono); letter-spacing:.1em; text-transform:uppercase; margin-bottom:4px}
.br.tired b{color:var(--cyan)} .br.weak b{color:var(--warn)} .br.done b{color:var(--ok)}
.chips{display:flex; flex-wrap:wrap; gap:8px}
.chips button{font:600 .9rem var(--body); color:var(--fg); background:var(--panel); border:1px solid var(--line); border-radius:999px; padding:7px 14px; cursor:pointer}
.chips button[aria-pressed="true"]{background:var(--cyan); border-color:var(--cyan); color:var(--bg)}
.chips button:focus-visible{outline:2px solid var(--gold); outline-offset:2px}
.moods{display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:14px}
.mood{background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 18px; display:grid; gap:10px; align-content:start; min-width:0}
.mood dl{margin:0; display:grid; grid-template-columns:auto 1fr; gap:6px 12px; font-size:.93rem}
.mood dt{font:600 .7rem/1.9 var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--muted)}
.mood dd{margin:0; min-width:0}
.tag{font:600 .7rem var(--mono); letter-spacing:.06em; text-transform:uppercase; color:var(--gold)}
.bars{display:grid; gap:8px; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 18px}
.bar{display:grid; grid-template-columns:minmax(150px, 34%) 1fr 96px; gap:12px; align-items:center; font-size:.93rem}
.bar .b{height:12px; border-radius:6px; background:var(--panel2); overflow:hidden}
.bar .b i{display:block; height:100%; background:var(--gold); border-radius:6px}
.bar .b i.trade{background:var(--muted)}
.bar .v{text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums}
.tests{display:grid; gap:14px}
.test{background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px; display:grid; grid-template-columns:120px 1fr; gap:16px}
.test .rk{display:grid; align-content:start; gap:4px; border-right:1px solid var(--line); padding-right:14px}
.test .rk .n{font:700 2.3rem/1 var(--display); color:var(--gold)}
.test .rk .t{font:600 .78rem var(--mono); color:var(--muted)}
.test .body{display:grid; gap:10px; min-width:0}
.test ul{margin:0; padding-left:1.1em; display:grid; gap:4px}
.bring{background:var(--gold-soft); border-radius:8px; padding:9px 12px; font-size:.93rem}
.bring b{font:600 .7rem var(--mono); letter-spacing:.1em; text-transform:uppercase; color:var(--gold); margin-right:6px}
footer{font-size:.88rem; color:var(--muted); display:grid; gap:8px; border-top:1px solid var(--line); padding-top:18px}
footer a{color:var(--cyan)}
@media (max-width:720px){
  .branches,.moods{grid-template-columns:1fr}
  .test{grid-template-columns:1fr}
  .test .rk{border-right:0; border-bottom:1px solid var(--line); padding:0 0 10px; grid-auto-flow:column; justify-content:start; align-items:baseline; gap:12px}
  .bar{grid-template-columns:1fr 80px}
  .bar .b{grid-column:1 / -1; order:3}
}
"""

SCRIPT = """
(function(){
  var KEY='openwarframe-mastery-checks';
  var saved={};
  try{ saved=JSON.parse(localStorage.getItem(KEY)||'{}')||{}; }catch(e){ saved={}; }
  document.querySelectorAll('#checklist input').forEach(function(box){
    if(saved[box.id]) box.checked=true;
    box.addEventListener('change',function(){
      saved[box.id]=box.checked;
      try{ localStorage.setItem(KEY, JSON.stringify(saved)); }catch(e){}
    });
  });
  var buttons=document.querySelectorAll('.chips button');
  var cards=document.querySelectorAll('#moodgrid .mood');
  buttons.forEach(function(btn){
    btn.addEventListener('click',function(){
      var m=btn.getAttribute('data-mood');
      buttons.forEach(function(b){ b.setAttribute('aria-pressed', b===btn ? 'true':'false'); });
      cards.forEach(function(c){
        c.hidden = !(m==='all' || (' '+c.getAttribute('data-moods')+' ').indexOf(' '+m+' ')>=0);
      });
    });
  });
})();
"""


def _e(v) -> str:
    return escape(str(v), quote=True)


def _short(n: int) -> str:
    return f"{n / 1_000_000:.2f}M" if n >= 1_000_000 else f"{n / 1000:.0f}k"


def track_svg(rank: int, estimate: int, target: int = 30) -> str:
    """Rank track drawn to one scale from the current rank's threshold to the target."""
    lo, hi = rank_threshold(rank), rank_threshold(target)
    span = max(1, hi - lo)
    width, x0 = 1000, 20

    def x(v: int) -> float:
        return round(x0 + width * (min(max(v, lo), hi) - lo) / span, 1)

    parts = [
        f'<svg viewBox="0 0 1040 92" role="img" aria-label="Mastery track from rank {rank} to {target}">',
        f'<rect x="{x0}" y="40" width="{width}" height="10" rx="5" fill="var(--panel2)" stroke="var(--line)"/>',
        f'<rect x="{x0}" y="40" width="{max(0.0, x(estimate) - x0)}" height="10" rx="5" fill="var(--cyan)"/>',
    ]
    for r in range(rank, target + 1):
        px = x(rank_threshold(r))
        anchor = "end" if r == target else ("start" if r == rank else "middle")
        parts.append(f'<rect x="{px - 1}" y="34" width="2" height="22" fill="var(--gold)"/>')
        parts.append(f'<text class="t-rank" x="{px}" y="26" text-anchor="middle">{r}</text>')
        if r > rank:
            parts.append(
                f'<text class="t-lbl" x="{px}" y="74" text-anchor="{anchor}">{_short(rank_threshold(r))}</text>'
            )
    yx = x(estimate)
    parts.append(f'<polygon points="{yx},58 {yx - 6},66 {yx + 6},66" fill="var(--cyan)"/>')
    you_anchor = "start" if yx < 120 else ("end" if yx > 900 else "middle")
    parts.append(
        f'<text class="t-you" x="{yx}" y="88" text-anchor="{you_anchor}">you ≈{_short(estimate)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render_mastery_html(plan: MasteryPlan) -> str:
    who = plan.display_name.rstrip("") if plan.display_name else "Your account"
    h: list[str] = []
    a = h.append
    a('<!doctype html><html lang="en"><head><meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
    a(f"<title>Road to Mastery {plan.target_rank}</title>")
    a(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700'
        '&family=Source+Sans+3:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap">'
    )
    a(f'<style>{CSS}</style></head><body><div class="wrap">')

    # header
    a('<header><div class="eyebrow">Mastery plan · built from your profile</div>')
    a(f'<h1>Road to Mastery {plan.target_rank}</h1><div class="who">')
    a(f"<span><b>{_e(who)}</b> · {_e(plan.platform.upper())}</span>")
    a(f"<span>MR <b>{plan.rank}</b></span>")
    a(f"<span>Snapshot <b>{plan.snapshot_taken_at:%d %b %Y}</b></span></div>")
    n_tests = len(plan.tests)
    a(
        f'<p class="lede">{n_tests} rank{"s" if n_tests != 1 else ""} to go and about '
        f"{plan.needed_to_target:,} mastery. Follow the path in order, or pick by mood when you want "
        "something different. Every item named here comes from your account data.</p></header>"
    )

    # where you stand
    a('<section aria-labelledby="where"><h2 id="where">Where you stand</h2><div class="track">')
    a(track_svg(plan.rank, plan.estimate, plan.target_rank))
    nxt = plan.ranks[0] if plan.ranks else None
    a('<div class="kv">')
    a(f"<span>Estimated mastery <b>≈{plan.estimate:,}</b></span>")
    if nxt:
        a(f"<span>To MR {nxt.rank} <b>≈{nxt.to_earn:,}</b></span>")
    a(f"<span>To MR {plan.target_rank} <b>≈{plan.needed_to_target:,}</b></span></div></div>")
    a(
        '<p class="note">The estimate adds your item XP, intrinsics, star chart, junctions and Steel Path '
        "nodes, and may be off by a few thousand. Your in-game Profile shows the exact bar. When it says "
        "<b>Rank Up</b>, the test is open.</p>"
    )
    if plan.ranks:
        a(
            '<div class="tbl"><table class="wide"><thead><tr><th>Rank</th><th>Title</th>'
            '<th class="r">Total needed</th><th class="r">To earn</th><th>Test to pass</th></tr></thead><tbody>'
        )
        for r in plan.ranks:
            a(
                f'<tr><td class="num">{r.rank}</td><td class="title-cell">{_e(r.title)}</td>'
                f'<td class="r num">{r.threshold:,}</td><td class="r num">{r.to_earn:,}</td><td>{_e(r.test)}</td></tr>'
            )
        a("</tbody></table></div>")
    a("</section>")

    # tips
    a(
        '<section aria-labelledby="rules"><h2 id="rules">Rules that make it faster</h2><div class="tbl"><table><tbody>'
    )
    for t in plan.tips:
        a(f"<tr><td><b>{_e(t.title)}</b> {_e(t.text)}</td></tr>")
    a("</tbody></table></div></section>")

    # tonight
    a('<section aria-labelledby="tonight"><h2 id="tonight">Do these first, tonight</h2>')
    a('<p class="muted">Cheap mastery your account is sitting on. Ticks are saved in this browser only.</p>')
    a('<div class="check" id="checklist">')
    for t in plan.tonight:
        a(
            f'<label><input type="checkbox" id="c-{_e(t.id)}"><span><span class="what">{_e(t.title)}</span>'
            f'<small>{_e(t.detail)}</small></span><span class="gain">{_e(t.gain_label)}</span></label>'
        )
    a("</div></section>")

    # path
    a('<section aria-labelledby="path"><h2 id="path">The path, one rank at a time</h2>')
    a(
        '<p class="muted">Each phase covers one rank and takes the next sources in order, cheapest and '
        "most certain first. The three boxes say what to do if you get bored, if it is too hard, and when to "
        'take the test.</p><div class="path">'
    )
    for p in plan.phases:
        a('<article class="phase"><div class="phase-head">')
        a(f'<span class="badge">{p.from_rank} → {p.to_rank}</span><h3>{_e(p.title)}</h3>')
        need = "already there" if p.already_there else f"≈{p.need:,}"
        a(f'<span class="need">{need}</span><span class="test-chip">Test: {_e(p.test)}</span></div>')
        if p.already_there:
            a(
                "<p>Your estimate already covers this rank. Take the test as soon as the previous one unlocks.</p>"
            )
        else:
            a(f'<p class="muted">{_e(p.blurb)}</p><ol>')
            for s in p.steps:
                a(
                    f'<li><b>{_e(s.title)}</b><span class="m">+{s.mastery:,}</span><br>'
                    f"{_e(', '.join(s.items))}.</li>"
                )
            a("</ol>")
            if p.planned < p.need:
                a(
                    f'<p class="note">The sources this plan knows about add {p.planned:,} of the {p.need:,} '
                    "this rank needs. Trade or event items can cover the rest.</p>"
                )
        a('<div class="branches">')
        a(f'<div class="br tired"><b>If you get tired</b>{_e(p.tired)}</div>')
        a(f'<div class="br weak"><b>If it is too hard</b>{_e(p.too_hard)}</div>')
        a(f'<div class="br done"><b>When you are there</b>{_e(p.done)}</div></div></article>')
    a("</div></section>")

    # moods
    a('<section aria-labelledby="moods"><h2 id="moods">Pick by mood</h2>')
    a('<p class="muted">Every option earns affinity or mastery. Choose a mood to filter.</p>')
    a('<div class="chips" role="group" aria-label="Filter by mood">')
    a('<button type="button" data-mood="all" aria-pressed="true">All</button>')
    for key, label in plan.moods.items():
        a(f'<button type="button" data-mood="{_e(key)}" aria-pressed="false">{_e(label)}</button>')
    a('</div><div class="moods" id="moodgrid">')
    for c in plan.mood_cards:
        a(f'<article class="mood" data-moods="{_e(" ".join(c.moods))}">')
        a(f'<span class="tag">{_e(" · ".join(c.mood_labels))}</span><h3>{_e(c.name)}</h3><dl>')
        a(f"<dt>Where</dt><dd>{_e(c.where)}</dd><dt>Levels</dt><dd>{_e(c.levels)}</dd>")
        a(f"<dt>Too hard</dt><dd>{_e(c.too_hard)}</dd><dt>Bored</dt><dd>{_e(c.tired)}</dd></dl></article>")
    a("</div></section>")

    # budget
    a(
        f'<section aria-labelledby="budget"><h2 id="budget">Where {plan.needed_to_target:,} mastery comes from</h2>'
    )
    a(
        f'<p class="muted">Mastery your account can still earn, by source. You need about '
        f"{plan.needed_to_target:,}. Everything except trading adds up to about {plan.budget_without_trade:,}.</p>"
    )
    a('<div class="bars" role="list">')
    top = max((b.mastery for b in plan.budget), default=1)
    for b in plan.budget:
        width = round(100 * b.mastery / top, 1)
        cls = ' class="trade"' if b.trade else ""
        a(
            f'<div class="bar" role="listitem"><span>{_e(b.label)} ({b.count})</span>'
            f'<span class="b"><i{cls} style="width:{width}%"></i></span><span class="v">{b.mastery:,}</span></div>'
        )
    a("</div></section>")

    # tests
    if plan.tests:
        a('<section aria-labelledby="tests"><h2 id="tests">The tests</h2>')
        a(f'<p class="muted">{_e(" ".join(plan.test_rules))}</p><div class="tests">')
        for t in plan.tests:
            a(
                f'<article class="test"><div class="rk"><span class="n">{t.rank}</span><span class="t">{_e(t.title)}</span></div>'
            )
            a(f'<div class="body"><h3>{_e(t.name)}</h3><p>{_e(t.objective)}</p><ul>')
            for tip in t.tips:
                a(f"<li>{_e(tip)}</li>")
            a(f'</ul><div class="bring"><b>Bring</b>{_e(t.bring)}</div></div></article>')
        a("</div></section>")

    # footer
    parts = plan.estimate_parts
    a("<footer>")
    a(
        f"<p>Built by OpenWarframe on {plan.generated_at:%d %b %Y} from the snapshot taken "
        f"{plan.snapshot_taken_at:%d %b %Y %H:%M} UTC. Sources: "
        + ", ".join(f'<a href="{_e(s["url"])}">{_e(s["title"])}</a>' for s in plan.sources)
        + ".</p>"
    )
    a(
        "<p>Estimate: "
        + ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in parts.items())
        + f". Total ≈{plan.estimate:,}.</p>"
    )
    for n in plan.notes:
        a(f"<p>{_e(n)}</p>")
    a("</footer></div>")
    a(f"<script>{SCRIPT}</script></body></html>")
    return "".join(h)


def write_mastery_html(plan: MasteryPlan, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_mastery_html(plan), encoding="utf-8")
    return path
