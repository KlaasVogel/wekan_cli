# Architecture

## Modules (`src/wekan_cli/`)

| Module | Job | Status |
|---|---|---|
| `cli.py` | typer app: commands, options, output calls. No HTTP or parsing logic. `main()` turns errors into one stderr line + exit code. | skeleton |
| `errors.py` | `WekanError` and subclasses, each with its exit code | done |
| `config.py` | credentials parser, `~/.config/wekan/config.toml` (board/user aliases), `.wekan` lookup (current folder and up), board resolution with its source | planned (v0.1.0) |
| `client.py` | `WekanClient` around `httpx.Client`: form-encoded login, Bearer token, token cache, one re-login on an auth failure, error mapping | planned (v0.1.0) |
| `cache.py` | `~/.cache/wekan/`: the token (file 600, folder 700, atomic writes) | planned (v0.1.0) |
| `models.py` | dataclasses: Board, Swimlane, WList, Card, Checklist, Item, Label, User, WipLimit | planned (v0.1.0) |
| `resolve.py` | name → object: board (alias, ID, title), list (title per swimlane), card (`cardNumber`), item (number or text) | planned (v0.1.0) |
| `output.py` | plain text, `--json`, later `--markdown` | planned (v0.1.0) |

## Data flow

1. `cli.py` parses the command and resolves the board (`--board` > `WEKAN_BOARD` > `.wekan` > error).
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
- Auth failure: `401` on `/api/user`, but **`200` with an error body** (`"statusCode": 401`) on board routes.
- Unknown routes answer **`200` with HTML**, not 404.
- `GET /api/boards` is admin-only; use `GET /api/users/:userId/boards`.
- Collection GETs return reduced objects; the export and `GET /api/cards/:id` return full ones.
- WIP limits are only in the export: `{"value": 2, "enabled": true}` is hard (no `soft` key), `"soft": true` is soft.
  **The API doesn't enforce them**: the tool does.
- `POST` card ignores `labelIds`; set labels with a `PUT` afterwards. `labelIds` and `assignees` replace the whole list.
- Checklist item `PUT` needs a JSON body; one call can tick and rename. Item and card `DELETE` are hard deletes.
- A moved card goes to the top of its new list. Lists can't be ordered through the API.
- Checklist titles are Markdown: "1. Step" renders as "1." for every item; use "(1) Step".
