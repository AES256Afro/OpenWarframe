"""OpenWarframe command line."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape as _e
from rich.table import Table
from rich.tree import Tree

from . import __version__
from .config import load_settings
from .fsutil import atomic_write_text

app = typer.Typer(help="Export, explain and plan your Warframe account.", no_args_is_help=True)
codex_app = typer.Typer(
    help="The local game database (items, recipes, drops, vendors).", no_args_is_help=True
)
account_app = typer.Typer(help="Which account to snapshot.", no_args_is_help=True)
app.add_typer(codex_app, name="codex")
app.add_typer(account_app, name="account")
inventory_app = typer.Typer(help="Load your full inventory from a JSON file.", no_args_is_help=True)
app.add_typer(inventory_app, name="inventory")
guide_app = typer.Typer(help="Guides built from your snapshot and the knowledge base.", no_args_is_help=True)
app.add_typer(guide_app, name="guide")
app.add_typer(__import__("openwarframe.live.cli", fromlist=["app"]).app, name="live")
console = Console()


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log what is being fetched."),
    home: Path | None = typer.Option(
        None, "--home", help="Data directory (default: OPENWARFRAME_HOME or the OS app-data dir)."
    ),
) -> None:
    if home:
        os.environ["OPENWARFRAME_HOME"] = str(home)
    from .config import default_home
    from .logs import setup_logging

    # console as before (-v for details); everything also goes to <data folder>/logs, with
    # the game session key masked in both
    setup_logging(default_home(), console_level=logging.INFO if verbose else logging.WARNING)


@app.command()
def version() -> None:
    """Print the version and data directory."""
    s = load_settings()
    console.print(f"openwarframe {__version__} · data in {s.home}")


@app.command()
def backup(
    out: Path | None = typer.Option(
        None, "--out", help="Zip file to write (default: <data folder>/backups/)."
    ),
) -> None:
    """Save your goals, settings, profile history and inventory to one zip file.

    To restore, close OpenWarframe and unzip it into the data folder shown by
    `openwarframe version`. Downloaded game data, caches and logs are left out: they come back
    on their own.
    """
    import zipfile
    from datetime import datetime

    s = load_settings()
    skip_dirs = {"cache", "logs", "webview", "app-window", "exports", "backups"}
    skip_files = {"codex.sqlite", "app.lock"}
    target = out or s.home / "backups" / f"openwarframe-backup-{datetime.now():%Y-%m-%d_%H%M}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(s.home.rglob("*")):
            rel = p.relative_to(s.home)
            if (
                not p.is_file()
                or rel.parts[0] in skip_dirs
                or "recordings" in rel.parts
                or p.name in skip_files
            ):
                continue
            if p.resolve() == target.resolve() or p.suffix == ".tmp":
                continue
            zf.write(p, rel.as_posix())
            count += 1
    console.print(f"Backed up {count} files to {target}", markup=False)


@app.command(hidden=True)
def selfcheck() -> None:
    """Check that the files bundled with the app are present (used by the build smoke test)."""
    from importlib import resources

    from .guide.kb import load_kb

    problems: list[str] = []
    try:
        kb = load_kb()
        console.print(
            f"knowledge base: {kb.path} ({len(kb.tests.get('tests', []))} rank tests)", markup=False
        )
        for f in kb.stale():
            console.print(f"knowledge base file not checked recently: {f}", markup=False, style="yellow")
    except Exception as exc:  # noqa: BLE001 - report every problem, not just the first
        problems.append(f"knowledge base: {exc}")
    static = resources.files("openwarframe.app").joinpath("static")
    for name in ("index.html", "mini.html", "icon.ico"):
        if not static.joinpath(name).is_file():
            problems.append(f"missing app file: static/{name}")
    try:  # the page is assembled from static/page/: every part must be bundled
        from .app.server import INCLUDE_RE, page_source

        if INCLUDE_RE.search(page_source()):
            problems.append("app page: a part was not filled in")
    except OSError as exc:
        problems.append(f"app page: {exc}")
    if problems:
        for p in problems:
            console.print(p, markup=False, style="red")
        raise typer.Exit(code=1)
    console.print("bundled files: ok")


def _names_translator(s, codex, lang: str | None):
    """Item names for exports: --names, else the app's Item names setting; downloads once."""
    from .codex.languages import LANGUAGES, load_names
    from .codex.translate import Translator
    from .http import CachedClient

    if lang is None:
        try:
            prefs = json.loads((s.home / "app-prefs.json").read_text(encoding="utf-8"))
            lang = str(prefs.get("settings", {}).get("names_lang") or "en")
        except (OSError, ValueError, AttributeError):
            lang = "en"
    if lang not in LANGUAGES:
        raise typer.BadParameter(f"unknown language {lang!r}; choose from {', '.join(LANGUAGES)}")
    if lang == "en":
        return None
    client = CachedClient(s.cache_dir)
    try:
        table = load_names(s.home, lang, client)
    finally:
        client.close()
    if not table:
        console.print(f"Could not get {LANGUAGES[lang][0]} item names; exporting in English.", style="yellow")
        return None
    return Translator.from_codex(codex.conn, lang, dict(table))


