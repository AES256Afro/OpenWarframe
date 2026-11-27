# Exports

```bash
uv run openwarframe export
```

Exports the latest snapshot into `%LOCALAPPDATA%\OpenWarframe\exports\<snapshot time>\full`
(the time is your local time). `exports\LATEST.txt` always holds the path of the newest
export folder, and the command prints it at the end.

Options:

- `--format json,sqlite,csv,xlsx,llm,dashboard,guide`: any subset.
- `--out <dir>`: write somewhere else.
- `--snapshot <ref>`: a snapshot file, prefix, `latest` or `previous`.
- `--share`: strip display name, clan and raw payloads; writes to `...\share`.
- `--budget compact|full`: size of the LLM brief.
- `--no-pdf`: skip the PDFs of the guide, brief and dashboard. PDFs need Chrome, Edge,
  Chromium or Brave; without one you get a one-line note and everything else.
- `--copy-to onedrive|gdrive|onedrive,gdrive`: copy the guide files into your OneDrive or
  Google Drive sync folder, so the desktop app uploads them.
- `--open`: open the export folder when done.
- `--remember`: keep the `--budget`, `--pdf`/`--no-pdf` and `--copy-to` you gave as your
  defaults for next time (saved in `config.toml`).

`openwarframe guide mastery` writes the mastery guide on its own, to the same folder
(`...\full`, or `...\share` with `--share`). It prints a short summary and the files it
wrote; add `--show-plan` to print the whole plan in the terminal.

Every format is rendered from one report model, so the numbers always agree. The raw
profile stored in the snapshot is re-parsed with the current codex on each export, so
better item names and categories reach old snapshots too.

| File | What it is |
| --- | --- |
| `account.json` | The full report. Schema `openwarframe.account/1`, published at [schema/account.schema.json](schema/account.schema.json) (regenerate with `openwarframe schema --out docs/schema/account.schema.json`). |
| `account.sqlite` | One table per section below plus `meta` (schema version, snapshot time, coverage, anonymized flag). |
| `csv/*.csv` | Same tables as SQLite, UTF-8 with BOM so Excel opens them cleanly. |
| `OpenWarframe-<date>.xlsx` | Styled workbook: Summary sheet with KPI tiles, category table and a stacked bar chart, a "Since last sync" sheet when there is an earlier snapshot, then one filterable sheet per table with conditional formatting. Yes/No columns, A4 landscape print setup with the header row on every page. Internal ids sit in hidden columns. |
| `account-brief.md` + `.json` | LLM planning brief. Compact is about 6-8k tokens and its JSON holds the same content; full (`account-brief-full.*`) lists everything. Includes your goals from the app, what changed since the last sync, standing left today and whether a rank test is ready, when known. |
| `account-brief.html` + `.pdf` | The same brief as a printable page and a text-selectable PDF, for agents and tools that take file uploads. `--no-pdf` skips the PDF. |
| `dashboard.html` + `.pdf` + `.docx` | The account dashboard: mastery ring and KPIs, arsenal by category, closest to done, most used, get next, star chart with Steel Path, syndicates and a data-coverage panel. One self-contained page with light, dark and print themes; the PDF is the page printed on A4 landscape; the Word file has the same sections as tables. |
| `mastery-plan.html` + `.pdf` + `.docx` | Road to Mastery 30: rank table, tonight's checklist, a phased plan per rank, mood cards, a mastery budget and test cards. PDF and Word are A4. Also `openwarframe guide mastery`. See [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md#mastery-guide). |

The HTML pages are self-contained and work offline: they load nothing from other sites.
Fonts come from your computer (Cinzel when installed, otherwise Georgia and your system
fonts).

## Tables

| Table | Rows | Notes |
| --- | --- | --- |
| `summary` | key / value | Headline numbers. |
| `categories` | one per masterable category | mastered, leveling (owned, below rank 30), missing (never leveled), total. |
| `missing_items` | masterable items with no XP | `acquisition` summarises routes: Relics (farmable now / vaulted), Vendor / standing, Mission drops, Bounties, Enemy drops, Trade, or no drop data. `best_sources` lists the top sources for the blueprint and each component. |
| `missing_sources` | one row per source | Long form of the above, with a `farmable` flag for relics. |
| `owned_items` | items with XP | rank (from XP), mastered, `xp_to_30`. |
| `star_chart` | every node in the codex | completed, Steel Path, completions, mission type, faction, level. |
| `syndicates` | each affiliation | Nightwave seasons are labelled individually. |
| `achievements` | each tracked challenge | Named through the codex where possible. |
| `intrinsics` | Railjack and Drifter | Ranks and unspent pools. |
| `weapon_usage` | lifetime stats per item | kills, headshots, equip hours, XP. |
| `sources` | data versions | Public Export hash, export-plus commit, drop data hash, market fetch time, snapshot. |

## What counts as masterable

An item is masterable when its codex category is one of Warframe, Primary, Secondary,
Melee, Companion, Companion Weapon, Archwing, Archgun, Archmelee, Necramech, Amp or
K-Drive and the Public Export does not flag it `excludeFromCodex`. For modular gear
only the part that grants mastery counts: Zaw strike, Kitgun chamber, Amp prism,
K-Drive deck, MOA and Hound model. PvP variant parts are ignored.

## Limits of a profile-only snapshot

- "Missing" means never leveled. Items you own but never equipped count as missing.
- Resource counts, owned blueprints, foundry, relics and mods need your inventory (load it in the app or with `openwarframe inventory`).
- Mastery XP from star chart nodes, Steel Path and junctions is not in the profile. The
  items + intrinsics figure is computed exactly; the estimated total adds completed star
  chart and Steel Path nodes (14,569 for all 241 mastery nodes, about 60 each) and
  junctions (1,000 each, normal and Steel Path), and is labelled as an estimate.
- Item ranks are capped at 30, or 40 for Kuva, Tenet, Coda and Dual Coda weapons,
  Paracesis and Necramechs; the profile keeps counting affinity past the cap.
- Relic farmability means the relic appears in the current drop tables. It updates
  when you run `openwarframe codex update`.

## Item names in another language

`openwarframe export --names de` (or the app's Settings > Item names) writes item, part and relic
names in that language in every format. Column names, categories and the rest of the text stay
English. See [I18N.md](I18N.md).

