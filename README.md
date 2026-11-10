# wekan-cli

A command-line tool for a self-hosted [Wekan](https://wekan.github.io/) board: read boards and cards, tick checklist
items, move cards, all addressed the way people do (card `#14`, list `Doing`, item `(2)`). Short plain-text output by
default, `--json` for scripts, and distinct exit codes, so both people and coding agents can use it.

**Status: early development.** v0.1.0 reads boards and cards; v0.2.0 (in progress) changes them. See
`docs/changelog/`.

## Usage

```bash
wekan whoami                 # check the login
wekan boards                 # boards this account is a member of
wekan board -b "My Board"    # lists (with WIP limits) and cards
wekan card 14 -b "My Board"  # one card: description, checklists, items
wekan card 14 --json         # the same as JSON
wekan config                 # which settings are used, and where they come from

wekan add-item 14 "Write the tests" --numbered   # adds "(4) Write the tests"
wekan tick 14 2 3            # tick items (2) and (3); --undo to untick
wekan move 14 Doing --from "To Do"               # refuses a full hard WIP limit (--over-wip to override)
wekan describe 14 --file notes.md                # replace the description (- reads stdin)
```

Every change is read back and printed as `from → to (verified)`. Options such as `--board` and `--credentials` can go
after the command.

Pick the board with `--board/-b` (an alias, the board ID, or its title), the `WEKAN_BOARD` environment variable, or a
`.wekan` file in the current folder or any folder above it:

```toml
board = "my-board"
```

Aliases live in `~/.config/wekan/config.toml`:

```toml
[boards]
my-board = "<board id>"

[users]
alice = "<user id>"
```

Exit codes: 0 ok, 1 bug, 2 usage, 3 not found, 4 ambiguous, 5 login/credentials, 6 network or server, 7 refused,
8 a change didn't show up when read back.

## Install (development)

```bash
git clone https://github.com/KlaasVogel/wekan_cli.git
cd wekan_cli
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Or as a command on your PATH, following your checkout: `pipx install -e .`

## Credentials

The tool reads a `KEY=VALUE` file (one per line, no quotes):

```
WEKAN_URL=https://wekan.example.com
WEKAN_USERNAME=your-user
WEKAN_PASSWORD=your-password
```

Where the tool looks, first match wins:

1. `--credentials PATH`
2. the `WEKAN_CREDENTIALS` environment variable (handy to give a coding agent its own account)
3. `~/.config/wekan/credentials`

Keep the folder at mode 700 and the file at 600. The tool never prints the password or the login token.

## Licence

MIT, see `LICENSE`.
