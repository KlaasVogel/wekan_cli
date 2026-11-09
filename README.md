# wekan-cli

A command-line tool for a self-hosted [Wekan](https://wekan.github.io/) board: read boards and cards, tick checklist
items, move cards, all addressed the way people do (card `#14`, list `Doing`, item `(2)`). Short plain-text output by
default, `--json` for scripts, and distinct exit codes, so both people and coding agents can use it.

**Status: early development.** Nothing works yet beyond `wekan --version`. See `docs/changelog/`.

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
