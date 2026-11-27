# Legal checklist

What OpenWarframe owes to others, and where each obligation is met. Check this list before every
release that adds a data source, a bundled library or a feature that touches the game.
This is a working checklist, not legal advice.

| Area | Obligation | Where it is met | Status |
| --- | --- | --- | --- |
| Our own code | MIT license, copyright notice kept in copies | `LICENSE`; shipped in every zip and the installer | Done |
| Bundled software | Keep the license text of every bundled library (Python, pywebview, httpx, openpyxl, …) | `packaging/third_party_notices.py` writes `THIRD_PARTY_LICENSES.txt` into each build | Done |
| Fonts and icons | Only fonts and images we may redistribute | Exports use system fonts (no Google Fonts since M5); the icon is our own (`docs/brand/icon.svg`) | Done |
| Digital Extremes' trademarks | Say we are a fan project, not made by or affiliated with DE; don't use DE logos or game art as our branding | README "Credits and license", the app footer, this file | Done |
| DE game data | Public Export, drop tables and world state are DE's; we read them, cache them locally and don't redistribute them | Each user's app downloads its own copy into their data folder (`codex update`); nothing from DE is committed or bundled | Done |
| Community data (MIT) | Credit warframe-public-export-plus and the WFCD projects | `docs/DATA_SOURCES.md` | Done |
| Warframe Wiki (CC BY-SA) | Attribute any fact taken from the wiki, with a link and the license; share-alike applies to the text we adapt | Every `kb/` entry that uses the wiki has a `sources:` link with `license: CC BY-SA`; item rows link back to their wiki page | Done; keep it for every new `kb/` entry |
| warframe.market | Follow their terms and rate limits; identify ourselves | Descriptive User-Agent, cached requests, one request per second, back-off on 429 | Done |
| browse.wf | Credit requested | `docs/DATA_SOURCES.md` | Done |
| Terms of Service: reading the running game | DE's terms forbid "unauthorized third-party software"; tolerated tools have still been caught in ban sweeps. Say so plainly, ask before the first use, never write to the game, never automate input | Consent screen and CLI prompt name the suspension or ban risk; reading is opt-in, Windows only, read-only; `docs/ACCOUNT_DATA_ACCESS.md` quotes DE's policy | Done |
| Terms of Service: screen capture (reward helper) | Only read pixels the player already sees; no overlays drawn into the game, no input sent | `live/ocr.py` captures and reads; nothing is injected | Done |
| Privacy | Say what is sent where; no telemetry; recordings opt-in | README "Privacy and risk"; recordings are off by default with a size cap | Done |
| Fan content policy | DE's fan content guidelines allow non-commercial fan tools that don't imply endorsement | Free, no ads, no paid features, disclaimer shown; re-check if DE publishes a new policy | Done, re-check yearly |
| Code signing | Signed Windows builds (an OV certificate is planned for December 2026); macOS stays ad-hoc signed and not notarized for now | `README.md` "Download" explains the SmartScreen and Gatekeeper prompts | Planned |
| Microsoft Store | Store listing needs a privacy policy URL, age rating and the trademark disclaimer | Not started; after the signing work | Planned |

## When you add something

- **A new data source:** add it to `docs/DATA_SOURCES.md` with its license, and to the table above if
  it has terms beyond MIT.
- **A new dependency:** check its license is compatible with MIT distribution (no GPL in the
  bundled app); `third_party_notices.py` picks it up on the next build.
- **Wiki-derived text:** link the page and mark `license: CC BY-SA` in the `kb/` entry.
- **Anything that touches the running game:** read-only, opt-in, explained in the consent text.
