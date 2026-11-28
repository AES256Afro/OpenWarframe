# Builds

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

| Shields take every damage type except Toxin, which goes to health (hits and ticks); armor doesn't protect shields; faction modifiers apply to shields too | Damage/Toxin_Damage (2026-11-25), Damage/Calculation (2026-11-04), Damage (2026-10-30) |
| Magnetic: shield damage x2 at 1 stack, +0.25 per stack, x4.25 at 10; 6 s each | Damage/Magnetic_Damage (2026-10-26) |
| Slash bleed hits shields since Update 36 | Damage/Slash_Damage (2026-11-25) |
| Health and shields grow with level (per-faction curves); the Steel Path multiplies both by 2.5 | Enemy_Level_Scaling (2026-07-29), The_Steel_Path (2026-10-14) |

The faction-modifier-on-shields rule is read from "regardless of the presence of armor or shields"
on the Damage page; no page says it outright. Heat, Electricity and Gas ticks are taken to hit
shields first, since only Toxin is described as skipping them.

Builds are scored by **time to kill** one reference enemy: shields first (Toxin hurts health
meanwhile), then health. Reference units (Module:Enemies/data): a Heavy Gunner (300 health, 500
armor, level 8) for Grineer, Scaldra, Orokin, Narmer, Anarchs and "any enemy"; a Corpus Tech (700
health, 250 shields, level 15) for Corpus; a Toxic Ancient (400 health, level 1) for Infested; an
unarmored unit with a Heavy Gunner's health for the rest. At the Steel Path (level 135) a Corpus
Tech has about 328,500 health and 48,200 shields, so Viral still matters more than Magnetic there.

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

- Shield regeneration between bursts, the Magnetic shield-break burst, overguard, and the
  Toxic Ancient's own Toxin resistance. Regeneration waits for a pause in incoming damage, and
  the model fires steadily, so it wouldn't change the result.
- Stacks are taken at their steady state from the first shot; very short kills get less.
- Heat's growing stacks in long fights (each Heat proc refreshes them all; counted per proc).
  The reference kills take 1 to 3 seconds, and the growth only shows after about 6, so it's left
  out. Heat's 2-second ramp, Electricity and Gas hitting nearby enemies, Blast and Puncture effects.
- Status-based bonuses (Galvanized Aptitude's damage per status type).
- Headshots and weak points, Riven mods, Incarnon forms.
- Bow fire-rate bonuses (bows get double from some mods) and charge or burst timing.
- Archguns and companion weapons.

## Checking a build

The app shows per-shot damage, sustained DPS, crit, status, multishot and fire rate. Put the same
mods on the weapon in the game's Arsenal and compare the numbers there; differences point at
something the model doesn't cover. Reports with the weapon and mods are welcome.

## Melee builds

Open a melee weapon and click **Suggest a build**. Melee uses the same damage, armor, shield and
status model as guns (no multishot, no reload), plus (wiki pages read 2026-11-27):

| Rule | Source |
| --- | --- |
| The combo multiplier is 1x below 20 hits, then +1x per 20 hits up to 12x; it doesn't raise normal attack damage | Melee_Combo (2026-10-28) |
| Blood Rush: crit chance = base x (1 + crit mods + 0.40 x (combo - 1)); Weeping Wounds the same for status | Blood_Rush (2026-08-24), Weeping_Wounds (2026-05-14) |
| Gladiator set: +10% crit per set mod per combo step, alongside Blood Rush | Gladiator_Set (2026-01-16) |
| Condition Overload: +80% per status type on the target (any source), in the same bonus as Pressure Point | Condition_Overload (2026-10-12) |
| Attack speed bonuses add together; Berserker Fury can't be used with Fury or Primed Fury | Attack_Speed (2026-11-11), Berserker_Fury |

Choices in the app: **Combo** (none, 6x, 12x) and **Status types from other sources** (what your
abilities, guns or squad keep on the target, for Condition Overload). The weapon's own statuses
count as the chance that at least one proc of each type is still running.

Damage per second uses the attack speed from the game data; real hits per second depend on the
stance, so compare builds of one weapon rather than melee with guns. Melee gets 10 more capacity
for a stance in a slot of matching polarity. Not counted yet: slams and follow-through.

### Heavy attacks

Set **Attack** to **Heavy attack** to judge one heavy attack instead of normal hits (wiki
Heavy_Attack, read 2026-11-27):

| Rule | Source |
| --- | --- |
| Heavy damage = normal damage x the weapon type's heavy multiplier x the combo multiplier; the game data's `heavyAttackDamage` is normal damage x that multiplier (Galatine Prime: 1,680 = 280 x 6) | Heavy_Attack, game data |
| A heavy attack spends the combo | Heavy_Attack, Melee_Combo |
| Killing Blow's heavy damage joins the base damage bonus (Pressure Point) | Killing_Blow |
| True Steel and its variants count twice on heavies ("x2 for Heavy Attacks") | True_Steel |
| Wind-up speed mods shorten the wind-up; attack speed doesn't | Heavy_Attack |

The score is the damage of one heavy attack, its hit plus the status damage over time of its
procs. Its own procs land after the hit, so the hit meets full armor. The time to build the
combo again isn't counted, so compare heavy builds with heavy builds.

## Weapon arcanes

Guns and melee weapons have one arcane slot (wiki Arcane_Enhancement, read 2026-11-27). Primary
weapons take Primary and Fractalized arcanes (bows add Longbow, shotguns Shotgun); secondaries take
Secondary, Cascadia and Conjunction; melee takes Melee. The build picks the best of the ones it
can score, at full stacks, from the in-game text:

- Primary and Secondary Merciless: +30% damage per kill stack, up to 12, added to the base damage
  bonus (Serration).
- Primary Blight, Primary Frostbite, Conjunction Voltage: stacks from the weapon's own Toxin,
  Cold or Electricity procs; only offered when the build deals that element.
- Melee Doughty: +1.0x critical multiplier per 10% Puncture status chance, rounded to 0.1, at most
  +50x.
- Melee Animosity: up to +420% crit chance on the next heavy attack; heavy attacks only.

Other weapon arcanes trigger on things the model doesn't track (headshots, ability casts,
blocking). Pick one in the **Arcane** selector to see the build with it; ones the model can't
read are shown but not counted. The arcane isn't checked against your inventory.

