# Getting at your own account data

This is the part of the project with real uncertainty, so it gets its own document.
Everything below was checked on 2026-10-16; endpoints are undocumented by Digital
Extremes (DE) and can change.

## Summary

| Tier | Source | Needs | Gives | Risk |
| --- | --- | --- | --- | --- |
| 1 | Public profile endpoint | Account ID (24 hex chars) and platform | Mastery, XP per item, star chart, syndicates, intrinsics, achievements, loadout, lifetime stats | None known. Official, read-only, used by the in-game profile viewer and several community sites. |
| 2a | Inventory JSON file | A file you obtained some other way | Everything (resources, blueprints, foundry, relics, mods, quests, currencies, Helminth, Lich...) | None from us; depends on how the file was produced. |
| 2b | AlecaFrame hand-off | AlecaFrame installed and a readable export | Everything | Depends on AlecaFrame; its cached data is encrypted today. |
| 2c | Direct login adapter | Your email and password typed interactively | Everything | DE policy says "at your own risk". Logging in elsewhere ends the game session. **Not built unless the owner decides so (DG1).** |
| Live | `worldState.php` | Nothing | What is happening in the game world | None. Official public feed. |
| Live | `EE.log` tail | Game running on this machine | Current mission, squad state, login | None known; read-only, local. Contains your IP and email, so it is never uploaded. |

## Tier 1: the public profile endpoint

```
PC:         https://api.warframe.com/cdn/getProfileViewingData.php?playerId=<accountId>
PlayStation http://content-ps4.warframe.com/dynamic/getProfileViewingData.php?playerId=<accountId>
Xbox        http://content-xb1.warframe.com/dynamic/getProfileViewingData.php?playerId=<accountId>
Switch      http://content-swi.warframe.com/dynamic/getProfileViewingData.php?playerId=<accountId>
iOS         http://content-mob.warframe.com/dynamic/getProfileViewingData.php?playerId=<accountId>
Android     http://content-and.warframe.com/dynamic/getProfileViewingData.php?playerId=<accountId>
```

Verified today: a request with `?n=<display name>` returns HTTP 200 with an empty
body on the PC host and 404 on the legacy `content.warframe.com` host, so lookup is
**by account ID only**. The response carries `Cache-Control: public, max-age` of
roughly 600 seconds, so refreshing more often than every 10 minutes is pointless.

