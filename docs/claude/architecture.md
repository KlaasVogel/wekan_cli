# Architecture

## Modules (`src/wekan_cli/`)

| Module | Job | Status |
|---|---|---|
| `cli.py` | typer app: commands, options, output calls. No HTTP or parsing logic. `main()` turns errors into one stderr line + exit code. `make_client()` is the seam tests replace. | done (v0.1.0) |
| `errors.py` | `WekanError` and subclasses, each with its exit code | done |
| `config.py` | credentials parser, `~/.config/wekan/config.toml` (board/user aliases), `.wekan` lookup (current folder and up), board resolution with its source | done (v0.1.0) |
| `client.py` | `WekanClient` around `httpx.Client`: form-encoded login, Bearer token, token cache, one re-login on an auth failure, error mapping; `get`/`post`/`put`/`delete` | done (v0.2.0 writes) |
| `cache.py` | `~/.cache/wekan/`: the token (file 600, folder 700, atomic writes) | done (v0.1.0) |
| `models.py` | dataclasses built from the export: Board, Swimlane, WList, Card, Checklist, Item, Label, User, WipLimit; drops soft-deleted objects, orders by `sort` | done (v0.1.0) |
| `resolve.py` | name → object: board (alias, ID, title), card (`cardNumber`), list (title, swimlane), checklist, items (`(N)` or part of the title, across checklists) | done (v0.2.0) |
| `actions.py` | the write commands: change, read back from a fresh export, return a `Change` (no typer, no printing) | done (v0.2.0): add-item, tick, move, describe, new-card, label, delete-item |
| `output.py` | plain text and `--json` (boards, cards, changes); `--markdown` comes in v0.3.0 | done (v0.2.0) |

## Data flow

1. `cli.py` parses the command; `config.py` picks the board reference (`--board` > `WEKAN_BOARD` > `.wekan` > error)
   and `resolve.py` matches it against `GET /api/users/:id/boards`.
2. `client.py` fetches the **board export** (`GET /api/boards/:b/export`): one call returns cards with `cardNumber`,
   lists with `wipLimit`, swimlanes, labels, checklists, items and usernames. Every command reads it live, so nothing
   relies on an earlier call (people edit the board at the same time).
3. `resolve.py` finds the card, list or item in the export. Ambiguous matches raise `AmbiguousError` with the
   candidates.
4. A change is sent with its own endpoint, then read back and reported as `from → to (verified)`.

The lookup sits behind one function, so a `cardNumber → _id` cache plus `GET /api/cards/:id` can replace the export
read if big boards get slow.

## Wekan API facts the code relies on

- Login: `POST /users/login`, **form-encoded** (passwords can hold `+`/`=`). Then `Authorization: Bearer <token>` and
  `X-User-Id`. Tokens last 90 days. There is no working logout.
- If Wekan can't reach its database, every call waits ~30 s and then answers `401`. The client uses a 10 s timeout
  and treats a slow auth failure as a network problem (exit 6), without logging in again.
- Auth failure: `401` on `/api/user`, but **`200` with an error body** (`"statusCode": 401`) on board routes.
- Unknown routes answer **`200` with HTML**, not 404.
- `GET /api/boards` is admin-only; use `GET /api/users/:userId/boards`.
- Collection GETs return reduced objects; the export and `GET /api/cards/:id` return full ones.
- WIP limits are only in the export: `{"value": 2, "enabled": true}` is hard (no `soft` key), `"soft": true` is soft.
  **The API doesn't enforce them**: the tool does.
- `POST` card ignores `labelIds`; set labels with a `PUT` afterwards. `labelIds` and `assignees` replace the whole list.
- Checklist item `PUT` needs a JSON body; one call can tick and rename. Item and card `DELETE` are hard deletes.
- A card `PUT` goes through its current list (`/lists/:l/cards/:c`); through the wrong list it answers an empty 200 and
  changes nothing. An empty `description` answers `404 {"message":"Error"}`: send a single space to clear one.
- A moved card goes to the top of its new list. Lists can't be ordered through the API.
- Checklist titles are Markdown: "1. Step" renders as "1." for every item; use "(1) Step".
