"""The ``wekan`` command: argument parsing and output only, no HTTP logic."""

import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from wekan_cli import __version__, actions
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
from wekan_cli.errors import INTERNAL_ERROR_EXIT_CODE, NotFoundError, WekanError
from wekan_cli.models import Board
from wekan_cli.output import (
    board_json,
    card_json,
    change_json,
    format_board,
    format_boards,
    format_card,
    format_change,
    to_json,
)
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
_CREDENTIALS_HELP = "Credentials file. Default: WEKAN_CREDENTIALS, then ~/.config/wekan/credentials."
# Typer only takes a global option before the command; every command repeats it, so `wekan boards --credentials F`
# works too. The command's value wins over the global one.
CredentialsOpt = Annotated[Path | None, typer.Option("--credentials", help=_CREDENTIALS_HELP)]
NumberArg = Annotated[int, typer.Argument(help="Card number, as shown on the board (#14 → 14).")]


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
    credentials: CredentialsOpt = None,
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    """Work with a self-hosted Wekan board from the command line."""
    ctx.obj = State(credentials=credentials)


# --- helpers ------------------------------------------------------------------------------------------------------


def _credentials_override(ctx: typer.Context, override: Path | None) -> Path | None:
    return override if override is not None else _state(ctx).credentials


def _load_credentials(ctx: typer.Context, override: Path | None = None) -> Credentials:
    creds = load_credentials(_credentials_override(ctx, override))
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
def whoami(ctx: typer.Context, ids: IdsOpt = False, credentials: CredentialsOpt = None) -> None:
    """Log in (or reuse the cached token) and show the account and server.

    Example: wekan whoami
    """
    creds = _load_credentials(ctx, credentials)
    with make_client(creds) as client:
        me = client.me()
    user_id = f" ({me.get('_id', '')})" if ids else ""
    typer.echo(f"{me.get('username', creds.username)} on {creds.url}{user_id}")


@app.command()
def boards(ctx: typer.Context, json: JsonOpt = False, ids: IdsOpt = False, credentials: CredentialsOpt = None) -> None:
    """List the boards this account is a member of.

    Example: wekan boards
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
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
    credentials: CredentialsOpt = None,
) -> None:
    """Show a board: its lists (with WIP limits) and their cards.

    Example: wekan board -b my-board
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
    typer.echo(to_json(board_json(data, archived)) if json else format_board(data, archived, ids))


