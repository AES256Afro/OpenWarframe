# Changelog

What changed in each release, newest first. Releases are on
[GitHub](https://github.com/AES256Afro/OpenWarframe/releases).

## Unreleased

- **Melee builds.** Open a melee weapon and click **Suggest a build**. It uses the same damage,
  armor, shield and status model as guns, plus the combo multiplier (Blood Rush, Weeping Wounds,
  the Gladiator set), Condition Overload (counting your weapon's statuses and any you say other
  sources keep on the target) and attack speed. Pick the combo you fight at (none, 6x, 12x).
  Against armored Steel Path enemies Slash bleeds carry most of the damage, since they ignore armor.

## 0.20.0

- **Umbral set bonus.** Umbral Intensify, Vitality and Fiber now count with their set bonus
  (Intensify x1.25 / x1.75 with 2 / 3 pieces; Vitality and Fiber x1.30 / x1.80), so builds pick
  the full set where it pays off, and the mod list shows the boosted value.
- **Arcanes in Warframe builds.** Two arcane slots. Molt Augmented, Arcane Blessing, Arcane
  Bellicose and Arcane Intention are scored from their in-game text; other arcanes trigger on
  something, so pick them in the arcane selectors and the build fills the rest.

## 0.19.0

- **Archon Shards in Warframe builds.** Choose None, 5 shards or 5 Tauforged: the build picks
  Crimson (Ability Strength, Duration) and Azure (Health, Shields, Armor) shard stats alongside
  the mods, using the wiki's stacking rules (Crimson adds to the mods' bonuses; Azure is added
  after them). With your inventory it sticks to the loose shards you own.
- **Augment mods.** The build panel lists the augments for the abilities you use, with what they
  do and whether you own them. Tick the ones you want; the rest of the build is fitted around
  them.

## 0.18.0

- **Warframe builds fill the Aura and Exilus slots.** The Exilus slot takes one exilus-capable mod
  (the Drift mods and the like). The aura is picked for what it does for your own frame (Physique,
  Stand United) or else for the capacity it adds (double its drain with a matching polarity), and
  the build now fits that extra capacity.
- **Fix:** Umbral Fiber and Steel Fiber are no longer suggested together (variants of one mod).

## 0.17.0

- **Warframe builds.** Open a Warframe and click **Suggest a build**: the app balances Ability
  Strength, Duration, Range, Efficiency and survivability by how many of the abilities you use
  scale with each stat, then picks the mods (yours, if you like). Which stats each ability uses
  comes from the Warframe Wiki's ability pages, bundled with the app (127 frames). Untick the
  abilities you don't cast and build again. See [docs/BUILDS.md](docs/BUILDS.md).
- **Licensing fix:** the Warframe Wiki is CC BY-NC-SA 3.0, not CC BY-SA, and its terms don't allow
  automated access. The docs and knowledge-base entries now say so, and the app never contacts the
  wiki (see [docs/LEGAL.md](docs/LEGAL.md)).

## 0.16.0

- **Builds count shields.** Builds are now scored by the time to kill one reference enemy:
  shields first, then health. Toxin skips shields, Magnetic raises shield damage (up to x4.25),
  armor doesn't protect shields, and health and shields grow with level (x2.5 more on the Steel
  Path). Corpus are judged on a Corpus Tech, Grineer on a Heavy Gunner, Infested on a Toxic Ancient.
  The build shows the time to kill and the damage per second to shields.

## 0.15.0

- **Builds count armor and status.** Pick Normal missions or the Steel Path (or no armor, or armor
  already stripped by your squad). Builds now count armor and how Corrosive and Heat strip it,
  Viral's extra health damage, Cold's crit bonus and the damage over time from Slash, Heat, Toxin,
  Electricity and Gas, using the wiki's current formulas. Against armored Steel Path enemies this
  picks Viral and Heat builds, as players do. The build shows direct and status damage per second
  and what the enemy ends up with (armor left, Viral and Corrosive stacks).
