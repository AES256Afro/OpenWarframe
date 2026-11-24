# OpenWarframe plan: 0.3 to 1.0

Written 2026-11-24, after 0.2.0 (desktop app) and the game-session inventory reader.
The long-form milestone history stays in `ROADMAP.md`; this file is the working plan.

## Design principle: built for focus

Many players, the owner included, play with ADHD or autism in the mix. Every screen
follows these rules:

1. **One next action.** Each view opens with a single "Do this now" card: what, where,
   why, and how long. Everything else is one click deeper.
2. **Always say why.** Every suggestion names the reason ("drops a part you need",
   "vaulted, worth 45 platinum") so nothing feels arbitrary.
3. **Small, finishable steps.** Checklists with ticks, progress bars that move, and a
   clear "done for today" state.
4. **Escape hatches.** Every suggestion has "I'm bored" and "too hard" alternatives,
   so switching activity never means starting over.
5. **Calm by default.** Same layout every time, no surprise pop-ups, reduced motion
   respected, sounds off unless turned on, larger-text option.
6. **Easy to resume.** The app remembers the last view, filters and goal.

## Milestones

Effort: S = hours, M = a day or two, L = several days. Each item lists how we know it is done.

### 0.3 "Ready to share"

| Item | Effort | Done when |
| --- | --- | --- |
| One-click installer script (`install.ps1`): installs uv, OpenWarframe and the desktop icon | S | A fresh Windows account goes from download to running app with one command |
| Standalone `OpenWarframe.exe` built by GitHub Actions on every release tag, with SHA-256 checksums | M | The release page has a zip; it runs on a machine without Python. Unsigned, so the README explains the SmartScreen "More info, Run anyway" step and how to verify the checksum |
| Sell list from the real inventory: duplicates and parts of mastered Primes, ducats vs today's platinum (built) | S | Matches the in-game ducat kiosk counts for 10 spot-checked parts |
| Foundry tab: queue with time left and "ready to claim" (built) | S | Shows the 8 items in the owner's Foundry with correct ready times |
| Resource shortfalls: what owned blueprints need vs what you have (built) | S | Every short resource links to its best farm |
| Mods and arcanes tab: duplicates, unranked rares, endo and ducat-free sell candidates (built) | S | Counts match the in-game mod screen for 5 spot checks |
| Auto-refresh: grab the inventory on open when the game runs (after the one-time consent) | S | Opening the app during play needs no click |
| Release 0.3.0: README "how it works", real screenshots, repo description and topics | S | Release page and repo front page explain what it is, how to install and the risks |

### 0.4 "What to farm"

| Item | Effort | Done when |
| --- | --- | --- |
| Do these missions: nodes ranked by the drop chance of relics and parts you need, filterable by mission type (built) | M | Top 10 for the owner's account agree with a veteran's judgement |
| To finish this: pick an item and see each missing piece with its best source (built) | M | Works for Primes, vendor items, bounty items and Necramechs |
| Relics to crack: owned relics scored by vaulted gear, parts you need and expected platinum at your refinement | M | Score explained per relic; sorting by it matches the price check |
| Popular farms: curated, sourced list of well-known farms (Hepit, Ukko, Apollo...) in `kb/routes/` (built) | S | Every entry has a source and a last-verified date |
| One part away: Prime sets and blueprints missing exactly one piece (built) | S | Correct for the owner's inventory |
| Road to 30 inside the app, using owned-but-unmastered gear | M | Plan totals match `openwarframe guide mastery` |

### 0.4b "Earnings and costs"

| Item | Effort | Done when |
| --- | --- | --- |
| What you can make: spare Prime parts, relics, mods and arcanes valued in ducats and platinum, with "sell to Baro" vs "sell on the market" per item (built) | M | Totals match the Sell list, relic and mod price checks |
| Cost to finish: for any goal, credits, resources, build time and the platinum to buy missing parts instead of farming them (built) | M | Shown on every "To finish this" card |
| Next content from your profile: "done with relics? do this next", ranked by what your account is missing and what pays | M | Feeds the Now card in 0.6 |

### 0.5 "Live"

| Item | Effort | Done when |
| --- | --- | --- |
| World state panel: fissures, Steel Path fissures, void storms, Baro, invasions (built; Arbitration still to do) | M | Refreshes on its own and shows time left |
| Fissure matching: "Lith fissure on Tessera, 38 min left, you own 4 Lith C7 with a part you need" (built) | M | Every active fissure is checked against owned relics |
| You are here: current mission from `EE.log` (node, mission type, faction) (built) | S | Shows the right node within seconds of loading in |
| Refresh after missions: re-grab the inventory when you return to the Orbiter | S | Counts update without a click |

### 0.6 "Focus mode"

| Item | Effort | Done when |
| --- | --- | --- |
| Now card on every view: one next action with where, why and time (built) | M | Never shows more than one primary button |
| Session planner: "I have 30 minutes" builds a short checklist from live state and goals (built) | M | Plans fit the time given |
| Daily and weekly checklist: sortie, Archon Hunt, Nightwave, standing caps, Baro, Foundry claims (built) | M | Resets at the game's reset times |
| Goals: "build Wisp Prime", "reach MR 24", tracked automatically (built; system unlocks like Helminth come with the knowledge base) | M | Progress moves after each inventory refresh |
| Comfort settings: larger text, reduced motion, high contrast, sounds off (built) | S | Settings persist |

### 0.7 "Relic reward helper"

| Item | Effort | Done when |
| --- | --- | --- |
| Detect the reward screen from `EE.log` (built, checked on one real run) | M | Verified on recorded fissure runs, solo and squad |
| Read the four reward names with Windows' built-in OCR from a screenshot of the game window (built; needs real recordings to reach 95 %) | L | 95 % name accuracy at 1080p and 1440p on recorded runs |
| Rank the picks: parts you need, vaulted, platinum, ducats; show in the app and an optional small always-on-top window (built) | M | Pick shown within 3 seconds of the screen appearing |

The helper only reads the log and the screen, never game memory. It needs one or two
recorded fissure runs from the owner to tune.

### 0.8 and later

| Item | Effort |
| --- | --- |
| Goals and guides knowledge base (Helminth, Steel Path, Incarnons, hidden content) | L |
| Compare with a friend's shared export | M |
| Update check in the app | S |
| Code signing, if the project ever pays for a certificate | S once bought |

## Risks

- **Antivirus and SmartScreen.** An unsigned exe that reads another program's memory is a
  classic false-positive pattern. Mitigations: build in GitHub Actions from public source,
  publish checksums, keep the installer script as the recommended path, and submit
  false positives to Microsoft.
- **Game updates.** The session pattern, log lines and screen layout can change with any
  update. Every reader fails with a clear message and keeps the last good data.
- **DE policy.** The session reader is opt-in with the warning shown before first use. The
  reward helper reads only the log and the screen.

## How the work is split

Independent pieces run in their own sessions and branches so they do not collide:

- **Packaging:** installer script, PyInstaller build, release workflow (`packaging/`,
  `.github/workflows/release.yml`).
- **Reward helper backend:** log tailer, reward-screen detection, OCR capture
  (`openwarframe/live/`), with a debug command for recording runs.
- **Main session:** data features and the app UI (`openwarframe/app/`), then the
  release with screenshots.
