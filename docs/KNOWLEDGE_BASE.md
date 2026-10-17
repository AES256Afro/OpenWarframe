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

## Mastery guide

`kb/mastery/` drives `openwarframe guide mastery` and the `mastery-plan.html` export.

| File | Holds |
| --- | --- |
| `tests.yaml` | The Mastery Rank tests 24 to 30: objective, tips, and `recommend` frames and companions in order of preference. The planner names the ones the account has leveled, Prime versions first, and falls back to `bring_default`. |
| `farms.yaml` | Affinity and mastery activities with mood tags (`fast`, `group`, `survival`, `chill`, `nofight`, `skill`), where to go, what it levels, and what to do if it is too hard or you get tired. Text may use placeholders such as `{drifter_ranks_left}` that the planner fills from the snapshot. |
| `routes.yaml` | The order in which the planner spends mastery sources (`order`), the title, blurb and fallbacks shown for each source, and the general tips. |

How the plan is built (`src/openwarframe/guide/mastery.py`):

1. Every source of mastery becomes a unit: an unfinished item, an intrinsic rank, a
   block of Steel Path nodes, a junction, Forma headroom on a rank 40 item, or a
   never-leveled item routed by how it is obtained.
2. Intrinsic ranks the banked points already pay for are bought greedily, cheapest
   first (Drifter 20, 25, 30, 45, 65, 90, 125, 160, 205, 255; Railjack 2^rank). The
   rest wait in `intrinsics_grind`.
3. Units are queued in `routes.yaml` order and handed to each rank until its
   threshold (2,500 x rank^2) is met. Items above the rank being worked toward wait.
4. Each phase takes its title and fallbacks from the source that contributes most.

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