def _export_folder(s, snap, share: bool) -> Path:
    from .exports.extras import export_folder

    return export_folder(s, snap, share)


def _remember_latest(s, folder: Path) -> Path:
    """exports/LATEST.txt names the newest export folder (a link would not work everywhere)."""
    pointer = s.exports_dir / "LATEST.txt"
    atomic_write_text(pointer, str(folder.resolve()) + "\n")
    return pointer


def _open_in_browser(path: Path) -> None:
    """Open a file or folder the way `guide mastery --open` does."""
    import webbrowser

    webbrowser.open(path.resolve().as_uri())


def _export_extras(s, store, snapshot: str, parsed, codex):
    from .exports.extras import gather_extras

    return gather_extras(s, store, parsed, codex, compare=snapshot == "latest")


@app.command()
def export(
    formats: str = typer.Option(
        "json,sqlite,csv,xlsx,llm,dashboard,guide",
        "--format",
        "-f",
        help="Comma-separated: json, sqlite, csv, xlsx, llm, dashboard, guide.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Output folder (default: data dir/exports/<date>/full, or /share with --share).",
    ),
    snapshot: str = typer.Option(
        "latest", "--snapshot", help="Snapshot file, prefix, 'latest' or 'previous'."
    ),
    share: bool = typer.Option(False, "--share", help="Strip display name, clan and raw payloads."),
    budget: str | None = typer.Option(
        None, "--budget", help="LLM brief size: compact (~8k tokens, the default) or full."
    ),
    pdf: bool | None = typer.Option(
        None,
        "--pdf/--no-pdf",
        help="Also print PDFs of the guide, brief and dashboard (needs Chrome, Edge, Chromium or Brave). On by default.",
    ),
    copy_to: str | None = typer.Option(
        None, "--copy-to", help="Copy the guide files to cloud sync folders: onedrive, gdrive or both."
    ),
    open_: bool = typer.Option(False, "--open", help="Open the export folder when done."),
    remember: bool = typer.Option(
        False, "--remember", help="Save --budget, --pdf/--no-pdf and --copy-to as your defaults."
    ),
    names: str | None = typer.Option(
        None,
        "--names",
        help="Item names in this language: en, de, es, fr, it, ja, ko, pl, pt, ru, th, tr, uk, zh, tc "
        "(default: the app's Item names setting, else English).",
    ),
) -> None:
    """Export a snapshot to JSON, SQLite, CSV, Excel, an LLM brief, a dashboard and the mastery guide."""
    from .account.store import SnapshotStore
    from .account.sync import reparse
    from .codex import Codex
    from .config import save_settings
    from .exports import FORMATS, run_exports
    from .report import build_report

    s = load_settings()
    saved = s.export_prefs
    if budget is not None and budget not in ("compact", "full"):
        raise typer.BadParameter("budget must be compact or full")
    if copy_to is not None:
        _cloud_targets(copy_to)  # a bad name stops here, before it is saved
    if remember:
        given = {"budget": budget, "pdf": pdf, "copy_to": copy_to}
        s.remember_export(**{k: v for k, v in given.items() if v is not None})
        save_settings(s)
    budget = budget if budget is not None else saved.get("budget", "compact")
    pdf = pdf if pdf is not None else saved.get("pdf", True)
    copy_to = copy_to if copy_to is not None else saved.get("copy_to")
    if not s.codex_path.exists():
        console.print("[red]No codex yet; run `openwarframe codex update` first.[/red]")
        raise typer.Exit(code=1)
    store = SnapshotStore(s.snapshots_dir)
    try:
        snap = store.load(snapshot)
    except FileNotFoundError:
        console.print("[red]No snapshot yet; run `openwarframe sync` first.[/red]")
        raise typer.Exit(code=1) from None
    wanted = [f.strip().lower() for f in formats.split(",") if f.strip()]
    bad = [f for f in wanted if f not in FORMATS]
    if bad:
        raise typer.BadParameter(f"unknown format(s) {bad}; choose from {', '.join(FORMATS)}")
    if budget not in ("compact", "full"):
        raise typer.BadParameter("budget must be compact or full")
    targets = _cloud_targets(copy_to)
    with Codex(s.codex_path) as codex, console.status("Building report..."):
        parsed = reparse(snap, codex)
        report = build_report(parsed, codex, anonymize=share, inventory=_saved_inventory(s))
        extras = _export_extras(s, store, snapshot, parsed, codex)
        tr = _names_translator(s, codex, names)
    target = out or _export_folder(s, snap, share)
    with console.status("Writing exports..."):
        results = run_exports(
            report,
            target,
            wanted,
            brief_budget=budget,
            guide_pdf=pdf,
            copy_to=targets,
            share=share,
            extras=extras,
            translator=tr,
        )
    t = Table(title=f"exports -> {_e(str(target))}", show_edge=False)
    t.add_column("format")
    t.add_column("file")
    t.add_column("detail")
    t.add_column("size", justify="right")
    for r in results:
        t.add_row(
            _e(r.format),
            _e(r.path.name + ("/" if r.path.is_dir() else "")),
            _e(r.detail),
            f"{r.size / 1024:,.0f} KB",
        )
    console.print(t)
    if share:
        console.print("[yellow]share mode: display name, clan and raw payloads removed[/yellow]")
    if remember:
        console.print(f"Saved your export choices to {s.config_path}", markup=False)
    pointer = _remember_latest(s, target)
    console.print(f"Export folder: {target.resolve()}", markup=False)
    console.print(f"(its path is also in {pointer})", markup=False, style="dim")
    if open_:
        _open_in_browser(target)


