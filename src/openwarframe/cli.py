"""OpenWarframe command line."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from . import __version__
from .config import load_settings

app = typer.Typer(help="Export, explain and plan your Warframe account.", no_args_is_help=True)
codex_app = typer.Typer(
    help="The local game database (items, recipes, drops, vendors).", no_args_is_help=True
)
account_app = typer.Typer(help="Which account to snapshot.", no_args_is_help=True)
app.add_typer(codex_app, name="codex")
app.add_typer(account_app, name="account")
guide_app = typer.Typer(help="Guides built from your snapshot and the knowledge base.", no_args_is_help=True)
app.add_typer(guide_app, name="guide")
console = Console()


@app.callback()
def _main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log what is being fetched."),
    home: Path | None = typer.Option(
        None, "--home", help="Data directory (default: OPENWARFRAME_HOME or the OS app-data dir)."
    ),
) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    if home:
        os.environ["OPENWARFRAME_HOME"] = str(home)


@app.command()
def version() -> None:
    """Print the version and data directory."""
    s = load_settings()
    console.print(f"openwarframe {__version__}  -  data in {s.home}")


@app.command()
def export(
    formats: str = typer.Option(
        "json,sqlite,csv,xlsx,llm,guide",
        "--format",
        "-f",
        help="Comma-separated: json, sqlite, csv, xlsx, llm, guide.",
    ),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Output directory (default: data dir/exports/<date>)."
    ),
    snapshot: str = typer.Option(
        "latest", "--snapshot", help="Snapshot file, prefix, 'latest' or 'previous'."
    ),
    share: bool = typer.Option(False, "--share", help="Strip display name, clan and raw payloads."),
    budget: str = typer.Option("compact", "--budget", help="LLM brief budget: compact (~8k tokens) or full."),
    pdf: bool = typer.Option(
        True, "--pdf/--no-pdf", help="With the guide, also print a PDF (needs Chrome or Edge)."
    ),
    copy_to: str | None = typer.Option(
        None, "--copy-to", help="Copy the guide files to cloud sync folders: onedrive, gdrive or both."
    ),
) -> None:
    """Export a snapshot to JSON, SQLite, CSV, Excel, an LLM brief and the mastery guide (HTML, Word, PDF)."""
    from .account.store import SnapshotStore
    from .account.sync import reparse
    from .codex import Codex
    from .exports import FORMATS, run_exports
    from .report import build_report

    s = load_settings()
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
    codex = Codex(s.codex_path)
    with console.status("Building report..."):
        report = build_report(reparse(snap, codex), codex, anonymize=share)
    target = out or (s.exports_dir / snap.taken_at.strftime("%Y-%m-%d_%H%M") / ("share" if share else "full"))
    with console.status("Writing exports..."):
        results = run_exports(
            report, target, wanted, brief_budget=budget, guide_pdf=pdf, copy_to=targets, share=share
        )
    t = Table(title=f"exports -> {target}", show_edge=False)
    t.add_column("format")
    t.add_column("file")
    t.add_column("detail")
    t.add_column("size", justify="right")
    for r in results:
        t.add_row(
            r.format, r.path.name + ("/" if r.path.is_dir() else ""), r.detail, f"{r.size / 1024:,.0f} KB"
        )
    console.print(t)
    if share:
        console.print("[yellow]share mode: display name, clan and raw payloads removed[/yellow]")


@app.command()
def schema(out: Path = typer.Option(Path("docs/schema/account.schema.json"), "--out")) -> None:
    """Write the JSON Schema for account.json."""
    from .exports.data import write_schema

    out.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"wrote {write_schema(out)}")


@app.command()
def plan() -> None:
    """Recommend what to do next (milestone 7, not implemented yet)."""
    raise typer.Exit(code=_not_yet("plan", "M7"))


def _not_yet(cmd: str, milestone: str) -> int:
    console.print(f"[yellow]`openwarframe {cmd}` arrives in {milestone}. See docs/ROADMAP.md.[/yellow]")
    return 2


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
    codex = Codex(s.codex_path)
    return s, snap, build_report(reparse(snap, codex), codex, anonymize=share)


@guide_app.command("mastery")
def guide_mastery(
    snapshot: str = typer.Option(
        "latest", "--snapshot", help="Snapshot file, prefix, 'latest' or 'previous'."
    ),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Where to write mastery-plan.html (default: data dir/exports/<date>/)."
    ),
    html: bool = typer.Option(True, "--html/--no-html", help="Write the guide files (HTML, Word, PDF)."),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Also print a PDF (needs Chrome or Edge)."),
    docx: bool = typer.Option(True, "--docx/--no-docx", help="Also write a Word document."),
    copy_to: str | None = typer.Option(
        None, "--copy-to", help="Copy the files to cloud sync folders: onedrive, gdrive or both."
    ),
    open_: bool = typer.Option(False, "--open", help="Open the HTML guide in your browser when done."),
    share: bool = typer.Option(False, "--share", help="Strip display name and clan."),
) -> None:
    """Your road to Mastery Rank 30: rank table, tonight's checklist, phased plan and test cards."""
    from .guide import build_mastery_plan, load_kb, write_guide_bundle

    targets = _cloud_targets(copy_to)

    s, snap, report = _load_report(snapshot, share)
    plan = build_mastery_plan(report, load_kb())
    console.print(
        f"[bold]MR {plan.rank}[/bold]  estimated mastery ~{plan.estimate:,}  -  "
        f"~{plan.needed_to_target:,} to MR {plan.target_rank}"
    )
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
        t.add_row(str(r.rank), r.title, f"{r.threshold:,}", f"{r.to_earn:,}", r.test)
    console.print(t)
    console.print("\n[bold]Tonight[/bold]")
    for item in plan.tonight:
        console.print(f"  [yellow]{item.gain_label:>8}[/yellow]  {item.title}")
    console.print("\n[bold]The path[/bold]")
    for p in plan.phases:
        head = "already there" if p.already_there else f"~{p.need:,}"
        console.print(f"  [bold]{p.from_rank} -> {p.to_rank}[/bold] {p.title} ({head}, test: {p.test})")
        for st in p.steps:
            names = ", ".join(st.items[:6]) + (" ..." if len(st.items) > 6 else "")
            console.print(f"      +{st.mastery:>7,}  {st.title}: [dim]{names}[/dim]")
    console.print("\n[bold]Tests[/bold]")
    for tc in plan.tests:
        console.print(f"  {tc.rank}  {tc.name}  [dim]bring: {tc.bring}[/dim]")
    if html:
        folder = out or (s.exports_dir / snap.taken_at.strftime("%Y-%m-%d_%H%M"))
        if folder.suffix.lower() == ".html":
            folder = folder.parent
        with console.status("Writing the guide..."):
            bundle = write_guide_bundle(plan, folder, pdf=pdf, docx=docx, copy_to=targets, share=share)
        console.print()
        for f in bundle.files():
            console.print(f"[green]wrote[/green] {f}")
        for t_, where in bundle.cloud.items():
            console.print(f"[green]copied to {t_}[/green] {where}")
        for w in bundle.warnings:
            console.print(f"[yellow]{w}[/yellow]")
        if open_:
            import webbrowser

            webbrowser.open(bundle.html.resolve().as_uri())


