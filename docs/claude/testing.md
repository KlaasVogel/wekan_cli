# Testing

## Unit tests (default)

```bash
.venv/bin/pytest
```

- One test file per module: `src/wekan_cli/<module>.py` → `tests/test_<module>.py`.
- **No real Wekan.** `tests/fakewekan.py` is an in-memory Wekan behind `httpx.MockTransport`. It copies the real API's
  quirks (HTML `200` for unknown routes, `200` + error body for a bad token on board routes, form-encoded login).
  Add routes there as commands need them, and test the fake itself in `tests/test_fakewekan.py`.
  Write routes change the fake's state; `drop_writes = True` answers writes without storing them, to test the
  read-back check (exit 8).
- Board data comes from export-shaped JSON in `tests/fixtures/`. **All IDs, names and titles are made up**; never
  record a real token or login response.
- `conftest.py` points `HOME` and the XDG folders at a temp folder for every test, so the real config, credentials
  and cache are never read or written.
- The fake's password holds `+` and `=` on purpose (form-encoding bugs).
- Secret checks: tests assert that a crash, a failed login and `--verbose` never print the password or token.

## Live tests (opt-in)

```bash
WEKAN_LIVE_BOARD=<board id> .venv/bin/pytest -m live
```

Planned, not written yet. Rules:

- Only against a throwaway board, never a board in use. The suite refuses to run unless the board's title contains
  "test" (any case).
- Each test creates its own card and cleans up its checklist items afterwards.
