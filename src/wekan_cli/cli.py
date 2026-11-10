"""The ``wekan`` command: argument parsing and output only, no HTTP logic."""

import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from wekan_cli import __version__
from wekan_cli.cache import TokenCache
from wekan_cli.client import WekanClient
from wekan_cli.config import (
    Credentials,
    board_ref,
    credentials_path,
    is_private,
    load_aliases,
    load_credentials,
)
from wekan_cli.errors import INTERNAL_ERROR_EXIT_CODE, WekanError
from wekan_cli.models import Board
from wekan_cli.output import board_json, card_json, format_board, format_boards, format_card, to_json
from wekan_cli.resolve import find_card, resolve_board

# Pretty exceptions are off: typer's rich tracebacks can show local variables, which may hold the password or the
# token. Errors are reported by main() instead. Plain help (no rich boxes) keeps --help cheap for agents.
app = typer.Typer(
    name="wekan",
    help="Work with a self-hosted Wekan board from the command line.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    add_completion=False,
    rich_markup_mode=None,
)

BoardOpt = Annotated[
    str | None,
    typer.Option("--board", "-b", help="Board alias, ID or title. Default: WEKAN_BOARD, then a .wekan file."),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print JSON instead of text.")]
IdsOpt = Annotated[bool, typer.Option("--ids", help="Show Wekan IDs.")]
ArchivedOpt = Annotated[bool, typer.Option("--archived", help="Include archived cards and lists.")]


@dataclass
class State:
    """Global options, shared by all commands."""

    credentials: Path | None = None


def _state(ctx: typer.Context) -> State:
    obj = ctx.find_root().obj
    return obj if isinstance(obj, State) else State()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"wekan {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    credentials: Annotated[
        Path | None,
        typer.Option(
            "--credentials", help="Credentials file. Default: WEKAN_CREDENTIALS, then ~/.config/wekan/credentials."
        ),
    ] = None,
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    """Work with a self-hosted Wekan board from the command line."""
    ctx.obj = State(credentials=credentials)


# --- helpers ------------------------------------------------------------------------------------------------------


def _load_credentials(ctx: typer.Context) -> Credentials:
    creds = load_credentials(_state(ctx).credentials)
    if not is_private(creds.path):
        typer.echo(f"warning: {creds.path} is readable by others; run: chmod 600 {creds.path}", err=True)
    return creds


def make_client(credentials: Credentials) -> WekanClient:
    """Create the API client (tests replace this to use a fake Wekan)."""
    return WekanClient(credentials)


def _open_board(client: WekanClient, board: str | None) -> Board:
    ref = board_ref(board)
    board_id, _title = resolve_board(ref.value, client.boards(), load_aliases())
    return Board.from_export(client.export(board_id))


# --- commands -----------------------------------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Show the version.

    Example: wekan version
    """
    typer.echo(f"wekan {__version__}")


@app.command()
def whoami(ctx: typer.Context, ids: IdsOpt = False) -> None:
    """Log in (or reuse the cached token) and show the account and server.

    Example: wekan whoami
    """
    creds = _load_credentials(ctx)
    with make_client(creds) as client:
        me = client.me()
    user_id = f" ({me.get('_id', '')})" if ids else ""
    typer.echo(f"{me.get('username', creds.username)} on {creds.url}{user_id}")


@app.command()
def boards(ctx: typer.Context, json: JsonOpt = False, ids: IdsOpt = False) -> None:
    """List the boards this account is a member of.

    Example: wekan boards
    """
    with make_client(_load_credentials(ctx)) as client:
        rows = client.boards()
    if json:
        typer.echo(to_json([{"id": b["_id"], "title": b.get("title", "")} for b in rows]))
    else:
        typer.echo(format_boards(rows, ids))


@app.command()
def board(
    ctx: typer.Context,
    board: BoardOpt = None,
    archived: ArchivedOpt = False,
    json: JsonOpt = False,
    ids: IdsOpt = False,
) -> None:
    """Show a board: its lists (with WIP limits) and their cards.

    Example: wekan board -b my-board
    """
    with make_client(_load_credentials(ctx)) as client:
        data = _open_board(client, board)
    typer.echo(to_json(board_json(data, archived)) if json else format_board(data, archived, ids))


@app.command()
def card(
    ctx: typer.Context,
    number: Annotated[int, typer.Argument(help="Card number, as shown on the board (#14 → 14).")],
    board: BoardOpt = None,
    archived: ArchivedOpt = False,
    json: JsonOpt = False,
    ids: IdsOpt = False,
) -> None:
    """Show a card: list, labels, description and every checklist with its items.

    Example: wekan card 14
    """
    with make_client(_load_credentials(ctx)) as client:
        data = _open_board(client, board)
    found = find_card(data, number, include_archived=archived)
    typer.echo(to_json(card_json(data, found)) if json else format_card(data, found, ids))


@app.command()
def config(ctx: typer.Context, board: BoardOpt = None) -> None:
    """Show the settings in use and where each one comes from. Never shows the password or the token.

    Example: wekan config
    """
    path, source = credentials_path(_state(ctx).credentials)
    lines = [f"credentials: {path} ({source})"]
    if path.exists():
        lines[0] += "" if is_private(path) else "  WARNING: readable by others, run chmod 600"
        try:
            creds = load_credentials(_state(ctx).credentials)
            lines += [f"url: {creds.url}", f"username: {creds.username}", "password: set"]
            cached = TokenCache().load(creds.url, creds.username)
            expires = f", expires {cached.expires}" if cached and cached.expires else ""
            lines.append(f"token: {'cached' + expires if cached else 'none cached (next command logs in)'}")
        except WekanError as exc:
            lines.append(f"credentials problem: {exc}")
    else:
        lines.append("credentials problem: file not found")
    aliases = load_aliases()
    if aliases.path is None:
        lines.append("aliases: none (no config.toml)")
    else:
        lines.append(f"aliases: {aliases.path} ({len(aliases.boards)} boards, {len(aliases.users)} users)")
    try:
        ref = board_ref(board)
        target = aliases.boards.get(ref.value)
        lines.append(f"board: {ref.value}{f' -> {target}' if target else ''} (from {ref.source})")
    except WekanError as exc:
        lines.append(f"board: none ({exc})")
    typer.echo("\n".join(lines))


def main() -> None:
    """Entry point: run the app and turn errors into one stderr line and an exit code.

    Known errors (``WekanError``) print their message. Anything else is a bug: only the exception type is printed,
    never its message or a traceback, because either could hold a secret. Set ``WEKAN_DEBUG=1`` to get a plain
    traceback (still without local variables).
    """
    try:
        app()
    except WekanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except Exception as exc:
        if os.environ.get("WEKAN_DEBUG") == "1":
            traceback.print_exception(exc, file=sys.stderr)
        else:
            print(f"internal error: {type(exc).__name__} (set WEKAN_DEBUG=1 for details)", file=sys.stderr)
        sys.exit(INTERNAL_ERROR_EXIT_CODE)