@app.command(hidden=True)
def schema(
    out: Path = typer.Option(
        ..., "--out", help="Where to write the schema, e.g. docs/schema/account.schema.json."
    ),
) -> None:
    """Write the JSON Schema for account.json (for developers)."""
    from .exports.data import write_schema

    out.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"wrote {write_schema(out)}", markup=False)


# -- desktop app -------------------------------------------------------------------------


SHORTCUT_PS = r"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}')
$s.TargetPath = '{target}'
$s.WorkingDirectory = '{cwd}'
$s.Description = 'OpenWarframe'
$s.IconLocation = '{icon},0'
$s.Save()
"""


def _ps_quote(value: str) -> str:
    """Text for inside a single-quoted PowerShell string: a quote is written twice."""
    return str(value).replace("'", "''")


def shortcut_script(lnk: Path | str, target: str, cwd: Path | str, icon: Path | str) -> str:
    return SHORTCUT_PS.format(
        lnk=_ps_quote(lnk), target=_ps_quote(target), cwd=_ps_quote(cwd), icon=_ps_quote(icon)
    )


@app.command()
def gui(
    port: int = typer.Option(0, "--port", help="Port to listen on (default: any free port)."),
    no_window: bool = typer.Option(
        False, "--no-window", help="Only start the server; open the URL yourself."
    ),
    shortcut: bool = typer.Option(
        False, "--shortcut", help="Put an OpenWarframe shortcut on your desktop and exit."
    ),
) -> None:
    """Open the OpenWarframe app window: frames, weapons, relics and blueprints you can sort and filter."""
    if shortcut:
        import shutil
        import subprocess
        import sys

        if sys.platform != "win32":
            console.print(
                "Desktop shortcuts are made on Windows only. On this computer, start the app with: "
                "openwarframe gui",
                markup=False,
            )
            return

        target = shutil.which("openwarframe-app") or shutil.which("openwarframe")
        if not target:
            console.print("[red]Install the command first: uv tool install --editable .[/red]")
            raise typer.Exit(code=1)
        desktop = Path.home() / "Desktop"
        onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
        if not desktop.exists() and onedrive_desktop.exists():
            desktop = onedrive_desktop
        lnk = desktop / "OpenWarframe.lnk"
        from importlib import resources

        icon = resources.files("openwarframe.app").joinpath("static/icon.ico")
        script = shortcut_script(lnk, target, Path.home(), icon)
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)  # noqa: S603, S607
        console.print(f"[green]Shortcut created:[/green] {_e(str(lnk))}")
        return
    from .app import run_app

    run_app(port=port, open_window=not no_window)


@inventory_app.command("import")
def inventory_import(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Inventory JSON file."),
) -> None:
    """Copy an inventory JSON file into OpenWarframe so the app can show relics and blueprints."""
    import json

    from .inventory import load_inventory

    s = load_settings()
    try:
        inv = load_inventory(path)
    except (ValueError, json.JSONDecodeError) as exc:
        console.print(f"[red]Could not read {path}: {exc}[/red]")
        raise typer.Exit(code=1) from None
    from .inventory import unwrap

    data = unwrap(json.loads(path.read_text(encoding="utf-8-sig")))
    atomic_write_text(s.inventory_path, json.dumps(data))
    console.print(
        f"[green]Inventory loaded:[/green] {len(inv.equipment)} built items, {len(inv.recipes)} blueprints, "
        f"{sum(sum(v.values()) for v in inv.relics.values())} relics"
    )


@inventory_app.command("grab")
def inventory_grab(
    yes: bool = typer.Option(
        False, "--yes", help="Kept for scripts. The first run always asks; later runs never do."
    ),
) -> None:
    """Read the running game's session (read-only) and download your full inventory."""
    import json

    from .config import save_settings
    from .inventory import parse_inventory
    from .sources.account.session import RISK_TEXT, SUPPORTED, UNSUPPORTED_TEXT, SessionError, grab_inventory

    if not SUPPORTED:  # say so before asking for consent to something that can't run here
        console.print(UNSUPPORTED_TEXT, markup=False, style="yellow")
        raise typer.Exit(code=1)
    s = load_settings()
    if not s.extra.get("session_reader_ok"):
        # --yes never answers this first question: consent has to come from the player
        console.print(f"[yellow]{RISK_TEXT}[/yellow]", markup=False)
        if not typer.confirm("Continue?", default=False):
            raise typer.Exit(code=1)
        s.extra["session_reader_ok"] = True
        save_settings(s)
    try:
        with console.status("Reading the game session and downloading your inventory..."):
            data = grab_inventory(s.account_id)
    except SessionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    inv = parse_inventory(data, source="game session")
    atomic_write_text(s.inventory_path, json.dumps(data))
    console.print(
        f"[green]Inventory downloaded:[/green] {len(inv.equipment)} built items, {len(inv.recipes)} blueprints, "
        f"{sum(sum(v.values()) for v in inv.relics.values())} relics"
    )


