# Data sources

All verified on 2026-10-16 unless noted. "Join key" is how the source links to the
rest: the game's internal item path (`uniqueName`, e.g.
`/Lotus/Powersuits/Rhino/RhinoPrime`) or the node id (`SolNode94`).

## Static game data

| Source | URL | Format | Gives | Cadence | License | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Public Export (DE, official) | `https://content.warframe.com/PublicExport/index_en.txt.lzma` then `.../PublicExport/Manifest/<file>` | LZMA-alone index, JSON manifests | 16 manifests: Customs, Drones, Flavour, FusionBundles, Gear, Keys (quests), **Recipes** (blueprints + ingredients), **Regions** (nodes), RelicArcane, Resources, Sentinels, SortieRewards, Upgrades (mods), Warframes, Weapons, Manifest (images) | On game updates; file names carry a content hash | DE's | Python's `lzma` rejects the index in auto/alone mode; decode the body after the 13-byte header as raw LZMA1 (see `spikes/poc_public_export.py`). Some manifests contain raw control characters: strip before `json.loads`. Counts today: 1,885 recipes, 841 weapons, 269 regions, 3,551 resources. |
| warframe-public-export-plus (calamity-inc) | `https://github.com/calamity-inc/warframe-public-export-plus` (branch `senpai`), raw files via `raw.githubusercontent.com/calamity-inc/warframe-public-export-plus/senpai/<File>.json` | JSON | Everything DE does not export: Relics, Enemies, MissionTypes, Rewards, Vendors, Syndicates, **Challenges (achievements)**, Nightwave, Bounties, FocusUpgrades, Intrinsics, Codex, Factions, Tilesets, Boosters, Arcanes, dict.en.json | Unstated | MIT | Pin a commit; check diffs on update. |
| WFCD warframe-drop-data | `https://drops.warframestat.us/data/all.json`, `info.json`, `missionRewards.json`, `relics.json`, `blueprintLocations.json`, `modLocations.json`, `enemyBlueprintTables.json`, `enemyModTables.json`, `cetusBountyRewards.json`, `zarimanRewards.json`, `sortieRewards.json`, `transientRewards.json`, `syndicates.json` | JSON | Parsed version of DE's official drop table page | Game updates (not every hotfix); `info.json` carried `modified` = 2026-10-07 today | MIT | Source page: `https://www.warframe.com/droptables` (302 to a DigitalOcean-hosted HTML). Keys are item *names*, not uniqueNames: needs a name→uniqueName map (from Public Export / warframe-items). |
| WFCD warframe-items (`@wfcd/items`) | `https://github.com/WFCD/warframe-items` (`data/json/*.json`) | JSON | Merged item records with components, drops, images (`cdn.warframestat.us/img/<imageName>`), tradability, i18n | Automated on releases | MIT | Convenient cross-check and image source; not the primary store. |
| WFCD warframe-worldstate-data | npm `warframe-worldstate-data` | JSON | Node names, mission types, factions, sortie modifiers, syndicate names | Community | MIT | Fallback for names when Public Export lacks them. |
| warframe.market v2 | `https://api.warframe.market/v2/items` (3,893 items; each has `gameRef` = uniqueName and `slug`); orders and statistics per official docs `https://warframe.market/api_docs` | JSON | Prices and order books for tradeable items | Live | Terms on their site | No auth for reads. Use descriptive User-Agent; cache aggressively. |
| Warframe Wiki | `https://wiki.warframe.com` (Lua data modules such as `Module:Weapons/csv`) | HTML / CSV modules | Human-curated facts, farming notes | Community | CC BY-SA | Not scraped wholesale. Facts used in the knowledge base carry an attribution link. |
| browse.wf | `https://browse.wf` (`oracle.browse.wf`, `arbys.txt`, `sp-incursions.txt`) | text/JSON | Arbitration schedule, Steel Path incursions, bounty challenges, Deep Archimedea modifiers | Live | Credit requested | Secondary live source. |

## Account data

See `docs/ACCOUNT_DATA_ACCESS.md`.

| Source | URL | Gives |
| --- | --- | --- |
| Public profile (official) | `https://api.warframe.com/cdn/getProfileViewingData.php?playerId=<id>` (+ platform hosts) | Progression, stats, loadout |
| Inventory JSON (user-supplied) | local file | Everything |
| `EE.log` (local, read-only) | `%LOCALAPPDATA%\Warframe\EE.log` | Live session signals |

## Live world state

| Source | URL | Notes |
| --- | --- | --- |
| Official world state | `https://api.warframe.com/cdn/worldState.php` (PC; `api-ps4`, `api-xb1`, `api-swi`, `api-mob`, `api-and` for other platforms, all identical since Update 32) | 42 top-level sections today, about 200 KB, UTF-8. Used sections: `ActiveMissions` (fissures, `Hard` = Steel Path), `VoidStorms`, `Alerts`, `Invasions`, `Sorties`, `LiteSorties` (Archon Hunt), `SeasonInfo` (Nightwave), `VoidTraders` (Baro), `SyndicateMissions` (incl. bounties), `Goals`/`Events`/`HubEvents`, `PrimeVaultTraders` (Prime Resurgence), `DailyDeals`, `FlashSales`, `EndlessXpSchedule` (Circuit), `Conquests` (Archimedea), `KnownCalendarSeasons`, `GlobalUpgrades` (boosters), `WeeklyVaultBonusRewards`. Node ids resolve via `ExportRegions`. |
| WFCD warframe-status (`api.warframestat.us/<platform>`) | parsed, friendlier JSON | Timed out twice from this machine today (20 s and 60 s). Treat as optional, never required. |
| WFCD warframe-worldstate-parser | `https://github.com/WFCD/warframe-worldstate-parser` | Reference for field semantics when writing our own parser. |

## Reference implementations worth reading

| Project | Why |
| --- | --- |
| SpaceNinjaServer (`spaceninjaserver/SpaceNinjaServer`) | Full TypeScript types for inventory, profile, stats and login payloads; the controller that builds the public profile response. |
| WFCD profile-parser, arsenal-parser | Profile JSON parsing, mastery math. |
| Paroxity FrameHub (Apache-2.0) | Mastery checklist including mission, junction and intrinsics XP; account-ID onboarding UX. |
| Kenya-DK quantframe-react | `InventorySource` trait with profile / file / AlecaFrame implementations; SQLite local store; warframe.market client. |
| EnzCampos warframe-profile-extension | Reads the `gid` cookie from warframe.com and fetches the profile per platform. |
| AlecaFrame docs (`docs.alecaframe.com`) | Feature benchmark for the foundry/crafting-tree views. |
