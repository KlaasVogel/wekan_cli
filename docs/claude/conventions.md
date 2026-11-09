# Conventions

## Code

- Python `>=3.13`, `src/` layout, type hints everywhere (Pylance/pyright **strict** clean).
- Black, line length 120. ruff (`E`, `F`, `I`, `UP`, `B`, `SIM`).
- Google-style docstrings for every non-obvious function and class.
- `pathlib`, not `os.path`. `dataclasses` for data.
- Mark temporary code with `# TODO:` or `# TEMP:` and a reason. No commented-out dead code.

## Secrets

- The password field of the credentials dataclass has `repr=False`. The token lives only in the client and the cache file.
- No secret in any message, error, log line or traceback. Unexpected errors print only the exception type
  (`WEKAN_DEBUG=1` prints a plain traceback, without local variables).
- httpx logging stays off.

## Output

- Short plain text by default; `--json` for scripts; IDs only with `--ids`.
- Every change is read back and reported as `#14 Title: Doing → Waiting (verified)`.
- Every command's `--help` has a one-line `Example:`.

## Exit codes

| Code | Meaning | Class |
|---|---|---|
| 0 | ok | |
| 1 | internal error (a bug) | |
| 2 | usage error | typer/click |
| 3 | not found (board, list, card, item) | `NotFoundError` |
| 4 | ambiguous | `AmbiguousError` |
| 5 | auth (login failed, no access) | `AuthError` |
| 6 | network or server error | `NetworkError` |
| 7 | refused (hard WIP limit, `--from` mismatch, duplicate card, missing `--yes`) | `RefusedError` |
| 8 | a change didn't show up when read back | `VerifyError` |

## Git

Feature branch → PR → the owner merges. Never push to `main`. Each change gets an entry in `docs/changelog/vX.Y.Z.md`.