@inventory_app.command("forget-consent")
def inventory_forget_consent() -> None:
    """Take back permission to read the game session. The next grab asks again."""
    from .config import save_settings

    s = load_settings()
    if s.extra.pop("session_reader_ok", None) is None:
        console.print("No permission was stored.")
        return
    save_settings(s)
    console.print("Permission removed. OpenWarframe will ask again before reading the game session.")


@inventory_app.command("clear")
def inventory_clear() -> None:
    """Forget the loaded inventory file."""
    p = load_settings().inventory_path
    if p.exists():
        p.unlink()
    console.print("Inventory cleared.")


# -- guides ------------------------------------------------------------------------------


def _cloud_targets(spec: str | None) -> list[str]:
    from .guide.documents import parse_targets

    try:
        return parse_targets(spec)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _load_report(snapshot: str, share: bool = False):
    from .account.store import SnapshotStore
    from .account.sync import reparse
    from .codex import Codex
    from .report import build_report

    s = load_settings()
    if not s.codex_path.exists():
        console.print("[red]No codex yet; run `openwarframe codex update` first.[/red]")
        raise typer.Exit(code=1)
    try:
        snap = SnapshotStore(s.snapshots_dir).load(snapshot)
    except FileNotFoundError:
        console.print("[red]No snapshot yet; run `openwarframe sync` first.[/red]")
        raise typer.Exit(code=1) from None
    with Codex(s.codex_path) as codex:
        return (
            s,
            snap,
            build_report(reparse(snap, codex), codex, anonymize=share, inventory=_saved_inventory(s)),
        )


def _saved_inventory(s):
    """The inventory the app or `inventory grab/import` saved, or None (with a warning if unreadable)."""
    from .inventory import load_inventory

    path = s.inventory_path
    if not path.exists():
        return None
    try:
        return load_inventory(path)
    except (OSError, ValueError) as exc:
        console.print(f"Your saved inventory could not be read ({exc}); exporting without it.", markup=False)
        return None


