# Architecture

## Pipeline

```
          STATIC                      ACCOUNT                        LIVE
 ┌──────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
 │ Public Export (DE)   │   │ Public profile (Tier 1)│   │ worldState.php (official)│
 │ public-export-plus   │   │ Inventory JSON (Tier 2)│   │ EE.log tail (optional)   │
 │ WFCD drop data       │   │ [AlecaFrame hand-off]  │   │ browse.wf oracle (opt.)  │
 │ warframe.market v2   │   │ [login adapter, DG1]   │   └─────────────┬────────────┘
 └──────────┬───────────┘   └───────────┬────────────┘                 │
            ▼                           ▼                              ▼
     codex.sqlite                snapshots/<ts>.json              live state (cached)
   (items, recipes,            (raw + normalized,                 (raw + normalized)
    relics, nodes, drops,       append-only)
    vendors, prices)                    │                              │
            └──────────────┬────────────┴──────────────────────────────┘
                           ▼
                    analysis/
          gaps · crafting trees · source ranking · affinity plan
          planner (events × gaps) · goals · knowledge-base rules
                           │
                           ▼
                      exports/
   json · sqlite · csv · xlsx · html dashboard · pdf · docx · llm brief
```

Three principles:

1. **Keep the raw.** Every fetched payload is stored verbatim next to its normalized
   form, so parsers can be improved and re-run without re-fetching.
2. **Join on `uniqueName`.** Public Export, drop data (after a name map), the profile,
   the inventory and warframe.market (`gameRef`) all speak it.
3. **Degrade gracefully.** The tool works with a profile alone; every feature states
   which sections it needs and hides itself, with a reason, when they are missing.

## Modules

