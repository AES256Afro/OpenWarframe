# Security

## Reporting a problem

Please report security problems privately, through GitHub: on the repository page open
**Security → Report a vulnerability**. Don't open a public issue for them. You'll get an
answer, and a fix will be released and credited (if you want) once it's ready.

Useful to include: the version (`openwarframe version`), your OS, what an attacker could do,
and the steps to reproduce it. Never include your account ID, inventory file, game log or
anything from `logs/` without looking at it first.

## What OpenWarframe is careful about

- **The game session key.** Reading the game's session (Windows, opt-in) finds a key that can
  download your inventory. It is used for one request and never saved; logs mask it.
- **The local app server.** It listens on 127.0.0.1 only, answers only requests addressed to
  it by name (DNS rebinding), checks the Origin of every change, can't be framed, and serves
  a Content-Security-Policy.
- **Files from elsewhere.** Inventory files and data from warframe.market and the community
  exports are treated as untrusted: values are checked and escaped; exported spreadsheets
  never contain formulas from game data.
- **Releases.** Built by GitHub Actions with read-only tokens and actions pinned to commits;
  each zip has a SHA-256 checksum on the release page. The builds are not code-signed.

## Supported versions

Only the latest release gets fixes. The app tells you when a newer one is out.