@guide_app.command("mastery")
def guide_mastery(
    snapshot: str = typer.Option(
        "latest", "--snapshot", help="Snapshot file, prefix, 'latest' or 'previous'."
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Folder for mastery-plan.html (default: data dir/exports/<date>/full, or /share with --share).",
    ),
    html: bool = typer.Option(True, "--html/--no-html", help="Write the guide files (HTML, Word, PDF)."),
    pdf: bool = typer.Option(
        True, "--pdf/--no-pdf", help="Also print a PDF (needs Chrome, Edge, Chromium or Brave)."
    ),
    docx: bool = typer.Option(True, "--docx/--no-docx", help="Also write a Word document."),
    copy_to: str | None = typer.Option(
        None, "--copy-to", help="Copy the files to cloud sync folders: onedrive, gdrive or both."
    ),
    open_: bool = typer.Option(False, "--open", help="Open the HTML guide in your browser when done."),
    share: bool = typer.Option(False, "--share", help="Strip display name and clan."),
    show_plan: bool = typer.Option(
        False,
        "--show-plan",
        help="Also print the whole plan here: ranks, tonight's list, every step and test.",
    ),
) -> None:
    """Your road to Mastery Rank 30: rank table, tonight's checklist, phased plan and test cards."""
    from .guide import build_mastery_plan, load_kb, write_guide_bundle

    targets = _cloud_targets(copy_to)

    s, snap, report = _load_report(snapshot, share)
    kb = load_kb()
    for f in kb.stale():
        console.print(
            f"The guide's {f} hasn't been checked against the game in a while; some advice may be out of date.",
            markup=False,
            style="yellow",
        )
    plan = build_mastery_plan(report, kb)
    if show_plan:
        _print_plan(plan)
    console.print(
        f"[bold]MR {plan.rank}[/bold]  estimated mastery ~{plan.estimate:,} · "
        f"~{plan.needed_to_target:,} to MR {plan.target_rank}, in {len(plan.phases)} steps"
    )
    if plan.tonight:
        console.print(f"Tonight: {plan.tonight[0].title}", markup=False)
    if not html:
        if not show_plan:
            console.print("Add --show-plan to print the whole plan here.", markup=False, style="dim")
        return
    folder = out or _export_folder(s, snap, share)
    if folder.suffix.lower() == ".html":
        folder = folder.parent
    with console.status("Writing the guide..."):
        bundle = write_guide_bundle(plan, folder, pdf=pdf, docx=docx, copy_to=targets, share=share)
    for w in bundle.warnings:
        console.print(w, markup=False, style="yellow")
    for t_, where in bundle.cloud.items():
        console.print(f"copied to {t_}: {where}", markup=False, style="green")
    console.print()
    for f in bundle.files():
        console.print(f"[green]wrote[/green] {_e(str(f))}")
    if not show_plan:
        console.print(
            "Open the HTML file for the full plan, or add --show-plan to print it here.", style="dim"
        )
    if open_:
        _open_in_browser(bundle.html)


def _print_plan(plan) -> None:
    t = Table(title="ranks", show_edge=False)
    for col, just in (
        ("rank", "right"),
        ("title", "left"),
        ("needed", "right"),
        ("to earn", "right"),
        ("test", "left"),
    ):
        t.add_column(col, justify=just)
    for r in plan.ranks:
        t.add_row(str(r.rank), _e(r.title), f"{r.threshold:,}", f"{r.to_earn:,}", _e(r.test))
    console.print(t)
    console.print("\n[bold]Tonight[/bold]")
    for item in plan.tonight:
        console.print(f"  [yellow]{_e(item.gain_label):>8}[/yellow]  {_e(item.title)}")
    console.print("\n[bold]The path[/bold]")
    for p in plan.phases:
        head = "already there" if p.already_there else f"~{p.need:,}"
        console.print(
            f"  [bold]{p.from_rank} -> {p.to_rank}[/bold] {_e(p.title)} ({head}, test: {_e(p.test)})"
        )
        for st in p.steps:
            names = ", ".join(st.items[:6]) + (" ..." if len(st.items) > 6 else "")
            console.print(f"      +{st.mastery:>7,}  {_e(st.title)}: [dim]{_e(names)}[/dim]")
    console.print("\n[bold]Tests[/bold]")
    for tc in plan.tests:
        console.print(f"  {tc.rank}  {_e(tc.name)}  [dim]bring: {_e(tc.bring)}[/dim]")
    console.print()


# -- account -----------------------------------------------------------------------------


@account_app.command("howto")
def account_howto() -> None:
    """Explain how to find your account id."""
    from .sources.account.profile import HOW_TO_FIND_ID

    console.print(HOW_TO_FIND_ID)


@account_app.command("set")
def account_set(
    id: str = typer.Option(..., "--id", help="24-character account id (the warframe.com `gid` cookie)."),
    platform: str = typer.Option(
        "pc",
        "--platform",
        help="pc, ps4 (PlayStation), xb1 (Xbox), swi (Switch), mob (iPhone/iPad) or and (Android).",
    ),
) -> None:
    """Store the account id and platform in config.toml."""
    from .config import save_settings
    from .sources.account.profile import HOSTS, ProfileError, validate_account_id

    s = load_settings()
    try:
        s.account_id = validate_account_id(id)
    except ProfileError as exc:
        raise typer.BadParameter(str(exc)) from None
    if platform not in HOSTS:
        raise typer.BadParameter(f"platform must be one of {', '.join(HOSTS)}")
    s.platform = platform
    console.print(f"saved to {save_settings(s)}")


