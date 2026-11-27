# Contributing

Thanks for helping. OpenWarframe is MIT licensed; contributions are accepted under
the same license.

## Setup

```bash
uv sync --all-groups
uv run openwarframe --help
uv run pytest -q              # add -m "not host" to skip tests that need Chrome or an OCR engine
uv run pytest -q --cov        # with coverage; CI fails below the floor in pyproject.toml
uv run ruff check . && uv run ruff format .
```

## Ground rules

- Never commit account data, inventory files, `EE.log` excerpts or account IDs.
  Fixtures are synthetic and small.
- Every network source gets a descriptive User-Agent and goes through the cached
  HTTP client in `openwarframe.http`.
- Keep raw payloads next to normalized data so parsers can be re-run offline.
- Knowledge-base entries (`kb/`) need a source and a `last_verified` date.
- Read `docs/ROADMAP.md` before opening a large pull request; milestones have
  acceptance criteria.

## Building and releasing

```bash
uv run pyinstaller packaging/openwarframe.spec --noconfirm
uv run python packaging/smoke_test.py dist/OpenWarframe/openwarframe-cli.exe   # Windows
uv run python packaging/smoke_test.py dist/OpenWarframe.app/Contents/MacOS/openwarframe-cli   # macOS
```

CI builds and smoke-tests both platforms on every pull request. To release, set
`__version__` in `src/openwarframe/__init__.py` (the only place the version lives), add the
release to CHANGELOG.md, merge, then push a `v<version>` tag. `.github/workflows/release.yml` builds both zips with a read-only
token and a final job publishes the release only once both are attached, together with
`constraints.txt`, `install.ps1` and the checksums. GitHub Actions are pinned to commit
SHAs; Dependabot proposes updates.