| Module | Responsibility |
| --- | --- |
| `sources/static/` | `public_export.py` (index decode, manifest fetch, cleaning), `pe_plus.py`, `wfcd_drops.py`, `market.py`. Each returns typed records and a `SourceVersion`. |
| `sources/account/` | `profile.py` (Tier 1), `inventory_file.py`, optional adapters. All implement `InventorySource`. |
| `sources/live/` | `worldstate.py`, `eelog.py` (tail, line classifiers), `oracle.py`. |
| `codex/` | SQLite schema, loaders, `queries.py` ("sources for item", "crafting tree", "what needs X"). |
| `account/` | `Snapshot` model (pydantic), merge of profile + inventory, `coverage`, `diff`. |
| `analysis/` | `gaps.py`, `tree.py`, `ranking.py`, `affinity.py`, `planner.py`, `goals.py`, `stage.py`. |
| `kb/` | YAML loader, `applies_if` rule evaluation (a small safe expression language over the snapshot), rendering helpers. |
| `exports/` | One module per format sharing a `ReportModel` (the dashboard's view model) so every format shows the same numbers. |
| `cli.py` | Typer app: `sync`, `codex update`, `export`, `plan`, `guide`, `diff`, `share`. |

## Data model (SQLite)

Codex (rebuilt from sources, safe to delete):

```
item(unique_name PK, name, category, type, mastery_req, tradable, image, vaulted, introduced)
recipe(unique_name PK, result_item, build_price, build_time_s, rush_price, num)
recipe_ingredient(recipe, item, count)
relic(unique_name PK, name, tier, vaulted)          relic_reward(relic, item, rarity, chance_intact..radiant)
node(id PK, name, planet, mission_type, faction, level_min, level_max, mastery_req, steel_path)
node_reward(node, rotation, item, chance, game_mode)
enemy_drop(enemy, item, chance, mod_drop_chance)    vendor_offer(vendor, item, currency, cost, standing_rank)
bounty_reward(bounty, stage, item, chance)          challenge(unique_name PK, name, description, hidden)
market_item(unique_name, slug, name)                source_version(source, version, fetched_at)
```

Account (one row set per snapshot, never rewritten):

```
snapshot(id PK, taken_at, sources_json, coverage_json)
progression(snapshot, mastery_rank, mastery_xp, created_at, clan, ...)
item_xp(snapshot, item, xp, mastered)               node_progress(snapshot, node, completes, steel_path)
affiliation(snapshot, syndicate, standing, title)   achievement(snapshot, challenge, progress, completed_at)
owned_item(snapshot, item, count, kind)             -- resources, blueprints, relics(+refinement), mods(+rank)
equipment(snapshot, item, xp, polarities_json, slots_json)
foundry(snapshot, recipe, started_at, ready_at)     quest(snapshot, key, completed, stage)
currency(snapshot, credits, platinum, endo, aya, regal_aya)
```

## Snapshot model and merging

`Snapshot = Progression + Possessions + Stats + Meta`. The profile fills
`Progression` and `Stats` entirely and `Possessions.equipment` partially (what has XP).
The inventory fills `Possessions` entirely. When both exist the inventory wins for
possessions and the profile wins for stats; conflicts are logged.

## Analysis

- **Gaps.** For each item in the codex that the account could care about (filter by
  category and mastery), classify: mastered, owned-unmastered, built-not-owned (sold),
  blueprint-only, partial components, nothing. Produce the crafting tree with net
  requirements.
- **Source ranking.** Each source gets an estimated minutes-to-obtain:
  relic: (1 / chance at your refinement) × average fissure time, discounted if you own the relic;
  node reward: (1 / chance) × rotation length; enemy drop: (1 / (spawn × drop)) × mission time;
  vendor: 0 if standing is available, else standing-per-day math; market: price vs a
  configurable platinum-per-minute. All constants live in `config.toml` and are shown
  in the UI.
- **Planner.** `recommendation = gap × live_event × source`, scored by
  `value × urgency × feasibility`, with a human-readable `because` string.
- **Affinity plan.** Unleveled gear grouped into loadouts (frame + primary + secondary
  + melee + companion) and matched with affinity-friendly nodes and active boosters.
- **Goals and stage.** Goals are YAML with prerequisites and steps; each step has a
  `done_if` rule over the snapshot. Stage is derived from quests, MR and systems.

## Exports

A single `ReportModel` (view model) is built once and rendered by every exporter:

- `json`: `account.json` (schema-versioned) + `account-brief.json`.
- `sqlite` / `csv`: the account tables above.
- `xlsx`: openpyxl, one sheet per section, styles from a shared palette.
- `html`: Jinja2 template, inline CSS, inline SVG charts, optional base64 icons.
- `pdf`: Playwright prints the HTML with a print stylesheet (DG2: WeasyPrint alternative).
- `docx`: python-docx, same sections, tables and rendered chart images.
- `llm`: Markdown brief with YAML front matter; compact and full budgets.

### LLM brief format

```markdown
---
schema: openwarframe.brief/1
generated: 2026-10-16T13:40:00Z
budget: compact
sources: {profile: 2026-10-16T13:35Z, inventory: none, worldstate: 2026-10-16T13:38Z, codex: pe-2026-10-07}
---
# Account
MR 23 (412,300 / 436,000 XP to 24). Playing since 2019-03. Clan: <stripped>.
Stage: late game. Steel Path star chart 61%. Helminth: unlocked, 29/50 subsumed.

# Gaps (top 20 by closeness)
- Rhino Prime: have Neuroptics, Systems; missing Chassis (Lith R2 relic, you own 3 Radiant) and Blueprint.
...

# Right now (expires)
- Lith fissure, Tessera (Venus), Defense, 38 min left. Run with Lith R2 for Rhino Prime Chassis.
...

# Open goals
- Reach MR 24: 23,700 XP. Fastest: level Zymos (owned, rank 0) + Cedo (owned, rank 12).
...
```

## Configuration and storage

```
%LOCALAPPDATA%\OpenWarframe\
  config.toml      # platform, account id, adapters enabled, ranking constants, share mode
  cache/           # HTTP cache (ETag / max-age)
  codex.sqlite
  snapshots/2026-10-16T133500Z.json
  exports/
```

Nothing leaves the machine except the requests listed in `docs/DATA_SOURCES.md`.

## Technology choices

| Choice | Why | Alternative considered |
| --- | --- | --- |
| Python 3.12 + uv | Fast to iterate, best libraries for xlsx/docx/pdf, easy for contributors | TypeScript (closer to WFCD packages; weaker Excel/Word story) |
| SQLite | Zero setup, single file, fits "feed into a DB" | DuckDB (nice for analytics, heavier) |
| pydantic v2 | Typed models for undocumented JSON, good error messages | dataclasses + manual validation |
| openpyxl | Mature, styling, conditional formatting | xlsxwriter (write-only; faster) |
| python-docx | Standard | docx templates via docxtpl |
| Playwright PDF | Dashboard and PDF share one design | WeasyPrint (no browser, weaker CSS) |
| Typer CLI | Minimal boilerplate | argparse |
| Jinja2 + inline SVG | Offline, single-file dashboard | React app (overkill for v1; possible for M9) |

## Testing

- Fixture accounts in `tests/fixtures/` (synthetic, three stages).
- Recorded source payloads (small, redacted) for parsers.
- Golden-file tests for every export format.
- Property tests on the crafting-tree math (totals never negative, every leaf is a resource).