@account_app.command("show")
def account_show() -> None:
    """Show the configured account."""
    s = load_settings()
    console.print(
        f"platform: {s.platform}\naccount id: {s.account_id or '[not set]'}\nconfig: {s.config_path}",
        markup=False,
    )


# -- snapshots ----------------------------------------------------------------------------


def _open_codex(s):
    from .codex import Codex

    return Codex(s.codex_path) if s.codex_path.exists() else None


def _print_summary(snapshot, codex) -> None:
    from .account.summary import summarize

    sm = summarize(snapshot, codex)
    who = snapshot.identity.display_name or "account"
    age = ""
    if sm.account_age_days:
        age = f" - playing for {sm.account_age_days // 365} y {sm.account_age_days % 365 // 30} m"
    console.print(f"[bold]{_e(who)}[/bold]  MR {sm.mastery_rank}{age}")
    bits = []
    if sm.play_time_h:
        bits.append(f"{sm.play_time_h:,.0f} h played")
    if sm.missions_completed:
        bits.append(f"{sm.missions_completed:,} missions")
    nodes = f"{sm.nodes_done}" + (f" / {sm.nodes_total}" if sm.nodes_total else "")
    other = f", +{sm.nodes_other} other" if sm.nodes_other else ""
    bits.append(f"star chart {nodes} nodes ({sm.steel_path_done} Steel Path{other})")
    bits.append(f"syndicates {sm.syndicates_max} maxed of {sm.syndicates_total}")
    bits.append(f"{sm.challenges_tracked} achievements tracked")
    console.print("  " + " - ".join(bits))
    t = Table(title="mastery", show_edge=False)
    t.add_column("category")
    t.add_column("mastered", justify="right")
    t.add_column("leveling", justify="right")
    t.add_column("in game", justify="right")
    for c in sm.categories:
        t.add_row(c.category, str(c.mastered), str(c.leveling), str(c.total) if c.total is not None else "?")
    console.print(t)
    if sm.unmastered_names:
        console.print("[dim]owned, not mastered: " + _e(", ".join(sm.unmastered_names)) + "[/dim]")


def _print_diff(d) -> None:
    if d.is_empty():
        console.print(f"[dim]no progression changes since {d.before:%Y-%m-%d %H:%M}[/dim]")
        return
    console.print(
        f"\n[bold]Changes[/bold] {d.before:%Y-%m-%d %H:%M} -> {d.after:%Y-%m-%d %H:%M}"
        f"  ({d.play_time_h:.1f} h played, {d.missions_completed} missions)"
    )
    if d.mastery_rank[0] != d.mastery_rank[1]:
        console.print(f"  mastery rank {d.mastery_rank[0]} -> {d.mastery_rank[1]}")
    if d.newly_mastered:
        console.print("  [green]mastered:[/green] " + _e(", ".join(d.newly_mastered)))
    if d.rank_ups:
        console.print(
            "  ranked up: " + ", ".join(f"{n} {a}->{b}" for n, a, b in d.rank_ups[:15]), markup=False
        )
    new_only = [n for n in d.newly_leveled if n not in d.newly_mastered]
    if new_only:
        console.print("  started leveling: " + ", ".join(new_only[:15]), markup=False)
    if d.new_nodes:
        console.print("  new nodes: " + ", ".join(d.new_nodes[:15]), markup=False)
    if d.new_steel_path_nodes:
        console.print("  [magenta]Steel Path:[/magenta] " + _e(", ".join(d.new_steel_path_nodes[:15])))
    if d.standing:
        console.print("  standing: " + ", ".join(f"{n} {v:+,}" for n, v in d.standing[:10]), markup=False)
    if d.challenges_progressed:
        console.print(f"  achievements progressed: {len(d.challenges_progressed)}")


@app.command()
def sync(force: bool = typer.Option(False, "--force", help="Ignore the 10-minute profile cache.")) -> None:
    """Fetch the public profile and store a snapshot."""
    from .account.store import SnapshotStore, diff_snapshots
    from .account.sync import sync_profile
    from .sources.account.profile import ProfileError

    s = load_settings()
    store = SnapshotStore(s.snapshots_dir)
    previous = store.latest()
    try:
        with console.status("Fetching profile..."):
            snapshot, path, written = sync_profile(s, force=force)
    except ProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    _print_summary(snapshot, _open_codex(s))
    if written:
        console.print(f"[dim]snapshot written to {path}[/dim]")
        if previous:
            _print_diff(diff_snapshots(previous, snapshot))
    else:
        console.print(
            f"[dim]profile unchanged since {snapshot.taken_at:%Y-%m-%d %H:%M} (DE caches it ~10 min); nothing new written[/dim]"
        )


