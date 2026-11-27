# Weapon builds

Open a primary or secondary gun in any list, pick a target and click **Suggest a build**. The app
works out the 8 mods that give the most damage, from the game data and the damage formulas
below. It doesn't copy builds from build sites: those go out of date and often disagree with how
the game calculates damage now.

## What it uses

- **Weapon stats:** DE's Public Export (damage by type, crit, status, fire rate, multishot,
  magazine, reload) and the weapon class from warframe-public-export-plus (rifle, shotgun, bow,
  sniper; compatibility tags such as semi-auto).
- **Mods:** each mod's effect per rank from the game data ("+165% Damage"), parsed into numbers
  (`builds/mods.py`). Lines after "On Kill:", "when Aiming" and similar are conditional: on-kill
  stacks (Galvanized mods) can be counted at their maximum; other conditions are listed, not
  counted.
- **Your mods:** with an inventory loaded, **Only mods I own** limits the build to mods you have, at
  the highest rank you have, and names the one mod you don't have that would add the most.

## Formulas

From wiki.warframe.com, read 2026-11-27 (pages edited between 2026-09 and 2026-11):

| Rule | Source page |
| --- | --- |
| Base damage mods (Serration, Heavy Caliber) add together and multiply every damage type | Damage/Calculation, Serration |
| Elemental mods add a % of the base damage after base damage mods; multishot multiplies after | Damage/Calculation |
| Elements combine in mod slot order; the weapon's own elements come last, or join the slot of a mod with the same element; an innate combined element never combines | Damage |
| Physical mods multiply only the physical type the weapon already has | Damage |
| Average crit multiplier = 1 + crit chance x (crit damage - 1), also above 100% | Critical_Hit |
| Status chance is per pellet; above 100% gives extra procs | Status_Effect |
| Bane mods are a separate multiplier (x1.30, Primed x1.55) | Faction_Damage_Bonus |
| Faction modifiers since Update 36: x1.5 or x0.5 per damage type (e.g. Grineer: Impact and Corrosive x1.5) | Damage/Overview_Table |
| Sustained DPS = damage per shot x fire rate x magazine / (fire rate x reload + magazine) | Damage/Calculation |
| Variants of one mod (Primed, Galvanized, Amalgam) can't be equipped together | Mod, mod infoboxes |

## Armor and status

Builds are judged against an enemy (wiki pages read 2026-11-27; edit dates in brackets):

| Rule | Source |
| --- | --- |
| Armor stops 0.9 x sqrt(armor / 2700) of damage, at most 90% | Armor (2026-09-28) |
| Armor grows with level (two curves blended between 70 and 80 levels above base), at least 200, at most 2700; the Steel Path adds 100 levels and no armor | Enemy_Level_Scaling (2026-07-29), The_Steel_Path (2026-10-14) |
| The armored reference unit is a Heavy Gunner: 500 armor at level 8 | Module:Enemies/data/grineer (2026-11-26) |
| Corrosive strips 26% of armor at 1 stack, 6% more per stack, 80% at 10; 8 s each | Damage/Corrosive_Damage (2026-10-26) |
| Heat strips 50% of armor while it burns; strips multiply | Damage/Heat_Damage (2026-11-14) |
| Viral: health damage x2 at 1 stack, +0.25 per stack, x4.25 at 10; 6 s each | Damage/Viral_Damage (2026-10-26) |
| Cold: crit multiplier +0.10 at 1 stack, +0.05 per stack, +0.50 at 9 | Damage/Cold_Damage (2026-09-30) |
| Slash, Heat, Toxin, Electricity and Gas deal 6 ticks over 6 s; each tick is 0.35 (Slash) or 0.5 x modded base damage x that element's mod bonus x bane (counted twice) x status damage mods x the hit's crit | Damage/<Type>_Damage pages (2026-11) |
| Slash ticks ignore armor (Cinematic damage); the others are reduced by armor | Damage/Slash_Damage, Armor |
| Each pellet rolls status; the proc type follows each damage type's share of the weapon's damage, before faction modifiers | Status_Effect (2026-11-20) |

The model is a steady state while firing: proc rate per type = multishot x status chance x fire
rate x the share of time not reloading x that type's share; stacks = proc rate x duration,
capped. Choices in the app:

- **Enemies:** No armor (a damage test), Normal missions (level 35: about 1,300 armor) or Steel
  Path (level 135: 2,700 armor). Grineer, Scaldra, Orokin, Narmer, Anarchs and "any enemy" use
  the armored unit; Corpus, Infested and the rest are judged without armor.
- **Armor already stripped:** for squads or Warframes that remove armor with abilities.

## How the build is chosen

The 8 slots are filled one mod at a time with the mod that adds the most damage per second to
health, then mods are swapped until no swap helps (`builds/search.py`). Swaps include two
elemental mods at once, because a combined element (Viral = Cold + Toxin) only pays off when
both halves are in. On the test weapons this finds the same build as trying every combination. Elemental mods are
placed in the order that gives the best combination for the target. Every build must fit 60 mod
capacity (an Orokin Catalyst) with matching polarities halving a mod's drain; the build says how
many Forma that takes.

## Not counted yet

- Shields and overguard (Corpus rely on shields: Magnetic and Toxin are worth more there).
- Heat's growing stacks in long fights (each Heat proc refreshes them all; counted per proc),
  Heat's 2-second ramp, Electricity and Gas hitting nearby enemies, Blast and Puncture effects.
- Status-based bonuses (Galvanized Aptitude's damage per status type).
- Headshots and weak points, Riven mods, arcanes, Incarnon forms, the Exilus slot.
- Bow fire-rate bonuses (bows get double from some mods) and charge or burst timing.
- Melee weapons, Archguns and companion weapons.

## Checking a build

The app shows per-shot damage, sustained DPS, crit, status, multishot and fire rate. Put the same
mods on the weapon in the game's Arsenal and compare the numbers there; differences point at
something the model doesn't cover. Reports with the weapon and mods are welcome.
