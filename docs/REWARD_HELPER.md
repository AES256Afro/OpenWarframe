# Relic reward helper (milestone 0.7): backend status

The helper only reads `%LOCALAPPDATA%\Warframe\EE.log` and pixels from the screen. It never
reads or writes game memory and never sends input to the game.

Code: `src/openwarframe/live/`

| File | What it does |
| --- | --- |
| `eelog.py` | Follows EE.log (re-opens per poll, survives the file being recreated at launch, partial lines, bad bytes) and emits events: `login`, `mission_loaded` (node, missionType, faction), `reward_reported`, `reward_screen_opened`, `reward_screen_closed`, `log_reset` |
| `ocr.py` | Finds the `Warframe.x64.exe` window, captures its client area (mss), crops one name box per reward using WFInfo's geometry, reads it with `Windows.Media.Ocr` (winrt) |
| `match.py` | Fuzzy-matches OCR text to relic reward names from the codex (difflib) and ranks: needed for an item you haven't mastered, then vaulted, then platinum (from a price dict you pass in), then ducats |
| `reward.py` | Screenshot -> OCR -> match -> ranking, and saving recordings |
| `synthetic.py` | Draws a fake reward screen for tests |

## Commands

```powershell
openwarframe live watch                       # print events as they happen
openwarframe live record                      # on each reward screen: save screenshot + OCR + log tail
openwarframe live capture --delay 3           # manual screenshot + OCR now
openwarframe live ocr shot.png [--players 4] [--prices prices.json] [--save-crops dir]
openwarframe live sample-image fake.png --size 2560x1440
```

Recordings go to `<data dir>\live\recordings\<timestamp>\` (`screenshot.png`,
`result.json`, `log.txt`). `record` also appends every reward/relic/fissure-looking log
line to `<data dir>\live\candidates.log`.

## What is verified

- **Log triggers: checked against one real run.** The owner's EE.log of 2026-11-24 has one
  4-player Lith fissure (Defense). The sequence is documented in `eelog.py` and copied
  into `tests/test_live.py`. It shows that two of WFInfo's markers are wrong for us:
  "Pause countdown done" comes about 0.5 s *before* the names are drawn, and "Relic timer
  closed" fires for every countdown. We open on `ProjectionRewardChoice.lua: Got rewards`
  and close on `Relic reward screen shut down` (or `MatchingService::EndSession`). The
  relic *selection* screen between Defense rounds is correctly ignored.
- **`reward_reported`.** While the screen loads the log names one player's reward by item
  path (`VoidProjections: <id> gets reward /Lotus/StoreItems/...`). In the recorded run
  only one of four players was named, so this is ground truth for one slot, not a
  replacement for OCR. `record` stores these paths in `result.json` for comparison.
- **Crop + OCR + match on synthetic screens**: 1 to 4 rewards at 1280x720, 1920x1080,
  2560x1440 and 3440x1440, UI scale 1.0 and 0.8, all read and matched exactly, and the
  squad size is detected.
- **Window capture** works on the owner's machine (windowed, 1920x1009 client area).

## What still needs a real fissure recording

Run `openwarframe live record` during a few fissure missions, then share the folders.

1. **Crop geometry on the real screen.** The boxes come from WFInfo's 1920x1080
   measurements and have only been checked on synthetic images. Needed: recordings at
   1080p and 1440p, and in the owner's windowed size (1920x1009: the helper scales by
   height there, as WFInfo does). Target from PLAN.md: 95 % name accuracy.
2. **Real text rendering.** Game fonts, theme colours, glow and the item art behind the
   names may need a different `ocr.prepare` (threshold, colour filter by UI theme,
   larger upscale). WFInfo filters by theme colour; we only greyscale, invert and
   stretch contrast so far.
3. **Solo and 2/3-player runs**, to confirm the centring rule and the squad-size
   detection (`RewardCatalog.pick_layout`), and that solo runs log the same lines.
4. **UI scale.** The owner's EE.cfg has no `Flash.FlashDrawScale` key (WFInfo's source),
   so the helper assumes 1.0. A run with a non-default HUD/menu scale would show which
   key the game uses now. `--ui-scale` overrides it meanwhile.
5. **Timing.** `record` waits 1.5 s after "Got rewards" (the selection countdown is 15 s).
   Check names are fully drawn by then; PLAN.md wants the pick within 3 s.
6. **Exclusive fullscreen.** Screen capture may come back black; borderless/windowed work.
7. **Two-line names, "2 X Forma Blueprint" style counts, and non-English clients**
   (`--lang`, plus CJK line height, which `ocr.name_band(cjk=True)` supports but nothing
   selects yet).

## Not done here

The app UI and the always-on-top window (other 0.7 rows) and platinum prices: `rank`
accepts a price dict keyed by name, market slug or uniqueName, but nothing fetches prices
yet.
