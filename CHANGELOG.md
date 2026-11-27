# Changelog

What changed in each release, newest first. Releases are on
[GitHub](https://github.com/AES256Afro/OpenWarframe/releases).

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
