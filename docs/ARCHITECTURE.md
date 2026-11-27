# Architecture

How OpenWarframe is put together, as of 0.6. Paths are under `src/openwarframe/`.

## The flow

```
   GAME DATA (codex/)                 YOUR ACCOUNT                     LIVE
 Public Export (DE)             public profile (sources/account/    world state (app/live.py)
 public-export-plus (pinned)      profile.py) -> account/            EE.log (live/eelog.py)
 WFCD drop tables                 snapshots, one folder per account  screen + OCR (live/ocr.py)
 warframe.market item list      inventory JSON (inventory/)
        |                          from the game session (Windows,
        v                          opt-in) or a file
   codex.sqlite                          |                               |
        \_______________________________ | ______________________________/
                                         v
                          report/  (one Report: what you have, what is missing,
                                    how to get it, mastery estimate)
                         /            |                \
                   app/            exports/            guide/
           local server + page   json, sqlite, csv,   mastery plan to MR 30
           (the desktop app)     xlsx, dashboard,     (html, pdf, docx)
                                 LLM brief
```

Principles the code keeps to:

1. **Keep the raw.** Snapshots store the profile payload verbatim (`reparse` re-reads it with
   the current codex). A profile that can't be parsed is kept on disk, not lost.
2. **Join on `uniqueName`.** The Public Export, drop data (via `codex/names.py`), the
   profile, the inventory and warframe.market (`gameRef`) all speak it.
3. **One answer per question.** Recipe logic lives in `codex/recipes.py` (`RecipeGraph`):
   ingredient counts, each item's usual recipe, what a part ends up building, how many a
   build needs. "Which relics drop now" is `codex.queries.farmable_relics`. How an item is
   obtained is a list of codes (`MissingItem.ways`, see `report/model.py`), not text matching.
4. **Degrade gracefully.** A profile alone is enough; inventory-only views say what they
   need. Offline, the app keeps the game data it has. Failures become a message, not a crash.

## Packages

| Package | What it does |
| --- | --- |
| `config.py` | `Settings` and the on-disk layout (below); a TOML writer that escapes values; moves pre-0.5 data into per-account folders. |
| `http.py` | `CachedClient`: on-disk cache with ETag/max-age, atomic writes, retries, 429 handling, stale copies when offline. |
| `fsutil.py`, `logsafe.py`, `logs.py` | Atomic writes; masking the session key in logs; the rotating log file and crash capture. |
| `sources/static/` | Public Export (LZMA index), export-plus (fetched at a pinned commit), WFCD drops, warframe.market items and prices. |
| `sources/account/` | `profile.py` (public profile per platform), `session.py` (Windows-only, opt-in read of the game session to download the inventory). |
| `codex/` | `schema.py`, `build.py` (loaders, name resolution, drift warning), `queries.py` (`Codex`: sources, trees), `recipes.py` (`RecipeGraph`), `names.py`. |
| `account/` | `Snapshot` model, null-tolerant `parse.py`, `store.py` (skips damaged files), `sync.py`, `summary.py`. |
| `inventory/` | `parse.py`: the game's inventory JSON (wallet values must be numbers), `unwrap` for tool wrappers. |
| `report/` | `build.py` turns a snapshot (+ inventory) into a `Report`; `model.py` is its pydantic schema, published as `docs/schema/account.schema.json`. |
| `exports/` | One module per format, all rendering the same `Report`; `run.py` runs them and reports per-format failures. |
| `guide/` | The mastery planner (`mastery.py`) over the curated knowledge base in `kb/` (`kb.py`, with staleness checks), and its HTML/PDF/Word output. |
| `app/` | `server.py` (local HTTP server, 127.0.0.1 only, Host/Origin checks, CSP), `data.py` (everything the page shows), `farm.py`, `extras.py`, `live.py`, `rewards.py` (reward watcher thread), `window.py` (WebView2/WKWebView window and pop-out), `static/` (the page). |
| `live/` | Reward helper pieces: `eelog.py` (log events), `ocr.py` (window lookup, capture, OCR), `match.py` (fuzzy names, squad size, ranking), `reward.py`, `synthetic.py` (drawn test screens), `cli.py`. |
| `cli.py` | The Typer CLI; `main()` turns known failures into a one-line message. |

## On disk

```
<data folder>/                     OPENWARFRAME_HOME, or the OS app-data folder
  config.toml                      platform, account id, a few settings
  app-prefs.json                   goals, ticks, comfort settings, remembered filters, session plan
  codex.sqlite                     the game database (rebuilt from sources; safe to delete)
  accounts/<account id>/
    snapshots/<UTC time>.json      profile snapshots (raw + parsed)
    inventory.json                 the loaded inventory
    profile-checked                touched on every profile fetch
  cache/                           HTTP cache
  exports/                         exports and guides
  logs/openwarframe.log            rotating log (session key masked)
  live/recordings/                 saved reward screens, only when turned on (newest 30)
  backups/                         `openwarframe backup` zips
```

## The app

`openwarframe gui` (or `OpenWarframe.exe` / `OpenWarframe.app`) starts `app/server.py` on a
free 127.0.0.1 port and opens the page in its own window, or in a Chrome/Edge app window.
The page (`app/static/index.html`) is plain JavaScript that calls the server's JSON API:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/data` | Everything the page shows (built by `app/data.py`), with `meta.caps` (what works here) and freshness. |
| `GET /api/live`, `/api/reward`, `/api/update` | World state, reward helper status, new-version check. |
| `POST /api/sync`, `/api/account`, `/api/inventory`, `/api/inventory/grab` | Refresh the profile, set or change the account, load an inventory. |
| `POST /api/prefs` | Save goals, ticks and settings (server-owned settings are kept). |
| `POST /api/export`, `/api/open-folder` | Exports from the app. |

## Tests and builds

- `pytest` runs offline on small synthetic databases; tests marked `host` need Chrome or an
  OCR engine. Coverage is measured in CI with a floor (`[tool.coverage.report]`).
- CI builds the frozen app on Windows and macOS for every pull request and smoke-tests it
  (`packaging/smoke_test.py`); releases come from `.github/workflows/release.yml`.
