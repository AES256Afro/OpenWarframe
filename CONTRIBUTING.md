# Contributing

Thanks for helping. OpenWarframe is MIT licensed; contributions are accepted under
the same license.

## Setup

```bash
uv sync --all-groups
uv run openwarframe --help
uv run pytest -q
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