- **Better search:** builds can now pick two elemental mods at once (Viral needs Cold and Toxin
  together), so combined elements are no longer missed.

## 0.14.0

- **Suggested weapon builds.** Open a primary or secondary gun and click **Suggest a build**: the
  app picks the 8 mods with the most sustained damage against the enemy you choose, worked out
  from the game data and the wiki's current damage formulas (not copied from build sites). With
  an inventory it can stick to your mods at your ranks and names the best mod you're missing. It
  shows the numbers, the Forma it needs and what isn't counted yet (armor, status damage over
  time, Rivens, arcanes). See [docs/BUILDS.md](docs/BUILDS.md).
- **Game data schema 4:** weapon classes and mod compatibility tags for builds. The app updates
  the game data once on start.

## 0.13.0

- **Item names in your language.** Settings > **Item names** shows items, parts and relics in any
  of the 15 game languages across the app, Live, item details and every export. The app's own text
  stays English, and search finds the English names too. `openwarframe export --names <lang>` does
  the same from the command line (default: the app's setting).
- **Excel summary** and a few CLI lines use " · " between facts instead of a spaced hyphen.

## 0.12.0

- **Reward helper in every game language.** Pick your game client's language in the Reward helper
  view (15 languages). OpenWarframe downloads DE's item names for it once (about 1.4 MB, saved in
  the data folder) and reads reward screens in that language; the pick still shows the English
  name. Matching now keeps letters of every script and ignores accents OCR tends to drop. Japanese,
  Korean and Chinese use the taller name box. The live CLI follows the same setting. See
  [docs/I18N.md](docs/I18N.md).

## 0.11.0

- **Docs and app text.** No em or en dashes anywhere (a test keeps them out); a few app strings
  are plainer ("Remove goal", "Session done.").
- **Reward helper: read now.** A system-wide key (Windows, default Ctrl+Alt+F9, changeable or
  off) reads the reward screen on demand, without waiting for the game log. A **Read the screen
  now** button does the same in the Reward helper view and the pop-out, on Windows and macOS.

## 0.10.0

- **Update from inside the app.** When a new version is out, the sidebar shows **Update to x.y.z
  now**. One click downloads it, checks it against the release's SHA-256 list, installs it and
  reopens OpenWarframe. With the Setup .exe it runs the new installer silently (no admin prompt:
  it installs per user); with the Windows zip it swaps the files in the folder you unpacked it to;
  on a Mac it replaces OpenWarframe.app. Copies run from source still get the install command.
  This works from 0.10.0 onward: updating to 0.10.0 itself is the last manual update.
- **Internal.** The app page's style and script are split by area into `app/static/page/`; the
  server stitches them back into one page, so nothing changes for players.

## 0.9.0

- **Live: This week.** The Archon Hunt (which Archon, its three missions and the shard colour),
  the Circuit's Warframe and Incarnon Genesis picks (flagged when you own the weapon or its Prime)
  and how much syndicate standing you can still earn today.
- **Live: Varzia.** Prime Resurgence stock with Aya and Regal Aya prices; Prime gear you haven't
  mastered and relics holding parts you need come first. The Live header says how many there are.
- **Helminth.** With an inventory that has Helminth data, Focus suggests feeding a mastered base
  Warframe whose ability you haven't subsumed yet (never a Prime or Umbra).
- **Circuit pick on Focus.** When this week's Steel Path Circuit offers an Incarnon Genesis for a
  weapon you own, Focus suggests taking it.
- **Linux.** The app finds the game log in Steam's Proton prefix (every Steam library, Flatpak
  Steam too), Lutris and Wine, so "you are here" works. The README says what Linux supports.
- **Docs.** A legal checklist ([docs/LEGAL.md](docs/LEGAL.md)), an accessibility statement and
  checklist ([docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)) and the plan for non-English game
  clients ([docs/I18N.md](docs/I18N.md)). The app footer carries the fan-project notice.
- **Tests.** Every button and field on the page must have a name a screen reader can read.

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