# -- account -----------------------------------------------------------------------------


@account_app.command("howto")
def account_howto() -> None:
    """Explain how to find your account id."""
    from .sources.account.profile import HOW_TO_FIND_ID

    console.print(HOW_TO_FIND_ID)


@account_app.command("set")
def account_set(
    id: str = typer.Option(..., "--id", help="24-character account id (the warframe.com `gid` cookie)."),
    platform: str = typer.Option("pc", "--platform", help="pc, ps4, xb1, swi, mob or and."),
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
        f"platform: {s.platform}\naccount id: {s.account_id or '[not set]'}\nconfig: {s.config_path}"
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
    console.print(f"[bold]{who}[/bold]  MR {sm.mastery_rank}{age}")
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
        console.print("[dim]owned, not mastered: " + ", ".join(sm.unmastered_names) + "[/dim]")


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
        console.print("  [green]mastered:[/green] " + ", ".join(d.newly_mastered))
    if d.rank_ups:
        console.print("  ranked up: " + ", ".join(f"{n} {a}->{b}" for n, a, b in d.rank_ups[:15]))
    new_only = [n for n in d.newly_leveled if n not in d.newly_mastered]
    if new_only:
        console.print("  started leveling: " + ", ".join(new_only[:15]))
    if d.new_nodes:
        console.print("  new nodes: " + ", ".join(d.new_nodes[:15]))
    if d.new_steel_path_nodes:
        console.print("  [magenta]Steel Path:[/magenta] " + ", ".join(d.new_steel_path_nodes[:15]))
    if d.standing:
        console.print("  standing: " + ", ".join(f"{n} {v:+,}" for n, v in d.standing[:10]))
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
            t.add_row(r["name"], str(r["count"]), r["sample_source"] or "")
        console.print(t)


@codex_app.command("search")
def codex_search(text: str, limit: int = 25) -> None:
    """Find items by name."""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    t = Table()
    t.add_column("name")
    t.add_column("category")
    t.add_column("MR", justify="right")
    t.add_column("uniqueName", style="dim")
    for r in cx.search(text, limit=limit):
        t.add_row(r["name"], r["category"], str(r["mastery_req"] or ""), r["unique_name"])
    console.print(t)


def _resolve_or_exit(cx, query: str) -> str:
    uid = cx.resolve(query)
    if not uid:
        console.print(f"[red]No unique match for '{query}'.[/red]")
        for m in cx.search(query, limit=8):
            console.print(f"  {m['name']}  [dim]{m['unique_name']}[/dim]")
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
            f"[bold]{it['name']}[/bold]  [dim]{it['category']} - {it['type'] or ''} - MR {it['mastery_req'] or 0}[/dim]"
        )
        console.print(f"[dim]{uid}[/dim]")
        if it.get("description"):
            console.print(it["description"])
        if it.get("market"):
            console.print(f"warframe.market slug: {it['market']['slug']}")
    for r in cx.recipes_for(uid):
        console.print(
            f"\n[bold]Recipe[/bold] {r['unique_name']}  -  {r['build_price']:,} credits - "
            f"{(r['build_time_s'] or 0) // 3600} h - rush {r['rush_price']} p - makes {r['num']}"
        )
        for ing in cx.ingredients(r["unique_name"]):
            console.print(f"  {ing['count']:>5} x {ing['name']}")
    uses = cx.what_needs(uid)
    if uses:
        console.print(f"\n[bold]Used by {len(uses)} recipes[/bold]")
        for u in uses[:20]:
            console.print(f"  {u['count']:>5} x for {u['result_name']}")
        if len(uses) > 20:
            console.print(f"  ... {len(uses) - 20} more")


