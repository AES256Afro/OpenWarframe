"""Print the LLM planning brief as HTML and PDF.

The brief is Markdown written for a model to read. Agents that only accept files
(PDF uploads, document tools) get the same text as a clean, selectable PDF: the
front matter becomes a metadata table, everything else keeps its structure.

Only the Markdown the brief itself uses is supported: ``#``/``##`` headings,
``-`` bullets, pipe tables and paragraphs.
"""

from __future__ import annotations

import html
from pathlib import Path

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm; }
:root { --ink:#172033; --muted:#566178; --line:#d6dce7; --gold:#8f6a17; --navy:#172033;
        --display:"Cinzel", "Trajan Pro", Georgia, serif;
        --body:"Source Sans 3", "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
        --mono:"IBM Plex Mono", ui-monospace, Consolas, "Cascadia Mono", monospace; }
* { box-sizing: border-box; }
body { margin: 0; color: var(--ink); background: #fff; font: 10.5pt/1.45 var(--body);
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
header { border-bottom: 2px solid var(--gold); padding-bottom: 8px; margin-bottom: 14px; }
header .brand { color: var(--gold); letter-spacing: .18em; font: 600 8.5pt var(--mono); }
header h1 { margin: 4px 0 0; font: 700 18pt var(--display); letter-spacing: .02em; border: 0; color: var(--ink); }
h1 { font-family: var(--display); font-size: 14pt; color: var(--navy); margin: 18px 0 6px; border-bottom: 1px solid var(--line); padding-bottom: 3px; }
h2 { font-size: 11.5pt; color: var(--gold); margin: 12px 0 4px; }
ul { margin: 4px 0 8px; padding-left: 18px; }
li { margin: 1px 0; break-inside: avoid; }
p { margin: 4px 0 8px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 9.5pt; break-inside: avoid; }
th { background: var(--navy); color: #fff; font-weight: 600; text-align: left; }
th, td { padding: 3px 6px; border: 1px solid var(--line); }
tr:nth-child(even) td { background: #f6f7fb; }
table.meta th { background: #f3f5fa; color: var(--muted); font-weight: 500; width: 22%; }
table.meta td { font-family: var(--mono); font-size: 8.5pt; word-break: break-all; }
footer { margin-top: 18px; color: var(--muted); font-size: 8pt; border-top: 1px solid var(--line); padding-top: 6px; }
"""


def _inline(text: str) -> str:
    return html.escape(text, quote=False)


def _front_matter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return {}, lines
    meta: dict[str, str] = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return meta, lines[i + 1 :]
        key, _, value = lines[i].partition(":")
        meta[key.strip()] = value.strip()
    return {}, lines


def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    body = [r for r in cells if not all(set(c) <= set("-: ") for c in r)]
    if not body:
        return ""
    head, *rest = body
    out = ["<table><thead><tr>", *(f"<th>{_inline(c)}</th>" for c in head), "</tr></thead><tbody>"]
    for r in rest:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def markdown_to_html(
    markdown: str, *, title: str = "Account planning brief", stem: str = "account-brief"
) -> str:
    meta, lines = _front_matter(markdown.splitlines())
    parts: list[str] = []
    para: list[str] = []
    bullets: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if para:
            parts.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if bullets:
            parts.append("<ul>" + "".join(f"<li>{_inline(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()
        if table:
            parts.append(_table(table))
            table.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("|"):
            if para or bullets:
                flush()
            table.append(stripped)
        elif stripped.startswith("## "):
            flush()
            parts.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            flush()
            parts.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if para or table:
                flush()
            bullets.append(stripped[2:])
        else:
            if bullets or table:
                flush()
            para.append(stripped)
    flush()

    meta_html = ""
    if meta:
        rows = "".join(f"<tr><th>{_inline(k)}</th><td>{_inline(v)}</td></tr>" for k, v in meta.items())
        meta_html = f'<table class="meta"><tbody>{rows}</tbody></table>'
    stamp = meta.get("snapshot", "")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{_inline(title)}</title><style>{CSS}</style></head><body>"
        f"<header><div class='brand'>OPENWARFRAME · PLANNING BRIEF</div><h1>{_inline(title)}</h1></header>"
        f"{meta_html}{''.join(parts)}"
        f"<footer>Generated by OpenWarframe from a snapshot taken {_inline(stamp)}. "
        f"The same content is available as {_inline(stem)}.md and {_inline(stem)}.json.</footer>"
        "</body></html>"
    )


def write_brief_documents(
    md_path: Path, *, pdf: bool = True, title: str | None = None
) -> tuple[Path, Path | None, str | None]:
    """Write ``<brief>.html`` next to the Markdown and print it to ``<brief>.pdf``.

    Returns ``(html_path, pdf_path_or_None, warning_or_None)``. A missing browser is a
    warning, not an error: the Markdown and JSON are still there.
    """
    from ..printing import try_print

    text = md_path.read_text(encoding="utf-8")
    html_path = md_path.with_suffix(".html")
    html_path.write_text(
        markdown_to_html(text, title=title or "Account planning brief", stem=md_path.stem), encoding="utf-8"
    )
    if not pdf:
        return html_path, None, None
    pdf_path, warning = try_print(html_path, md_path.with_suffix(".pdf"))
    return html_path, pdf_path, warning
