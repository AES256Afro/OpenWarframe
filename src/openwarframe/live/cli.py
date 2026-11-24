"""``openwarframe live``: follow the game log and read relic rewards off the screen."""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="Relic reward helper: follow EE.log, read the reward screen (log and screen only).",
    no_args_is_help=True,
)
console = Console()

LOG_OPT = typer.Option(None, "--log", help="EE.log to follow (default: the game's own EE.log).")


def _settings():
    from ..config import load_settings

    return load_settings()


def _catalog(s):
    from ..codex import Codex
    from .match import RewardCatalog

    if not s.codex_path.exists():
        console.print("[red]No codex yet; run `openwarframe codex update` first.[/red]")
        raise typer.Exit(code=1)
    return RewardCatalog.from_codex(Codex(s.codex_path).conn)


def _prices(path: Path | None) -> dict | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _need_ocr() -> None:
    from .ocr import ocr_available

    if not ocr_available():
        console.print(
            "[red]System OCR is not available (needs Windows 10/11 with the winrt packages, or macOS with pyobjc).[/red]"
        )
        raise typer.Exit(code=1)


def _print_analysis(a) -> None:
    t = Table(title=f"Rewards ({a.players} shown, UI scale {a.ui_scale:g})")
    t.add_column("#", justify="right")
    t.add_column("Reward")
    t.add_column("OCR read", style="dim")
    t.add_column("Match", justify="right")
    t.add_column("Why")
    for i, r in enumerate(a.ranked, 1):
        e = r.match.entry
        t.add_row(
            str(i),
            f"[bold]{e.name}[/bold]" if e and i == 1 else (e.name if e else "?"),
            r.match.raw or "-",
            f"{r.match.score:.2f}",
            r.reason,
        )
    console.print(t)


@app.command("watch")
def watch_cmd(
    log: Path | None = LOG_OPT,
    from_start: bool = typer.Option(False, "--from-start", help="Replay the whole log first."),
    as_json: bool = typer.Option(False, "--json", help="One JSON object per event."),
) -> None:
    """Print game events as they happen (mission loads, reward screen, login). Ctrl+C stops."""
    from .eelog import default_log_path, watch

    path = log or default_log_path()
    if not as_json:
        console.print(f"Following {path}  (Ctrl+C to stop)")
    try:
        for ev in watch(path, from_start=from_start):
            if as_json:
                d = {
                    "kind": ev.kind,
                    "time": ev.time,
                    **{k: v for k, v in ev.data.items() if k != "mission_info"},
                }
                print(json.dumps(d), flush=True)
            else:
                console.print(ev.describe(), highlight=False)
    except KeyboardInterrupt:
        pass


def _grab_and_save(s, catalog, needs, prices, *, event=None, log_tail=None, ui_scale=None, language=None):
    from . import ocr
    from .reward import analyze, save_recording

    win = ocr.find_game_window()
    if win is None:
        console.print("[yellow]Warframe window not found; nothing captured.[/yellow]")
        return None
    image = ocr.capture(win)
    scale = ui_scale or ocr.read_ui_scale()
    analysis, error = None, None
    try:
        analysis = analyze(image, catalog, ui_scale=scale, language=language, needs=needs, prices=prices)
    except Exception as exc:  # keep the screenshot even when OCR fails
        error = f"{type(exc).__name__}: {exc}"
    d = save_recording(s.home, image, analysis, event=event, log_tail=log_tail, error=error)
    if analysis:
        _print_analysis(analysis)
    else:
        console.print(f"[red]OCR failed: {error}[/red]")
    console.print(f"Saved to {d}")
    return d