@codex_app.command("sources")
def codex_sources(query: str) -> None:
    """Where can I get this item (or its blueprint)?"""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    uid = _resolve_or_exit(cx, query)
    srcs = cx.sources_for(uid)
    console.print(f"[bold]{cx.name_of(uid)}[/bold]  [dim]{uid}[/dim]")
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
        t.add_row(src.kind, src.where, src.detail)
    console.print(t)


@codex_app.command("tree")
def codex_tree(query: str, count: int = 1, depth: int = 6) -> None:
    """Full crafting tree with resource totals."""
    from .codex import Codex

    cx = Codex(load_settings().codex_path)
    uid = _resolve_or_exit(cx, query)
    tree = cx.crafting_tree(uid, count=count, depth=depth)

    def render(n, parent):
        label = f"{n.count} x {n.name}" + ("  [dim](crafted)[/dim]" if n.recipe else "")
        branch = parent.add(label)
        for ch in n.children:
            render(ch, branch)

    root = Tree(f"[bold]{tree.count} x {tree.name}[/bold]")
    for ch in tree.children:
        render(ch, root)
    console.print(root)
    totals = cx.tree_totals(tree)
    t = Table(title="leaf totals")
    t.add_column("count", justify="right")
    t.add_column("item")
    for _uid, (name, c) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        t.add_row(f"{c:,}", name)
    console.print(t)


if __name__ == "__main__":
    app()
