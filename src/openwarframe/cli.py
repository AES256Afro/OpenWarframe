"""OpenWarframe command line."""

from __future__ import annotations

import logging
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
app.add_typer(codex_app, name="codex")
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
        import os

        os.environ["OPENWARFRAME_HOME"] = str(home)


@app.command()
def version() -> None:
    """Print the version and data directory."""
    s = load_settings()
    console.print(f"openwarframe {__version__}  -  data in {s.home}")


@app.command()
def sync() -> None:
    """Take an account snapshot (milestone 2, not implemented yet)."""
    raise typer.Exit(code=_not_yet("sync", "M2"))


@app.command()
def export() -> None:
    """Export the latest snapshot (milestone 4, not implemented yet)."""
    raise typer.Exit(code=_not_yet("export", "M4"))


@app.command()
def plan() -> None:
    """Recommend what to do next (milestone 7, not implemented yet)."""
    raise typer.Exit(code=_not_yet("plan", "M7"))


def _not_yet(cmd: str, milestone: str) -> int:
    console.print(f"[yellow]`openwarframe {cmd}` arrives in {milestone}. See docs/ROADMAP.md.[/yellow]")
    return 2


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

    s = load_settings()
    cx = Codex(s.codex_path)
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
        matches = cx.search(query, limit=8)
        console.print(f"[red]No unique match for '{query}'.[/red]")
        for m in matches:
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