@app.command()
def summary(
    ref: str = typer.Argument("latest", help="Snapshot file, prefix, 'latest' or 'previous'."),
) -> None:
    """Summarize a stored snapshot."""
    from .account.store import SnapshotStore

    s = load_settings()
    _print_summary(SnapshotStore(s.snapshots_dir).load(ref), _open_codex(s))


@app.command()
def snapshots() -> None:
    """List stored snapshots."""
    from .account.store import SnapshotStore

    s = load_settings()
    paths = SnapshotStore(s.snapshots_dir).list()
    if not paths:
        console.print("no snapshots yet; run `openwarframe sync`")
        return
    for p in paths:
        console.print(f"  {p.stem}  [dim]{p.stat().st_size // 1024} KB[/dim]")


@app.command()
def diff(
    before: str = typer.Argument("previous", help="Older snapshot (file, prefix, 'previous')."),
    after: str = typer.Argument("latest", help="Newer snapshot (file, prefix, 'latest')."),
) -> None:
    """What changed between two snapshots."""
    from .account.store import SnapshotStore, diff_snapshots

    s = load_settings()
    store = SnapshotStore(s.snapshots_dir)
    _print_diff(diff_snapshots(store.load(before), store.load(after)))


# -- codex -------------------------------------------------------------------------------


@codex_app.command("update")
def codex_update(force: bool = typer.Option(False, "--force", help="Ignore the HTTP cache.")) -> None:
    """Download the game data sources and rebuild the codex database."""
    from .codex import update_codex

    s = load_settings()
    with console.status("Fetching sources and building the codex..."):
        report = update_codex(s, force=force)
    t = Table(title=f"codex rebuilt in {report.seconds:.1f}s -> {s.codex_path}")
    t.add_column("table")
    t.add_column("rows", justify="right")
    for k, v in report.counts.items():
        t.add_row(k, f"{v:,}")
    console.print(t)
    for w in report.warnings:
        console.print(w, markup=False, style="yellow")
    if report.unresolved:
        total = sum(c for c, _ in report.unresolved.values())
        console.print(
            f"[yellow]{len(report.unresolved)} drop-table names ({total:,} rows) could not be matched to an item; "
            f"see `openwarframe codex info --unresolved`.[/yellow]"
        )


@codex_app.command("info")
def codex_info(
    unresolved: bool = typer.Option(False, "--unresolved", help="List unmatched drop-table names."),
) -> None:
    """Show source versions and row counts."""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    t = Table(title="sources")
    t.add_column("source")
    t.add_column("version")
    t.add_column("fetched")
    for r in cx.versions():
        t.add_row(r["source"], r["version"], r["fetched_at"])
    console.print(t)
    t = Table(title="tables")
    t.add_column("table")
    t.add_column("rows", justify="right")
    for k, v in cx.counts().items():
        t.add_row(k, f"{v:,}")
    console.print(t)
    if unresolved:
        t = Table(title="unresolved drop-table names (top 50)")
        t.add_column("name")
        t.add_column("rows", justify="right")
        t.add_column("seen in")
        for r in cx.unresolved():
            t.add_row(_e(r["name"]), str(r["count"]), _e(r["sample_source"] or ""))
        console.print(t)


@codex_app.command("search")
def codex_search(
    text: str = typer.Argument(..., help="Part of an item name, e.g. 'rhino'."),
    limit: int = typer.Option(25, "--limit", help="Show at most this many matches."),
) -> None:
    """Find items by name."""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    t = Table()
    t.add_column("name")
    t.add_column("category")
    t.add_column("MR", justify="right")
    t.add_column("uniqueName", style="dim")
    for r in cx.search(text, limit=limit):
        t.add_row(_e(r["name"]), _e(r["category"]), str(r["mastery_req"] or ""), _e(r["unique_name"]))
    console.print(t)


def _resolve_or_exit(cx, query: str) -> str:
    uid = cx.resolve(query)
    if not uid:
        console.print(f"[red]No unique match for '{_e(query)}'.[/red]")
        for m in cx.search(query, limit=8):
            console.print(f"  {_e(m['name'])}  [dim]{_e(m['unique_name'])}[/dim]")
        raise typer.Exit(code=1)
    return uid