@app.command()
def card(
    ctx: typer.Context,
    number: NumberArg,
    board: BoardOpt = None,
    archived: ArchivedOpt = False,
    json: JsonOpt = False,
    ids: IdsOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Show a card: list, labels, description and every checklist with its items.

    Example: wekan card 14
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
    found = find_card(data, number, include_archived=archived)
    typer.echo(to_json(card_json(data, found)) if json else format_card(data, found, ids))


@app.command()
def config(ctx: typer.Context, board: BoardOpt = None, credentials: CredentialsOpt = None) -> None:
    """Show the settings in use and where each one comes from. Never shows the password or the token.

    Example: wekan config
    """
    override = _credentials_override(ctx, credentials)
    path, source = credentials_path(override)
    lines = [f"credentials: {path} ({source})"]
    if path.exists():
        lines[0] += "" if is_private(path) else "  WARNING: readable by others, run chmod 600"
        try:
            creds = load_credentials(override)
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


# --- write commands -----------------------------------------------------------------------------------------------


def _echo_changes(changes: list[actions.Change], json: bool, single: bool) -> None:
    if json:
        data = [change_json(c) for c in changes]
        typer.echo(to_json(data[0] if single else data))
    else:
        typer.echo("\n".join(format_change(c) for c in changes))


def _read_text(source: str) -> str:
    """Read a file, or stdin for ``-``."""
    if source == "-":
        return typer.get_text_stream("stdin").read()
    path = Path(source).expanduser()
    if not path.is_file():
        raise NotFoundError(f"no file {source}")
    return path.read_text(encoding="utf-8")


@app.command("add-item")
def add_item(
    ctx: typer.Context,
    number: NumberArg,
    text: Annotated[str, typer.Argument(help="The item's title.")],
    done: Annotated[bool, typer.Option("--done", help="Add it ticked.")] = False,
    checklist: Annotated[
        str | None,
        typer.Option("--checklist", help="Checklist title. Default: the card's only one, or a new 'Steps'."),
    ] = None,
    numbered: Annotated[bool, typer.Option("--numbered", help="Put the next free (N) in front.")] = False,
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Add a checklist item to a card.

    Example: wekan add-item 14 "Write the tests" --numbered
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        change = actions.add_item(client, data, find_card(data, number), text, done, checklist, numbered)
    _echo_changes([change], json, single=True)


@app.command()
def tick(
    ctx: typer.Context,
    number: NumberArg,
    match: Annotated[
        list[str], typer.Argument(help="Items to tick: a number N matches '(N) …', other text part of the title.")
    ],
    undo: Annotated[bool, typer.Option("--undo", help="Untick instead.")] = False,
    all_matches: Annotated[bool, typer.Option("--all", help="Tick every item a match fits.")] = False,
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Tick (or untick) checklist items on a card, across all its checklists.

    Example: wekan tick 14 2 3
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        changes = actions.tick(client, data, find_card(data, number), match, undo, all_matches)
    _echo_changes(changes, json, single=False)


@app.command()
def move(
    ctx: typer.Context,
    number: NumberArg,
    to_list: Annotated[str, typer.Argument(metavar="LIST", help="Target list title (case-insensitive).")],
    from_list: Annotated[
        str | None, typer.Option("--from", help="Only move when the card is in this list now.")
    ] = None,
    swimlane: Annotated[
        str | None, typer.Option("--swimlane", help="Swimlane, when the list title repeats across swimlanes.")
    ] = None,
    over_wip: Annotated[
        bool, typer.Option("--over-wip", help="Move into a full hard-limited list anyway (an OK'd exception).")
    ] = False,
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Move a card to another list. A full hard WIP limit refuses the move (exit 7); a soft one warns.

    Example: wekan move 14 Doing --from "To Do"
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        change = actions.move(client, data, find_card(data, number), to_list, from_list, swimlane, over_wip)
    _echo_changes([change], json, single=True)


@app.command()
def describe(
    ctx: typer.Context,
    number: NumberArg,
    file: Annotated[str, typer.Option("--file", help="File with the new description (Markdown), or - for stdin.")],
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Replace a card's description.

    Example: wekan describe 14 --file notes.md
    """
    text = _read_text(file)
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        change = actions.describe(client, data, find_card(data, number), text)
    _echo_changes([change], json, single=True)


@app.command("new-card")
def new_card(
    ctx: typer.Context,
    to_list: Annotated[str, typer.Argument(metavar="LIST", help="List title (case-insensitive).")],
    title: Annotated[str, typer.Argument(help="The card's title.")],
    file: Annotated[
        str | None, typer.Option("--file", help="File with the description (Markdown), or - for stdin.")
    ] = None,
    labels: Annotated[str | None, typer.Option("--labels", help="Labels to put on it, comma-separated.")] = None,
    swimlane: Annotated[
        str | None, typer.Option("--swimlane", help="Swimlane, when the list title repeats across swimlanes.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Create it even when a card has this title.")] = False,
    over_wip: Annotated[
        bool, typer.Option("--over-wip", help="Create it in a full hard-limited list anyway (an OK'd exception).")
    ] = False,
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Create a card at the top of a list, with you as its author. Refuses a duplicate title (exit 7).

    Example: wekan new-card Backlog "Write the docs" --labels Docs --file card.md
    """
    description = _read_text(file) if file is not None else ""
    names = [n.strip() for n in labels.split(",") if n.strip()] if labels else []
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        change = actions.new_card(client, data, to_list, title, description, names, swimlane, force, over_wip)
    _echo_changes([change], json, single=True)


@app.command()
def label(
    ctx: typer.Context,
    number: NumberArg,
    name: Annotated[str, typer.Argument(metavar="LABEL", help="Label name (or colour, for a label without one).")],
    remove: Annotated[bool, typer.Option("--remove", help="Take the label off instead.")] = False,
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Put a label on a card (or take it off with --remove). Its other labels stay.

    Example: wekan label 14 PR
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        change = actions.label(client, data, find_card(data, number), name, remove)
    _echo_changes([change], json, single=True)


@app.command("delete-item")
def delete_item(
    ctx: typer.Context,
    number: NumberArg,
    match: Annotated[str, typer.Argument(help="The item: a number N matches '(N) …', other text part of the title.")],
    yes: Annotated[bool, typer.Option("--yes", help="Really delete it (it can't be restored).")] = False,
    board: BoardOpt = None,
    json: JsonOpt = False,
    credentials: CredentialsOpt = None,
) -> None:
    """Delete one checklist item. Without --yes it only says what it would delete (exit 7).

    Example: wekan delete-item 14 3 --yes
    """
    with make_client(_load_credentials(ctx, credentials)) as client:
        data = _open_board(client, board)
        change = actions.delete_item(client, data, find_card(data, number), match, yes)
    _echo_changes([change], json, single=True)


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
