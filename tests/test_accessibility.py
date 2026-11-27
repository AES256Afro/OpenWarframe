"""Accessibility checks on the page's theme colours and static markup (docs/ACCESSIBILITY.md)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "src/openwarframe/app/static"
PAGE = (STATIC / "index.html").read_text(encoding="utf-8")


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))


def _themes() -> dict[str, dict[str, str]]:
    dark = _tokens(PAGE[PAGE.index(":root{") : PAGE.index("@media (prefers-color-scheme: light)")])
    light_block = PAGE[PAGE.index("@media (prefers-color-scheme: light)") :]
    light = {**dark, **_tokens(light_block[: light_block.index("}\n}") + 1])}
    return {"dark": dark, "light": light}


def _lum(hex_: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# text colour -> the backgrounds it is drawn on
PAIRS = {
    "fg": ["bg", "panel", "panel2", "row"],
    "muted": ["bg", "panel", "panel2", "row"],
    "gold": ["gold-soft", "panel"],
    "cyan": ["cyan-soft", "panel"],
    "ok": ["ok-soft", "panel"],
    "warn": ["warn-soft", "panel"],
    "bad": ["bad-soft", "panel"],
    "violet": ["violet-soft", "panel"],
}


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_theme_text_meets_wcag_aa(theme):
    t = _themes()[theme]
    failures = [
        f"{fg} on {bg}: {contrast(t[fg], t[bg]):.2f}"
        for fg, bgs in PAIRS.items()
        for bg in bgs
        if contrast(t[fg], t[bg]) < 4.5
    ]
    assert not failures, failures


def test_controls_have_names():
    # every static <button> has text or an aria-label; every <input> has a label or aria-label
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", PAGE, re.S):
        attrs, inner = m.groups()
        assert "aria-label" in attrs or re.sub(r"<[^>]+>", "", inner).strip(), m.group(0)[:80]
    for m in re.finditer(r"<input\b([^>]*)>", PAGE):
        attrs = m.group(1)
        if 'type="hidden"' in attrs or 'type="file"' in attrs:
            continue
        ident = re.search(r'id="([^"]+)"', attrs)
        before = PAGE[max(0, m.start() - 300) : m.start()]
        wrapped = before.rfind("<label") > before.rfind("</label>")  # <label><input> text</label>
        labelled = wrapped or "aria-label" in attrs or (ident and f'for="{ident.group(1)}"' in PAGE)
        assert labelled, m.group(0)[:80]


def test_page_has_language_live_region_and_modal_dialog():
    assert re.search(r"<html[^>]*\blang=\"en\"", PAGE)
    assert 'role="status"' in PAGE
    assert ".showModal()" in PAGE
