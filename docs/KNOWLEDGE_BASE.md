# Knowledge base (`kb/`)

The knowledge base holds what the APIs cannot tell you: how systems work, what to do
in which order, where farming is actually fast, and the things long-time players
commonly never discover. Entries are YAML files in `kb/`, reviewed like code.

## Entry schema

```yaml
id: helminth-unlock                      # stable, kebab-case
title: Unlock the Helminth
category: systems                        # systems | mastery | quests | farming | economy | achievements | qol | hidden
stage: mid                               # early | starchart | mid | late | endgame | any
one_liner: Subsume frames to move abilities between them; also removes the need to keep duplicate frames.
why_it_matters: >
  Helminth is the single biggest build-flexibility unlock in the game and most
  players postpone it because the segment costs Entrati standing at Rank 3.
prerequisites:
  - quest:HeartOfDeimos
  - syndicate:Entrati:3
steps:
  - text: Reach Entrati rank 3 (Associate) via Cambion Drift bounties.
    where: { node: SolNode229, hint: "Necralisk, Deimos" }
    done_if: "snapshot.affiliations['EntratiSyndicate'].title >= 3"
  - text: Buy the Helminth Segment blueprint from Son.
    done_if: "'/Lotus/Types/Recipes/...HelminthSegment' in snapshot.recipes"
  - text: Build it (24h) and install it in the Orbiter's Helminth room.
    done_if: "snapshot.inventory.InfestedFoundry.unlocked"
applies_if: "snapshot.mastery_rank >= 8 and not snapshot.inventory.InfestedFoundry.unlocked"
sources:
  - { title: "Helminth - WARFRAME Wiki", url: "https://wiki.warframe.com/w/Helminth", license: "CC BY-SA" }
last_verified: 2026-10-16
```

Rules:

- `applies_if` and `done_if` use a small, safe expression language over the snapshot
  (no arbitrary Python). If a referenced section is missing from the snapshot the entry
  is shown with a "needs inventory data" badge instead of being hidden.
- Every entry needs at least one source and a `last_verified` date. CI flags entries
  older than 12 months.
- Facts from the wiki are paraphrased, attributed and linked; no verbatim copying.
- Farming routes (`kb/routes/`) carry a `measured` block (resource per minute, sample
  size, date, mode) so numbers are honest.

## Categories and first-pass content

| Category | Examples of entries to write first |
| --- | --- |
| systems | Helminth, Steel Path and incursions, Incarnon adapters and the Circuit, Archon shards and Tauforged, Arcanes and the Arcane dissolve/upgrade loop, Focus schools and the lens economy, Railjack intrinsics, Necramech, Kuva Lich / Sister / Technocyte Coda mechanics, Duviri decrees, Calendar (1999), Nightwave cred offerings |
| mastery | What gives mastery and what does not; founder/prime "same item" rules; junctions and star chart XP; intrinsics XP; the 30 → Legendary ranks; Mastery tests practice mode in Simaris' relay room |
| quests | Recommended order, quests with hidden rewards, quest-gated vendors, replayable quests |
| farming | Resource routes (Orokin Cells, Argon, Nitain, Toroids, Gyromag...), relic cracking strategy and refinement math, rotation logic (AABC), endless vs capture efficiency, syndicate medallion routes |
| economy | Baro checklist by value, Ducat efficiency, Prime junk selling, standing caps and medallions, when to buy vs farm, credit farms (Index, Profit-Taker), endo (Arbitrations, Vodyanoi, Ayatan) |
| achievements | Overlooked in-game achievements (`ChallengeProgress` vs `ExportChallenges`), profile titles and accolades, Simaris scans, codex completion |
| qol | Settings worth changing, Orbiter segments, Dojo research, loadout slots, chat filters, Simaris target, daily Tribute milestones |
| hidden | Rooms, vendors and systems most players never find (the Leverian, Fortuna's Ticker, Zariman Hollow... each with "how to detect you have not done it") |

## Process

1. Open an issue with the `kb` label naming the entry and the sources.
2. Write the YAML; run `openwarframe kb lint` (schema, rules, dates).
3. Check against two fixture accounts: it should appear for one and not the other.
4. Review by a second person (or a second pass a day later while solo).