@app.command("record")
def record_cmd(
    log: Path | None = LOG_OPT,
    delay: float = typer.Option(
        1.5, "--delay", help="Seconds to wait after the trigger before the screenshot."
    ),
    ui_scale: float | None = typer.Option(
        None, "--ui-scale", help="Override the UI scale (default: EE.cfg or 1)."
    ),
    language: str | None = typer.Option(None, "--lang", help="OCR language tag, e.g. en-US."),
    prices: Path | None = typer.Option(None, "--prices", help="JSON file: name/slug -> platinum."),
) -> None:
    """On every reward screen, save the screenshot, OCR output and recent log lines for tuning.

    Also appends every reward/relic/fissure-looking log line to live/candidates.log, so a
    real fissure run shows which lines the game actually writes.
    """
    from .eelog import CANDIDATE_RE, default_log_path, watch
    from .match import account_needs

    _need_ocr()
    s = _settings()
    catalog = _catalog(s)
    needs = account_needs(s)
    price_map = _prices(prices)
    path = log or default_log_path()
    (s.home / "live").mkdir(parents=True, exist_ok=True)
    cand = (s.home / "live" / "candidates.log").open("a", encoding="utf-8")
    tail: deque[str] = deque(maxlen=300)

    def on_line(ln: str) -> None:
        tail.append(ln)
        if CANDIDATE_RE.search(ln):
            cand.write(ln + "\n")
            cand.flush()

    console.print(f"Recording reward screens from {path} into {s.home / 'live'}  (Ctrl+C to stop)")
    try:
        reported: list[str] = []  # reward item paths the log names for this screen
        for ev in watch(path, on_line=on_line):
            console.print(ev.describe(), highlight=False)
            if ev.kind == "reward_reported":
                reported.append(ev.data["item"])
            elif ev.kind in ("reward_screen_closed", "mission_loaded"):
                reported = []
            if ev.kind == "reward_screen_opened":
                time.sleep(delay)
                _grab_and_save(
                    s,
                    catalog,
                    needs,
                    price_map,
                    event={"kind": ev.kind, "time": ev.time, "line": ev.line, "reported": reported},
                    log_tail=list(tail),
                    ui_scale=ui_scale,
                    language=language,
                )
    except KeyboardInterrupt:
        pass
    finally:
        cand.close()


@app.command("capture")
def capture_cmd(
    delay: float = typer.Option(3.0, "--delay", help="Seconds to wait first (switch to the game)."),
    ui_scale: float | None = typer.Option(None, "--ui-scale"),
    language: str | None = typer.Option(None, "--lang"),
) -> None:
    """Screenshot the game now and save it with OCR output (manual fallback for `record`)."""
    from .match import account_needs

    _need_ocr()
    s = _settings()
    catalog = _catalog(s)
    time.sleep(delay)
    if (
        _grab_and_save(
            s, catalog, account_needs(s), None, event={"kind": "manual"}, ui_scale=ui_scale, language=language
        )
        is None
    ):
        raise typer.Exit(code=1)


@app.command("ocr")
def ocr_cmd(
    image: Path = typer.Argument(..., exists=True, dir_okay=False, help="A saved screenshot of the game."),
    players: int | None = typer.Option(
        None, "--players", "-n", min=1, max=4, help="Rewards shown (default: detect)."
    ),
    ui_scale: float = typer.Option(1.0, "--ui-scale"),
    language: str | None = typer.Option(None, "--lang"),
    prices: Path | None = typer.Option(None, "--prices", help="JSON file: name/slug -> platinum."),
    as_json: bool = typer.Option(False, "--json"),
    crops: Path | None = typer.Option(None, "--save-crops", help="Write the cropped name boxes here."),
) -> None:
    """Crop, OCR and match the reward names in a saved screenshot."""
    from PIL import Image

    from . import ocr
    from .match import account_needs
    from .reward import analyze

    _need_ocr()
    s = _settings()
    catalog = _catalog(s)
    img = Image.open(image).convert("RGB")
    a = analyze(
        img,
        catalog,
        players=players,
        ui_scale=ui_scale,
        language=language,
        needs=account_needs(s),
        prices=_prices(prices),
    )
    if crops:
        crops.mkdir(parents=True, exist_ok=True)
        for i, b in enumerate(ocr.slot_boxes(img.width, img.height, a.players, ui_scale)):
            ocr.prepare(img.crop(b.as_tuple())).save(crops / f"slot{i + 1}.png")
    if as_json:
        print(json.dumps(a.to_dict(), indent=2))
    else:
        _print_analysis(a)


@app.command("sample-image")
def sample_image_cmd(
    out: Path = typer.Argument(..., help="PNG to write."),
    names: str = typer.Option(
        "Saryn Prime Chassis Blueprint;Forma Blueprint;Burston Prime Barrel;Lex Prime Receiver",
        "--names",
        help="1 to 4 reward names separated by ';'.",
    ),
    size: str = typer.Option("1920x1080", "--size", help="WIDTHxHEIGHT."),
    ui_scale: float = typer.Option(1.0, "--ui-scale"),
) -> None:
    """Draw a synthetic reward screen to test `live ocr` without the game."""
    from .synthetic import reward_screen

    w, h = (int(x) for x in size.lower().split("x"))
    parts = [n.strip() for n in names.split(";") if n.strip()]
    if not 1 <= len(parts) <= 4:
        raise typer.BadParameter("give 1 to 4 names")
    reward_screen(parts, (w, h), ui_scale).save(out)
    console.print(f"Wrote {out}")