## Warframe builds

Open a Warframe and click **Suggest a build**. A frame's abilities don't share one formula, so
this doesn't calculate kills. It balances the stats the abilities you use scale with:

- **Which stats an ability uses** comes from `kb/builds/abilities.json`: for each ability, whether
  it has Strength, Duration and Range values, its energy cost and whether it's channeled, taken
  from the Warframe Wiki's ability pages and `Module:Ability/data` (checked 2026-11-27; 127
  frames, 336 abilities). Frame health, shields, armor and energy at rank 30 come from
  `Module:Warframes/data`. The wiki is CC BY-NC-SA 3.0 and isn't contacted by the app; see
  docs/LEGAL.md.
- **Weights:** a stat counts once for each of your chosen abilities that uses it. Efficiency
  counts every ability that costs energy; a channeled ability counts twice for Efficiency and
  Duration. After the first build, untick the abilities you don't cast.
- **Score:** weight x ln(stat) for Strength, Duration and Range; weight x -ln(energy cost) for
  Efficiency (capped at 175%, cost floor 25%); and survivability x ln(effective health gain),
  with effective health = health x (armor + 300) / 300 + shields (wiki Armor: Tenno damage
  reduction = armor / (armor + 300)). Survivability: not needed, some (default) or a lot.
- **Search:** like guns, plus swaps of two mods at once, because a mod with a cost (Blind Rage,
  Overextended) often only pays off next to the mod that covers it. A slot stays empty when
  every remaining mod would make the build worse. Builds fit 60 capacity (Orokin Reactor)
  plus what the aura adds.
- **Exilus slot:** a 9th slot that only takes exilus-capable mods (`isUtility` in the game data,
  such as the Drift mods); those can also go in the 8 general slots.
- **Aura slot:** an aura adds capacity, double its drain in a slot of matching polarity (wiki
  Aura, edited 2026-11-04): +14 for most auras at rank 5, +18 for Steel Charge and Power
  Donation. The aura that helps your own stats most is picked (Physique: +20% health; Stand
  United: +25% armor; Power Donation costs you 30% Strength); otherwise the one with the most
  capacity. Most auras help the squad in ways this doesn't count (Corrosive Projection, Energy
  Siphon), so any max-rank aura with a matching polarity adds the same capacity.
- **Augments:** the frame's augment mods come from the game data (`compatName` is the frame; the
  text names the ability, "Spores Augment: ..."). They change what an ability does, which no
  single number captures, so the app lists the augments for the abilities you use, with their
  effect text and whether you own them, and puts in only the ones you tick. The rest of the
  build is fitted around them; an augment that's exilus-capable may take the Exilus slot.
- **Archon Shards** (wiki Archon_Shard, edited 2026-11-21): None, 5 shards or 5 Tauforged
  (x1.5). 5 slots, a stat may repeat. Scored options: Crimson Ability Strength or Duration
  (+10%, Tauforged +15%, added to the mods' bonuses) and Azure Health, Shields or Armor (+150,
  Tauforged +225, added after all percentage bonuses). Every combination is tried (126 at most),
  alternating with the mod search. With an inventory and Only mods I own, only the loose Crimson
  and Azure shards you have are used; shards already in a frame aren't in the inventory counts.
  Not scored: Amber (casting speed, orbs) and the Emerald, Topaz and Violet options that raise
  ability damage against enemies with a status.
- **Umbral set** (wiki Umbral_Intensify, _Vitality, _Fiber, edited 2026-07-10): each Umbral mod's
  value grows with the number of Umbral mods equipped. Umbral Intensify x1.25 with 2 and x1.75
  with 3 (44% -> 77% Strength); Umbral Vitality and Umbral Fiber x1.30 and x1.80 (100% -> 180%).
- **Arcanes** (2 slots, no duplicates; wiki Arcane_Enhancement, edited 2026-11-21). Warframe
  arcanes are the "Arcane ..." and "Molt ..." ones. Four hold steady during a mission and are
  scored from the game's text: Molt Augmented (+0.24% Strength per kill, 250 stacks: +60%;
  lasts until death), Arcane Blessing (+24 health per health orb, 50 stacks: +1,200), Arcane
  Bellicose (round(max health / 250 x 6)% Strength, up to 72%; it reads your final health,
  Blessing included) and Arcane Intention (+250 health per channeled ability you use, up to 4).
  The rest trigger on something (being hit, freezing enemies, going invisible), so you pick them
  in the two arcane selectors; the free slots get the best scored ones.
- **Variants** can't be equipped together: Primed, Umbral, Archon and Amalgam versions with their
  base mod (Umbral Fiber with Steel Fiber).

The limit: the data says that an ability uses a stat, not how much it gains from it, so a
damage ability and a buff count the same. Picking the abilities you actually cast is how to
steer it. Not counted: arcanes that trigger on something (you can still pick them), conditional
mod effects (on kill, while aiming). Aura health and armor bonuses are added to the mods' bonuses;
the wiki doesn't say whether they stack that way or multiply.

