# OpenWarframe

**Your whole Warframe account: exported, explained, and planned.**

OpenWarframe is a local, open-source tool that pulls everything knowable about your
Warframe account, joins it with the game's official item and drop databases and the
live world state, and turns it into things you can actually use:

| Output | What it is for |
| --- | --- |
| **Account dashboard** (single HTML file) | A visually rich overview of the scope and scale of your account: mastery, arsenal, foundry, star chart, syndicates, achievements. Shareable. |
| **Excel workbook** (`.xlsx`) | Every item, blueprint, relic, mod and resource you own, with filters, totals and a farm plan sheet. |
| **Report** (`.pdf` / `.docx`) | A designed, printable account report with a foundry backlog and "where to go next" pages. |
| **Machine data** (`.json`, `.sqlite`, `.csv`) | Feed it into your own database, scripts or spreadsheets. |
| **LLM planning brief** (`.md` + JSON schema) | A compact, token-budgeted description of your account for ChatGPT, Claude or a local model to plan with. |
| **Planner** | What to farm next, which *active* fissures, invasions, alerts and bounties matter to *you*, which frames and weapons you own but never leveled, daily and weekly checklists, and goals on the road to MR 30 and beyond. |
| **Guide** | A curated knowledge base of systems, unlocks and "things even veterans never knew about", shown only when they apply to your account. |

Status: **M0, M1 and M2 done** (2026-10-16). The codex answers "where do I get X" and
"what does X need"; `sync` snapshots your account from the public profile and `diff`
shows what changed between play sessions. Exports come next (M4).
Read the [roadmap](docs/ROADMAP.md) and the [mockups](docs/mockups/README.md).

## Try it now

```bash
uv sync --all-groups
```

```bash
uv run openwarframe codex update
```

```bash
uv run openwarframe codex sources "Rhino Prime Chassis"
```

```bash
uv run openwarframe codex tree "Rhino Prime"
```

```bash
uv run openwarframe account howto
```

```bash
uv run openwarframe sync
```

Other commands: `codex info|search|item`, `account set|show`, `summary`, `snapshots`,
`diff`. Data lands in `%LOCALAPPDATA%\OpenWarframe` (override with
`OPENWARFRAME_HOME`). On Windows terminals set `PYTHONIOENCODING=utf-8` if box
characters render oddly.

---

## How it gets your data (the honest version)

Warframe has no official "export my account" button. OpenWarframe uses three kinds of
sources, each documented in [docs/ACCOUNT_DATA_ACCESS.md](docs/ACCOUNT_DATA_ACCESS.md):

1. **Public profile (Tier 1, official, read-only).** The same endpoint the in-game
   profile viewer uses. It needs only your account ID and gives mastery rank, XP on
   every item you ever leveled, star chart completion, syndicate standing,
   intrinsics, achievements, loadout and lifetime stats. No credentials, no client
   interaction. Verified working on 2026-10-16.
2. **Full inventory (Tier 2, opt-in).** Resource counts, owned blueprints, foundry
   queue, relics, mods, quests, credits and platinum only exist in the game's
   inventory JSON. There is no official public way to read it. OpenWarframe defines an
   `InventorySource` adapter interface and ships a plain **JSON file import** first.
   Other adapters are a decision for you, with the trade-offs laid out in the doc.
3. **Live signals.** The official world state feed (fissures, invasions, alerts,
   sorties, Archon Hunt, Nightwave, Baro, bounties, events) and, optionally, a
   read-only tail of the game's own `EE.log` for "what mission am I in right now".
   The log contains no session tokens (verified), and OpenWarframe never uploads it.

Everything is joined on the game's internal item path (`uniqueName`, for example
`/Lotus/Powersuits/Rhino/RhinoPrime`), which the Public Export, the drop tables,
warframe.market and the profile all share.

**Safety stance.** OpenWarframe never reads game memory, never injects, never
automates in-game actions and never stores your password. Digital Extremes' policy
is "use external software at your own risk" with no allow-list, so the choice of
Tier 2 adapter stays yours, documented and off by default.

## Where the game data comes from

| Source | Gives us | Verified |
| --- | --- | --- |
| Public Export (official) | 16 manifests: every weapon, frame, recipe with ingredients, resource, relic, mod, region/node, quest, gear | 2026-10-16 |
| warframe-public-export-plus (community, MIT) | Superset with relics, enemies, mission types, rewards, vendors, syndicates, challenges/achievements, Nightwave, bounties | 2026-10-16 |
| Official drop tables via WFCD warframe-drop-data (MIT) | Mission, relic, enemy, bounty, sortie and syndicate drop chances | 2026-10-16 |
| Official world state (`worldState.php`) | 42 sections of live data | 2026-10-16 |
| warframe.market v2 | Prices for 3,893 tradeable items, keyed by `gameRef` | 2026-10-16 |
| Our own curated knowledge base (YAML in this repo) | Farming routes, hidden systems, overlooked achievements, stage-based guides | ongoing |

Details, URLs and licenses: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Planned stack

Python 3.12+ managed with `uv`. `httpx` + `pydantic` for sources and models, SQLite
for the local codex and snapshots, `openpyxl` for Excel, `python-docx` for Word,
headless Chromium (Playwright) to print the HTML dashboard to PDF, `Jinja2` for
templates, `Typer` for the CLI. Rationale and alternatives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```
openwarframe/
  src/openwarframe/
    sources/      # static (public export, drops, market), account (profile, inventory), live (worldstate, eelog)
    codex/        # normalized game database (SQLite) + queries ("where can I get X")
    account/      # snapshot model, diffing, coverage
    analysis/     # gaps, farm ranking, planner, affinity, goals
    kb/           # knowledge base loader + rules engine
    exports/      # json, sqlite, csv, xlsx, html, pdf, docx, llm brief
    cli.py
  kb/             # curated YAML knowledge base (guides, tips, routes)
  docs/           # roadmap, architecture, data sources, mockups
  spikes/         # throwaway proofs of concept that de-risk milestones
  tests/
```

## Mockups

Rendered previews of the planned outputs live in [docs/mockups](docs/mockups/README.md):
account dashboard, Excel workbook, PDF report, planner, and CLI.

## Contributing and license

MIT licensed; see [CONTRIBUTING.md](CONTRIBUTING.md). Third-party data keeps its own
license and is credited in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
