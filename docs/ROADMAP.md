# OpenWarframe roadmap

Ten milestones, each with a goal, deliverables, acceptance criteria, risks and a rough
size. Sizes assume one developer working with AI assistance, part-time. They are
guides, not promises.

Decision gates (marked **DG**) are points where the project owner has to choose
before work continues.

Progress: **M0 done** and **M1 done** on 2026-10-16 (DG0 resolved: MIT). The codex
loads 17k items, 1,885 recipes, 795 relics, 269 nodes, 10k node rewards, 9.9k enemy
drops, 4.7k vendor offers and 3.9k market items in about 6 s from a cold cache; 49
drop-table names (mostly bundles and boosters) stay unresolved and are listed by
`openwarframe codex info --unresolved`.

```
M0 Foundation ─┬─ M1 Codex ──┬─ M2 Profile ──┬─ M4 Exports ── M5 Reports ── M9 Share & package
               │             │               │
               │             └─ M3 Inventory ┤
               │                             ├─ M6 Farm intelligence ── M7 Live planner
               └─ (kb/ can start any time) ──┴─ M8 Goals & guides
```

Milestones M1, M2 and M3 can be built in parallel once M0 exists. M4 onward needs a
snapshot (M2 at minimum). M6 needs M1 + M3 for full value but works on M2 data alone
for mastery gaps.

---

## M0. Foundation

**Goal.** A repository anyone can clone and run in one command, with the conventions
every later milestone builds on.

**Deliverables**
- `uv`-managed Python 3.12+ project, `src/` layout, `pyproject.toml`, lockfile.
- CLI skeleton (`openwarframe --help`) with `sync`, `export`, `plan`, `codex` command groups stubbed.
- Config and data directories (`%LOCALAPPDATA%\OpenWarframe` on Windows, XDG on Linux/macOS): `config.toml`, `cache/`, `codex.sqlite`, `snapshots/`, `exports/`.
- Logging, HTTP client with a descriptive User-Agent, on-disk caching with ETag/`Cache-Control` respect, retry with backoff.
- CI: ruff, mypy (loose), pytest on Windows + Linux.
- `CONTRIBUTING.md`, `LICENSE` (**DG0**: choose a license; MIT proposed).

**Acceptance**
- Fresh clone → `uv sync` → `uv run openwarframe --help` works on Windows and Linux.
- CI green on a trivial test.

**Risks.** None technical. The license choice blocks public contributions.

**Size.** S (2–3 days).

---

## M1. Codex: the normalized game database

**Goal.** One local SQLite database that answers "what is this item, what is it made
of, and where can I get it" for every item in the game, keyed by `uniqueName`.

**Deliverables**
- Source: official Public Export (16 manifests). Handles the LZMA-alone index quirk (raw LZMA1 decode after the 13-byte header; verified in `spikes/poc_public_export.py`).
- Source: warframe-public-export-plus (branch `senpai`) for the manifests DE does not publish: relics, enemies, mission types, rewards, vendors, syndicates, challenges, Nightwave, bounties, intrinsics, focus.
- Source: WFCD warframe-drop-data (`all.json` + `info.json`) parsed from DE's official drop table page.
- Source: warframe.market v2 item list (`gameRef` → slug) for later pricing.
- Normalizer into tables: `item`, `recipe`, `recipe_ingredient`, `relic`, `relic_reward`, `node`, `node_reward` (by rotation), `enemy_drop`, `vendor_offer`, `syndicate_offer`, `bounty_reward`, `challenge`, `market_item`, `source_version`.
- Item graph queries: full crafting tree with totals (e.g. a Prime frame → parts → resources), reverse lookup ("what uses Orokin Cells").
- `openwarframe codex update` with change detection (hash in Public Export file names; `info.json` hash for drops).
- Image manifest (ExportManifest) mapped to CDN URLs for the dashboard.

**Acceptance**
- `codex update` completes from a cold cache in under two minutes on a normal connection.
- For 50 hand-picked items (prime parts, resources, mods, arcanes, Necramech parts, Railjack parts) the ranked source list matches the wiki's.
- Round-trip tests: every recipe ingredient resolves to a known item; every drop entry resolves to a node, relic, enemy or vendor; unresolved entries are reported, not dropped silently.

**Risks**
- Public Export JSON occasionally contains raw control characters; keep the cleaning step.
- Drop data lags hotfixes; surface `info.json` timestamps in the UI.
- warframe-public-export-plus is a community project with no stated update cadence; pin a commit and alert on upstream changes.

