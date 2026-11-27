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

## How the build is chosen

The 8 slots are filled one mod at a time with the mod that adds the most sustained damage, then
mods are swapped one at a time until no swap helps (`builds/search.py`). Elemental mods are
placed in the order that gives the best combination for the target. Every build must fit 60 mod
capacity (an Orokin Catalyst) with matching polarities halving a mod's drain; the build says how
many Forma that takes.

## Not counted yet

- Armor and armor stripping (Corrosive, Heat). Against armored enemies, especially on the Steel
  Path, builds that strip armor do better than these numbers show.
- Damage over time from status effects (Slash, Heat, Toxin, Gas, Electricity) and status-based
  bonuses (Galvanized Aptitude's damage per status type).
- Headshots and weak points, Riven mods, arcanes, Incarnon forms, the Exilus slot.
- Bow fire-rate bonuses (bows get double from some mods) and charge or burst timing.
- Melee weapons, Archguns and companion weapons.

## Checking a build

The app shows per-shot damage, sustained DPS, crit, status, multishot and fire rate. Put the same
mods on the weapon in the game's Arsenal and compare the numbers there; differences point at
something the model doesn't cover. Reports with the weapon and mods are welcome.
