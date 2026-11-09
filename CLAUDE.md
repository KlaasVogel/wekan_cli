# CLAUDE.md

Instructions for coding agents working on this repo.

## What this is

`wekan-cli`: a Python CLI (`wekan`) for the Wekan REST API, built with `httpx` + `typer`, installed with pipx.
Details: `docs/claude/architecture.md`, `docs/claude/conventions.md`, `docs/claude/testing.md`.

## Rules

- **Public repo.** Never commit a real Wekan URL, board/card/user IDs, usernames, board or card titles from a real
  board, hostnames, or anything from a credentials file. Fixtures use made-up data. Check the diff before every commit.
- **Secrets never reach output**: not in messages, errors, `--verbose`, logs or tracebacks. Keep
  `pretty_exceptions_enable=False`. Error messages must not include request headers or bodies.
- **Unit tests never call a real Wekan.** Use the fake in `tests/fakewekan.py`. Live tests are opt-in (`-m live`).
- Git: feature branch → PR → the owner reviews and merges. Never push to `main`. Ask before each commit.
  Each change gets an entry in `docs/changelog/vX.Y.Z.md`.

## Commands

```bash
.venv/bin/pytest            # unit tests
.venv/bin/black --check .   # formatting (line length 120)
.venv/bin/ruff check .      # lint
```