**Size.** M (1 week).

---

## M2. Account snapshot, Tier 1: public profile

**Goal.** Build a complete picture of progression from the official public profile
endpoint, with zero risk to the account.

**Deliverables**
- Account ID capture: paste it, or a guided helper that explains how to copy the `gid` cookie from warframe.com while logged in. Platform selector (PC, PlayStation, Xbox, Switch, iOS, Android: each has its own host).
- Fetcher for `getProfileViewingData.php?playerId=...` honoring `Cache-Control` (about 10 minutes).
- Parser for `Results[0]` and `Stats` (reference parsers: WFCD `profile-parser`, SpaceNinjaServer's controller which documents the fields).
- Derived views: mastery rank and XP to next rank (FrameHub's formula including mission, junction and intrinsics XP), mastered / owned-but-unmastered / never-owned per category, star chart completion per node and per planet (including Steel Path), syndicate ranks and standing, intrinsics, achievements (`ChallengeProgress`), current loadout, lifetime stats (kills, missions by type, time played, weapon usage).
- Append-only `snapshots/` store (one JSON per sync) and `openwarframe diff` between any two.

**Acceptance**
- `openwarframe sync --profile` produces a snapshot and prints a one-screen summary.
- Mastery rank computed from XP matches the rank shown in the profile.
- Diff after a play session lists newly mastered items and newly completed nodes.

**Risks**
- The endpoint is undocumented and may change; keep the raw JSON in the snapshot so parsers can be re-run.
- Account ID discovery is the main onboarding friction. Options from easiest to most automatic: paste; guided cookie copy; optional read of the browser cookie with explicit consent.

**Size.** M (1 week).

---

## M3. Account snapshot, Tier 2: full inventory adapters

**Goal.** Add everything the profile cannot show: resources and their counts, owned
blueprints and components, foundry queue (with ready-at times), relics (with
refinement), mods and their ranks, arcanes, quests, credits, platinum, endo,
boosters, Helminth, Incarnon evolution, Lich/Sister state.

**Deliverables**
- `InventorySource` adapter interface with `fetch() -> RawInventory`, `coverage()` (which sections are present) and `freshness()`.
- Adapter 1: **JSON file import**. Accepts the game's inventory JSON shape (field reference: SpaceNinjaServer `IInventoryClient`). Drag-and-drop or path.
- Adapter 2: **AlecaFrame hand-off**, only if AlecaFrame offers a readable export. Today its cached data (`lastData.dat`) is encrypted and the keys are held by a third party, so this is a research task, not a promise.
- **DG1 (before any further adapter):** decide whether to add a direct login adapter (the mobile-app protocol, credentials entered interactively and never stored, session ends when the game logs in). It is the most complete source and also the one DE's "at your own risk" policy applies to most clearly. Off by default, behind an explicit flag with a warning, or not built at all. Owner's call; see `docs/ACCOUNT_DATA_ACCESS.md`.
- Normalizer: inventory JSON → the same snapshot model as M2, merged (profile fills progression, inventory fills possessions).
- Coverage report: "this snapshot has profile + inventory; missing: nothing" or "profile only; resources, blueprints, relics unavailable".

**Acceptance**
- A full inventory JSON imports in under five seconds and every known section maps to a table; unknown sections are kept raw and listed.
- Foundry: in-progress items show time remaining; ready-to-claim items are flagged.
- Relics: counts by tier, refinement and vaulted status.

**Risks**
- No stable public source for inventory. The adapter interface keeps the rest of the tool working with whatever is available.
- Inventory JSON is large (megabytes); stream-parse or load once and index.

**Size.** M–L (1–2 weeks plus the DG1 decision).

---

## M4. Exports v1: JSON, SQLite, CSV, Excel, LLM brief

**Goal.** Get the data out in every shape that other tools eat.

**Deliverables**
- Canonical `account.json` (versioned schema, published as JSON Schema in `docs/schema/`).
- `account.sqlite` with the snapshot tables, and a CSV bundle (one file per table).
- Excel workbook via `openpyxl`: sheets **Summary**, **Mastery**, **Arsenal**, **Foundry & Blueprints**, **Farm Plan**, **Relics**, **Mods & Arcanes**, **Resources**, **Star Chart**, **Syndicates**, **Achievements**, **Sources** (data timestamps). Frozen headers, autofilter, column widths, number formats, conditional formatting (owned / missing / ready), hyperlinks to the wiki.
- LLM brief: `account-brief.md` with YAML front matter plus `account-brief.json`. Two budgets: compact (about 8k tokens) and full (about 40k). Sections: identity (optional), progression, gaps ranked, foundry state, farm options, active world events relevant to the account, open goals. Written so a model can plan without any other context.
- `openwarframe export --format xlsx,json,sqlite,csv,llm`.

**Acceptance**
- Workbook opens in Excel and LibreOffice without repair prompts; golden-file tests on a fixture account.
- `account.json` validates against the schema; a round-trip import reproduces the snapshot.
- A pasted compact brief lets a model answer "what should I farm tonight" correctly for the fixture account.

**Size.** M (1.5 weeks).

---

## M5. Reports: dashboard, PDF, DOCX

**Goal.** The "visually pleasing" deliverable: a dashboard you want to look at and a
report you can hand to someone.

**Deliverables**
- Single-file HTML dashboard (inline CSS, no external calls, works offline), Warframe-inspired visual identity (see mockups). Sections: hero with MR ring and account age, arsenal grid by category with mastered/owned/missing states, foundry backlog cards, star chart heat strip per planet, syndicate bars, relic shelf, resource tiles, achievements wall, "next steps" panel.
- Share mode: strips account ID, display name and clan unless opted in.
- PDF: print stylesheet + headless Chromium (Playwright) so the PDF is the dashboard, not a second design. Cover page, table of contents, page numbers.
- DOCX via `python-docx` with the same sections, styled headings, tables and embedded images; suitable for editing.
- Image cache for item icons (from the Public Export manifest) with a text fallback.

**Acceptance**
- Dashboard renders in Chrome, Edge, Firefox and on a phone width without horizontal scroll.
- PDF under 15 MB for a maxed account; DOCX opens in Word and Google Docs.
- A screenshot test per section against the fixture account.

**Risks.** Playwright adds a browser download (about 150 MB); offer `--pdf-engine=weasyprint` as a lighter alternative (**DG2**).

**Size.** M (1.5 weeks).

---

## M6. Farm intelligence: "where do I get it, and what is fastest"

**Goal.** For every missing part, blueprint or resource, a ranked list of ways to get
it, tuned to this account.

**Deliverables**
- Gap analysis: items not mastered, items owned-but-unbuilt, blueprints missing components, components missing resources (full tree with totals, net of what you own).
- Source ranking per gap: relics (and which of them you already own, by refinement), mission nodes with rotation and chance, enemy drops, bounties, vendors and standing cost, syndicate offerings, Baro history, market median price. Ranked by expected time to obtain with transparent assumptions (editable in config).
- Resource farming routes: the drop tables do not describe resource-per-minute, so these come from the curated knowledge base (`kb/routes/*.yaml`) with sources cited.
- "Shortcuts you already have": you own a relic that drops it; you can buy it for standing you already have; it is cheap on the market right now.
- Mastery-aware filtering (hide items above your MR unless asked).

**Acceptance**
- For the fixture account, the top recommendation for 30 sampled gaps is one a veteran would agree with (reviewed by hand).
- Every recommendation shows its reasoning and its data source timestamp.

**Size.** M (1.5 weeks).

---

## M7. Live world state and the planner

**Goal.** Turn "what is happening right now" into "what *you* should do right now".

**Deliverables**
- World state source: official `worldState.php` (42 sections verified on 2026-10-16) parsed with our own models; node and mission names resolved through the codex (`ExportRegions`). Sections used first: fissures (`ActiveMissions`, including Steel Path and Void Storms), alerts, invasions, sorties, Archon Hunt (`LiteSorties`), Nightwave (`SeasonInfo`), Baro (`VoidTraders`), syndicate missions and bounties, events and goals, Prime Resurgence (`PrimeVaultTraders`), daily deals, open world cycles.
- Matching engine: active fissure tier × relics you own × parts you are missing → "run this fissure with this relic"; invasion rewards you lack; alert rewards you lack; Baro items you lack and can afford; Nightwave challenges that overlap your goals; bounties whose reward pools contain your gaps.
- Affinity plan: frames, weapons and companions you own but have not leveled, grouped by what you can equip together, matched with affinity-friendly nodes and current boosters (from inventory) and double-affinity events (from world state).
- Daily / weekly checklist generated from the snapshot: sortie, Archon Hunt, Nightwave weeklies, syndicate standing caps, Baro visit, Circuit, Deep Archimedea, Calendar tasks, foundry claims due.
- Optional live tail of `EE.log` (read-only, never uploaded): current mission selected, squad state, alert selected, login/logout; used only to annotate "you are here" in the planner. Verified today that the log carries no API tokens.
- `openwarframe plan` prints the plan; the dashboard gets a live panel; export formats get a "Right now" sheet/section.

**Acceptance**
- With the fixture account and a recorded world state, the planner produces at least ten explained recommendations, each linking the gap, the source and the event expiry.
- World state refresh respects cache headers; a failed refresh falls back to the last good state with its age shown.

**Risks.** World state sections change without notice; keep raw JSON, tolerate unknown fields. `EE.log` line formats are undocumented; treat parsing as best-effort.

**Size.** M–L (1.5–2 weeks).

---

## M8. Goals, guides and the knowledge base ("the path to MR 30")

**Goal.** Hand-holding that adapts to the account: what stage you are at, what you
have not unlocked, what you probably never knew existed.

**Deliverables**
- Account stage detection from quests completed, MR, nodes, systems unlocked (early game / star chart / mid / late / endgame / completionist).
- Goal engine: predefined goals (reach MR N, complete the star chart, finish all quests, unlock Helminth, Steel Path, Incarnons, Archon shards, Arcanes, Focus schools, Railjack intrinsics, Necramech, Duviri, 1999 content...) with prerequisites, steps and "where to go", each step resolvable against the snapshot so progress is automatic. Custom goals ("build Wisp Prime") expand into the crafting tree plus farm plan.
- Knowledge base in `kb/` (YAML, schema in `docs/KNOWLEDGE_BASE.md`): systems explainers, hidden and overlooked mechanics, achievements worth chasing (`ExportChallenges` vs `ChallengeProgress`), economy tips, quality-of-life settings. Every entry has an `applies_if` rule so it only shows when relevant, and cited sources.
- First 60 reviewed entries, prioritised by "things long-time players commonly miss".
- Guide section in dashboard and report; `openwarframe guide` in the CLI.

**Acceptance**
- For three fixture accounts at different stages, the guide shows different, relevant entries and no irrelevant ones.
- Every KB entry has a source and a last-verified date; a CI check fails on entries older than 12 months without re-verification.

**Risks.** Content work never ends; time-box the first pass and make contribution easy.

**Size.** L (2 weeks for the engine and first pass; ongoing for content).

---

## M9. Share, compare and package

**Goal.** Make it easy to show your account, compare with friends, and install without Python.

**Deliverables**
- Share mode export (anonymized by default) and a static share page; optional one-command publish to GitHub Pages or a gist.
- Import someone else's shared snapshot for side-by-side comparison (who has what, who can help with what).
- Packaging: `pipx install openwarframe`, Windows single-file executable (PyInstaller), auto-update check for the codex.
- Plugin points for new sources and exporters documented.

**Acceptance.** A non-developer installs the Windows build, pastes an account ID, and gets a dashboard in under five minutes.

**Size.** M (1.5 weeks).

---

## Cross-cutting

- **Privacy.** Account data stays on disk, in the user's profile directory. No telemetry. Share mode strips identifiers. `EE.log` is read, never copied anywhere.
- **Etiquette.** Descriptive User-Agent, cache respect, no polling faster than the data changes, no scraping of pages that offer a data file.
- **Testing.** Fixture accounts (synthetic, checked into `tests/fixtures/`), golden exports, recorded world states.
- **Docs.** Each milestone updates `docs/` and the README status line.

## Suggested order and rough calendar

| Order | Milestone | Size | Cumulative |
| --- | --- | --- | --- |
| 1 | M0 Foundation | S | week 1 |
| 2 | M1 Codex | M | week 2 |
| 3 | M2 Profile snapshot | M | week 3 |
| 4 | M4 Exports v1 (JSON, SQLite, Excel, LLM brief) | M | week 4–5 |
| 5 | M5 Reports (dashboard, PDF, DOCX) | M | week 6–7 |
| 6 | M3 Inventory adapters (+ DG1) | M–L | week 8–9 |
| 7 | M6 Farm intelligence | M | week 10 |
| 8 | M7 Live planner | M–L | week 11–12 |
| 9 | M8 Goals & guides | L | week 13–14, then ongoing |
| 10 | M9 Share & package | M | week 15 |

M3 is placed after the first exports on purpose: profile data alone already produces
a useful dashboard, and the Tier 2 decision deserves a working product to judge
against.
