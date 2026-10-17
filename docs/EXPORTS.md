# Exports

```bash
uv run openwarframe export
```

Exports the latest snapshot into `%LOCALAPPDATA%\OpenWarframe\exports\<snapshot time>\full`.
Options: `--format json,sqlite,csv,xlsx,llm` (any subset), `--out <dir>`,
`--snapshot <ref>`, `--share` (strip display name, clan and raw payloads; writes to
`...\share`), `--budget compact|full` for the LLM brief.

Every format is rendered from one report model, so the numbers always agree. The raw
profile stored in the snapshot is re-parsed with the current codex on each export, so
better item names and categories reach old snapshots too.

| File | What it is |
| --- | --- |
| `account.json` | The full report. Schema `openwarframe.account/1`, published at [schema/account.schema.json](schema/account.schema.json) (regenerate with `openwarframe schema`). |
| `account.sqlite` | One table per section below plus `meta` (schema version, snapshot time, coverage, anonymized flag). |
| `csv/*.csv` | Same tables as SQLite, UTF-8 with BOM so Excel opens them cleanly. |
| `OpenWarframe-<date>.xlsx` | Styled workbook: Summary sheet with KPI tiles, category table and a stacked bar chart, then one filterable sheet per table with conditional formatting. Internal ids sit in hidden columns. |
| `account-brief.md` + `.json` | LLM planning brief. Compact is about 6–8k tokens; full lists everything. |

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
- Resource counts, owned blueprints, foundry, relics and mods need an inventory source (M3).
- Mastery XP from star chart nodes, Steel Path and junctions is not in the profile. The
  items + intrinsics figure is computed exactly; the estimated total adds completed star
  chart and Steel Path nodes (14,569 for all 241 mastery nodes, about 60 each) and
  junctions (1,000 each, normal and Steel Path), and is labelled as an estimate.
- Item ranks are capped at 30, or 40 for Kuva, Tenet, Coda and Dual Coda weapons,
  Paracesis and Necramechs; the profile keeps counting affinity past the cap.
- Relic farmability means the relic appears in the current drop tables. It updates
  when you run `openwarframe codex update`.
