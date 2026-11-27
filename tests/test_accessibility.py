"""Milestone 6: accessibility and platform-aware text. No network, no browser."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest

from openwarframe.app.data import build_app_data
from openwarframe.app.server import AppState, page_source
from openwarframe.codex import Codex
from openwarframe.config import Settings
from test_app import server  # noqa: F401
from test_codex_build import codex_path  # noqa: F401
from test_guide import _report

STATIC = Path(__file__).parents[1] / "src/openwarframe/app/static"
PAGE = page_source()
MINI = (STATIC / "mini.html").read_text(encoding="utf-8")


# -- what this computer and account can do ------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "supported", "game_here", "grab"),
    [
        ("pc", True, True, True),
        ("pc", False, True, False),
        ("ps4", True, False, False),
        ("swi", False, False, False),
    ],
)
def test_capabilities_follow_the_os_and_the_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    supported: bool,
    game_here: bool,
    grab: bool,
):
    from openwarframe.live import ocr
    from openwarframe.sources.account import session

    monkeypatch.setattr(session, "SUPPORTED", supported)
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    caps = AppState(Settings(home=tmp_path, platform=platform)).capabilities()
    assert caps["game_here"] is game_here and caps["grab"] is grab
    assert caps["ocr"] is game_here  # a console account has no game window here to read
    assert caps["platform_label"] in ("PC", "PlayStation", "Nintendo Switch")


def test_the_setup_screen_is_told_what_works_here(server):  # noqa: F811
    base, state = server
    state.cache = {"error": "Connect your Warframe account to get started.", "setup": True}
    state.cache_fp = state._fingerprint()
    data = json.loads(urllib.request.urlopen(base + "/api/data").read())
    assert data["setup"] and set(data["caps"]) >= {"game_here", "grab", "ocr", "platform_label"}


def test_steel_path_counts_as_unlocked_only_once_reached(codex_path: Path):  # noqa: F811
    r = _report()  # 266 of 269 nodes, 102 Steel Path nodes done
    assert build_app_data(r, Codex(codex_path), None)["meta"]["steel_path_unlocked"] is True
    r.headline.steel_path_done = 0
    assert build_app_data(r, Codex(codex_path), None)["meta"]["steel_path_unlocked"] is False
    r.headline.starchart_done = r.headline.starchart_total
    assert build_app_data(r, Codex(codex_path), None)["meta"]["steel_path_unlocked"] is True


# -- contrast (WCAG AA, 4.5:1 for normal text) -------------------------------------------------


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def _ratio(a: str, b: str) -> float:
    def lum(h: str) -> float:
        rgb = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


DARK = _tokens(PAGE[PAGE.index(":root{") : PAGE.index("@media (prefers-color-scheme: light)")])
LIGHT = {
    **DARK,
    **_tokens(PAGE[PAGE.index("@media (prefers-color-scheme: light)") : PAGE.index("*{box-sizing")]),
}
PAIRS = [  # (text, background) as the page draws them
    ("ok", "ok-soft"),
    ("warn", "warn-soft"),
    ("bad", "bad-soft"),
    ("violet", "violet-soft"),
    ("gold", "gold-soft"),  # mastered pill
    ("cyan", "cyan-soft"),  # leveling pill, selected tab
    ("on-accent", "gold"),  # primary button
    ("on-accent", "cyan"),  # pressed chip and segment
    ("muted", "panel"),
    ("muted", "bg"),
    ("fg", "panel"),
]


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize(("fg", "bg"), PAIRS)
def test_text_meets_wcag_aa_contrast(theme: str, fg: str, bg: str):
    t = DARK if theme == "dark" else LIGHT
    assert _ratio(t[fg], t[bg]) >= 4.5, f"{theme}: --{fg} on --{bg}"


def test_text_can_grow_to_200_percent():
    assert '[2,"200%"]' in PAGE


# -- keyboard and screen readers ----------------------------------------------------------------


def test_rows_tabs_and_dialogs_work_without_a_mouse():
    assert 'tabindex="0" aria-expanded="' in PAGE  # table rows
    assert "function onTableKey" in PAGE and 'e.key==="Enter"' in PAGE  # one delegated handler
    assert "ArrowDown" in PAGE and 'aria-orientation","vertical' in PAGE  # the view list
    assert '<dialog id="consent"' in PAGE and "showModal()" in PAGE
    assert "function keepFocus" in PAGE and "keepFocus(renderAllNow)" in PAGE  # every redraw keeps focus


def test_feedback_is_announced():
    assert 'id="toast" role="status" aria-live="polite"' in PAGE
    assert 'role="status" aria-live="polite"' in MINI


def test_the_page_no_longer_guesses_the_platform_for_inventory_text():
    # every inventory hint goes through invHint(), which asks the server what works here
    assert "With Warframe running, click Get inventory from game." not in PAGE
    assert PAGE.count("invHint(") >= 5
    assert "Rewards tab" not in MINI


def test_every_control_has_a_name():
    # every <button> has text or an aria-label; every <input> has a label (around it or by id)
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