@codex_app.command("item")
def codex_item(query: str) -> None:
    """Show an item, its recipe and what it is used for."""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    uid = _resolve_or_exit(cx, query)
    it = cx.item(uid)
    if it:
        console.print(
            f"[bold]{_e(it['name'])}[/bold]  [dim]{_e(it['category'])} - {_e(it['type'] or '')} - MR {it['mastery_req'] or 0}[/dim]"
        )
        console.print(f"[dim]{_e(uid)}[/dim]")
        if it.get("description"):
            console.print(it["description"], markup=False)
        if it.get("market"):
            console.print(f"warframe.market slug: {it['market']['slug']}")
    for r in cx.recipes_for(uid):
        console.print(
            f"\n[bold]Recipe[/bold] {r['unique_name']} · {r['build_price']:,} credits - "
            f"{(r['build_time_s'] or 0) // 3600} h - rush {r['rush_price']} p - makes {r['num']}"
        )
        for ing in cx.ingredients(r["unique_name"]):
            console.print(f"  {ing['count']:>5} x {ing['name']}", markup=False)
    uses = cx.what_needs(uid)
    if uses:
        console.print(f"\n[bold]Used by {len(uses)} recipes[/bold]")
        for u in uses[:20]:
            console.print(f"  {u['count']:>5} x for {u['result_name']}", markup=False)
        if len(uses) > 20:
            console.print(f"  ... {len(uses) - 20} more")


@codex_app.command("sources")
def codex_sources(query: str) -> None:
    """Where can I get this item (or its blueprint)?"""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    uid = _resolve_or_exit(cx, query)
    srcs = cx.sources_for(uid)
    console.print(f"[bold]{_e(cx.name_of(uid))}[/bold]  [dim]{_e(uid)}[/dim]")
    if not srcs:
        console.print(
            "[yellow]No source recorded in the codex (crafted from parts, quest reward, or missing data).[/yellow]"
        )
        return
    t = Table()
    t.add_column("kind")
    t.add_column("where")
    t.add_column("detail")
    for src in srcs:
        t.add_row(src.kind, _e(src.where), _e(src.detail))
    console.print(t)


@codex_app.command("tree")
def codex_tree(
    query: str = typer.Argument(..., help="Item name, e.g. 'Rhino Prime'."),
    count: int = typer.Option(1, "--count", help="How many to build: multiplies every amount."),
    depth: int = typer.Option(6, "--depth", help="How many crafting levels to expand."),
) -> None:
    """Full crafting tree with resource totals."""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    uid = _resolve_or_exit(cx, query)
    tree = cx.crafting_tree(uid, count=count, depth=depth)

    def render(n, parent):
        label = f"{n.count} x {_e(n.name)}" + ("  [dim](crafted)[/dim]" if n.recipe else "")
        branch = parent.add(label)
        for ch in n.children:
            render(ch, branch)

    root = Tree(f"[bold]{tree.count} x {_e(tree.name)}[/bold]")
    for ch in tree.children:
        render(ch, root)
    console.print(root)
    totals = cx.tree_totals(tree)
    t = Table(title="leaf totals")
    t.add_column("count", justify="right")
    t.add_column("item")
    for _uid, (name, c) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        t.add_row(f"{c:,}", _e(name))
    console.print(t)


def _friendly(exc: BaseException) -> str | None:
    """A one-line explanation and next step for failures a player can fix, else None."""
    import httpx

    from .sources.account.profile import ProfileError
    from .sources.account.session import SessionError

    text = str(exc)
    if isinstance(exc, FileNotFoundError):
        if "codex not found" in text:
            return "No game database yet. Run: openwarframe codex update"
        if "previous snapshot" in text:
            return (
                "Comparing needs two snapshots. Run `openwarframe sync` again later, after you have played."
            )
        if "snapshot" in text:
            return "No profile snapshot yet. Run: openwarframe sync"
        return f"File not found: {exc.filename or text}"
    if isinstance(exc, PermissionError):
        return f"{exc.filename or 'A file'} is open in another program (Excel?). Close it and run this again."
    if isinstance(exc, ProfileError | SessionError):
        return text
    if isinstance(exc, httpx.HTTPError):
        return f"Network problem: {text}. Check your internet connection and try again."
    return None


def main() -> None:
    """Console entry point: known problems print one line and a next step, not a traceback."""
    try:
        app(prog_name="openwarframe")
    except Exception as exc:  # noqa: BLE001 - re-raised below unless it is one we can explain
        message = _friendly(exc)
        if message is None:
            raise
        console.print(message, markup=False, style="red")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
