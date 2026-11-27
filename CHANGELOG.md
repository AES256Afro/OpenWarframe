# Changelog

What changed in each release, newest first. Releases are on
[GitHub](https://github.com/AES256Afro/OpenWarframe/releases).

## Unreleased

- **Live: This week.** The Archon Hunt (which Archon, its three missions and the shard colour),
  the Circuit's Warframe and Incarnon Genesis picks (flagged when you own the weapon or its Prime)
  and how much syndicate standing you can still earn today.
- **Live: Varzia.** Prime Resurgence stock with Aya and Regal Aya prices; Prime gear you haven't
  mastered and relics holding parts you need come first. The Live header says how many there are.
- **Linux.** The app finds the game log in Steam's Proton prefix (every Steam library, Flatpak
  Steam too), Lutris and Wine, so "you are here" works. The README says what Linux supports.
- **Docs.** A legal checklist ([docs/LEGAL.md](docs/LEGAL.md)), an accessibility statement and
  checklist ([docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)) and the plan for non-English game
  clients ([docs/I18N.md](docs/I18N.md)). The app footer carries the fan-project notice.
- **Tests.** Theme colours are checked against WCAG AA contrast in both themes, and every
  control on the page must have a name.

## 0.8.1

0.8.0 was tagged but never published: its Windows build failed a test. 0.8.1 is the same
release with that fixed.

- **Fix.** On Windows the app could miss a new profile sync until it was restarted, because it
  only looked in the snapshot folder again when the folder's time changed.

- **Trading.** The Sell list has a Best column (Baro or market) and links each part to its
  warframe.market page. Mods and arcanes are priced unranked and relics as Intact, and the
  Earnings totals say they are estimates.
- **Readable names.** Vendors show their in-game names (Fisher Hai-Luk, Nightwave:
  Intermission 10) with Credits, Platinum and Standing costs; finished goals show item names.
- **Live.** Invasions say which side to fight for ("Side with Grineer: 3× Detonite
  Injector"), and the mission score is explained.
- **Getting around.** Overview cards open their view, Back and Forward move between views,
  `/` searches and `?` lists the shortcuts. "Show me" opens the item's Finish card. A narrow
  sidebar for small windows.
- **How to get anything.** Open any item (Warframes, Weapons, All items...) to see where it
  comes from: the relics for its blueprint and each part with Intact and Radiant chances,
  which relics are vaulted or farmable and which you already have, missions, bounties,
  vendors and syndicates, plus what resources it needs. Items no drop table records get a
  plain answer: Kuva Lich, Sister of Parvos, Technocyte Coda, Clan Dojo research, or the
  Market. This works for items you have already leveled too.
- **Goals.** Add a goal from any item's details, reorder them, and mark them done.
- **Exports.** Readable workbook headers, Yes/No instead of TRUE/FALSE, no red for "not yet",
  print-ready pages, A4 everywhere with page numbers in Word files, one look across the PDFs,
  and no Google Fonts (exports work offline). The brief, workbook and dashboard say when a
  rank test is ready and show what changed since the last sync; the brief lists your goals
  and standing left today. The compact brief's JSON is about a quarter of the size.
- **CLI.** Export folders use local time, `exports/LATEST.txt` points at the newest one,
  `export --open` opens it and `--remember` keeps your choices. The guide no longer
  overwrites the personal copy when shared, and prints its file paths last.
- **Faster.** The app's data is sent compressed, and the game log, live data and snapshot
  folder are only read again when they change. Old cache files are cleaned up.
- **Safer.** Console profiles are fetched over HTTPS. Windows shortcuts work in folders with
  an apostrophe, and `tasklist` runs from System32.

## 0.7.0

- **Windows installer.** `OpenWarframe-v0.7.0-windows-setup.exe` installs OpenWarframe like a
  normal app: for your user only (no admin prompt) into `%LOCALAPPDATA%\Programs\OpenWarframe`,
  with a Start menu entry, an optional desktop shortcut and an uninstaller under Settings > Apps.
  Running a newer setup updates in place. Uninstalling keeps your data folder. It is not
  code-signed yet, so SmartScreen asks once (More info, then Run anyway). The zip and the
  PowerShell install line are still there.

## 0.6.2

- **Log file.** The app and the CLI write `logs/openwarframe.log` in the data folder (four
  files of at most 1 MB), crashes included, with the game session key masked.
- **`openwarframe backup`** saves goals, settings, profile history and inventory to one zip.
- **Warnings for old advice and upstream changes.** The mastery guide warns when its
  knowledge base hasn't been checked against the game for 180 days; a game-data update warns
  when an upstream source seems to have changed format.
- **Fixed:** turning off "save reward screens" or reward watching no longer switches itself
  back on after a restart; Railjack nodes no longer count as star chart nodes; refreshing an
  unchanged profile clears the "old profile" notice; the pop-out can't reopen off-screen; a
  rate-limited price check stops instead of waiting minutes; an inventory loaded before the
  account is set is kept; a damaged preferences file no longer stops the app.
- **For contributors:** the version lives only in `src/openwarframe/__init__.py`; coverage is
  measured in CI; ARCHITECTURE.md describes the code as it is.

## 0.6.1

- **Steel Path only** on Live → Fissures: shows only Steel Path fissures, and the Right now
  pick and fissure suggestions follow it. Tick-box filters are now remembered across restarts.

## 0.6.0

- The profile is fetched again on open when it is more than a day old.
- The game data's age shows, with an **Update game data** button; notices for old game
  data, an old profile, or blueprints newer than the game data.
- Offline after an update, the app keeps using the game data it has.
- **Export my account** in the app, with Open folder.
- Optional check for new versions (once a day, can be turned off).
- Filters and sort are remembered per view; the session plan survives a reload, with a
  countdown.
- Foundry timers, Live data and market prices stay current in long sessions.
- The pop-out reopens where you put it.

## 0.5.1

- Accessibility: WCAG AA contrast in both themes, text up to 200%, keyboard support for
  rows and the view list, focus kept when the page redraws, a real consent dialog, messages
  announced to screen readers.
- Text that fits your platform: console accounts are never asked to load an inventory, Mac
  players get the Mac steps.
- New players aren't nagged with late-game routines or Steel Path fissures; a glossary.
- Undo for Done and Not now; the pop-out shows how old its pick is.

## 0.5.0

- Each account's snapshots and inventory are kept in their own folder (data moves on first
  start); **Change account** in the app; changing accounts checks the new one first.
- Profile parsing survives changed or null fields; a profile that can't be read is kept.
- The CLI explains failures in one line instead of a traceback.
- Polite networking: warframe.market rate limits, 429 retries, stale copies offline.
- Exports carry on past a failing format.

## 0.4.3

- Reward helper: one misread name no longer drops two rewards from a 4-player screen;
  unsure reads are never the pick; the pick appears before prices; every round of an endless
  mission is read; the watcher no longer blocks game-data updates on Windows.
- Saving reward screens is now opt-in (newest 30 kept).

## 0.4.2

- Correct advice for Prime parts needed twice (the sell list no longer says to sell them),
  dual weapons, Legendary rank thresholds, rank-40 weapons, the star chart in the mastery
  plan, Omnia fissures and mission names. Exports use your saved inventory.

## 0.4.1

- Security: the session key is never logged; a crafted inventory file can't run script in
  the app; the local server refuses other hostnames and can't be framed; safe file writes.
- Releases are built with read-only tokens and published only once both platforms are
  attached; the installer installs pinned dependency versions.