Response shape (from the open-source server reimplementation that mirrors it and from
WFCD's `profile-parser`):

```
{
  "Results": [ {
    "AccountId", "DisplayName", "PlayerLevel" (mastery rank), "Created",
    "LoadOutInventory": { "WeaponSkins", "XPInfo": [ { "ItemType", "XP" } ... ] },
    "PlayerSkills" (Railjack/Drifter intrinsics), "ChallengeProgress" (achievements),
    "Missions": [ { "Tag": "SolNode...", "Completes", "Tier" } ... ] (star chart),
    "Affiliations": [ { "Tag", "Standing", "Title" } ... ] (syndicates),
    "DailyFocus", "Wishlist", "Alignment", "Accolades", "TitleType",
    "GuildName", "GuildTier", "GuildXp", "GuildClass", "GuildEmblem",
    "LoadOutPreset" (current equipped loadout), "DeathMarks", "Harvestable", "DeathSquadable"
  } ],
  "TechProjects": [...], "XpComponents": [...],
  "Stats": { lifetime stats: kills, deaths, missions by type, time played, weapons used, ... }
}
```

What it cannot tell us: item *counts* (resources, blueprints, relics, mods), the
foundry queue, quests, credits, platinum, endo, boosters. Those live only in the
inventory.

### Finding your account ID

The ID is the 24-character hexadecimal value of the `gid` cookie set by
`warframe.com` when you are logged into the website. Community tools (FrameHub,
the Warframe Tracker browser extension) ask users to copy it from the browser's
cookie view. OpenWarframe will ship a guided helper and, later, an optional
consent-based read of that cookie. The game's `EE.log` does **not** contain it
(checked: zero matches for `accountId`, `nonce` or the ID pattern in the login lines).

## Tier 2: full inventory

The game client fetches `inventory.php` after login and receives one large JSON
document. Its fields are documented by the open-source server project
SpaceNinjaServer (`src/types/inventoryTypes/inventoryTypes.ts`, interface
`IInventoryClient`). The sections OpenWarframe cares about:

| Section | Meaning |
| --- | --- |
| `MiscItems` | Resources, components, **relics** (`/Lotus/Types/Game/Projections/...`), fish, gems... with `ItemCount` |
| `Recipes` | Owned blueprints with counts |
| `PendingRecipes` | Foundry queue with `CompletionDate` |
| `Suits`, `LongGuns`, `Pistols`, `Melee`, `SpaceSuits`, `SpaceGuns`, `SpaceMelee`, `Sentinels`, `SentinelWeapons`, `KubrowPets`, `MoaPets`, `MechSuits`, `Hoverboards`, `OperatorAmps`, `CrewShips` ... | Built equipment with XP, polarities, installed mods |
| `Upgrades`, `RawUpgrades` | Mods (ranked, with fingerprints) and unranked stacks |
| `QuestKeys` | Quests started and completed |
| `Missions` | Star chart completions (also in the profile) |
| `Affiliations`, `FocusXP`, `PlayerSkills` | Syndicates, Focus schools, intrinsics |
| `InfestedFoundry` | Helminth: unlocked, subsumed abilities, resources |
| `EvolutionProgress` | Incarnon evolutions |
| `Nemesis`, `NemesisHistory` | Current Lich/Sister and history |
| `RegularCredits`, `PremiumCredits`, `PremiumCreditsFree`, `FusionPoints`, `PrimeTokens` | Credits, platinum, endo, Regal Aya |
| `Boosters`, `LoadOutPresets`, `Ships`, `ShipDecorations`, `CompletedSorties`, `SeasonChallengeHistory`, `ChallengeProgress` | Everything else |

### How existing tools get it

- **AlecaFrame** (closed source, Overwolf). Its FAQ says the "potentially risky part,
  getting your account/inventory data, is handled by Overwolf" and that data refreshes
  only on login and loading screens. It caches the inventory locally in
  `%LOCALAPPDATA%\AlecaFrame\lastData.dat`, AES-encrypted.
- **Quantframe** (open source, Rust/Tauri) defines an inventory-source trait with
  three implementations: `profile` (Tier 1 above), `file` (a plain inventory JSON) and
  `alecaframe` (decrypts `lastData.dat` with keys fetched from Quantframe's own
  backend). That is the precedent for OpenWarframe's adapter design. The decryption
  keys are not public, so reproducing the AlecaFrame adapter is not something this
  project can promise.
- **The mobile companion protocol** (`login.php` then `inventory.php`), reimplemented
  by SpaceNinjaServer on the server side. A third-party client that speaks it gets the
  complete inventory. It requires the account password (hashed client-side), ends the
  game's own session, and is the kind of "unauthorized third-party software" DE's
  EULA talks about even though several tools have used it for years.

### DE's policy, in their words

From the support article *Third Party Software and You* and the 2024 forum post
*Third party software usage* by [DE]Juice:

- "If you use external software in conjunction with Warframe, then you do so at your
  own risk."
- DE does not publish a list of approved or banned programs, because tolerated
  software can later be caught in an automated ban "drag net".
- The same rules apply to Overwolf apps; DE's involvement with Overwolf was limited to
  conversations ensuring the EULA and ToS are not breached.

Nothing in these statements singles out log reading or public endpoints as a problem,
and the public profile endpoint is literally what the game and the website use.
Nothing in them blesses any inventory method either.

### Recommendation

1. Build Tier 1 first. It already powers mastery tracking, star chart, syndicates,
   achievements, stats, the affinity plan and most of the guide.
2. Ship the JSON-file adapter so anyone who has an inventory export from any source
   gets the full experience.
3. Put the direct-login adapter behind **DG1**. If built: interactive password prompt,
   never written to disk, explicit `--i-accept-the-risk` flag, a plain-language
   warning that the game session will be logged out, and a one-shot fetch (no
   polling). If not built: say so in the README and point at the file adapter.

## Live signals from `EE.log`

Location: `%LOCALAPPDATA%\Warframe\EE.log`. Reset on every game launch. Lines look
like `13.649 Sys [Info]: Logged in <name>`. Verified useful lines today:

| Line shape | Use |
| --- | --- |
| `Sys [Info]: Logged in <name>` | Session start, display name |
| `Background.lua: EliteAlertMission at SolNode122 (Uranus - Stephano)` | Current alert / mission selected in navigation |
| `ThemedSquadOverlay.lua: OnSquadMissionSelected` | Squad picked a mission |
| `Sys [Info]: Starting new background region: /Lotus/Levels/...` | Level transitions (orbiter, relay, mission) |
| `Net [Info]: SendSessionUpdate: updating sessionId: ...` | Squad session changes |
| `.../MasteryRanks/NewMasteryRanks/Rank22to24` | Mastery bracket of the icon loaded (coarse) |

Not present: API URLs with session parameters, account ID, inventory contents.
Present and sensitive: IP addresses and the login e-mail (per the wiki warning), which
is why the tail stays local and only derived events are stored.
