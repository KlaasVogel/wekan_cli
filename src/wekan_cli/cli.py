"""The ``wekan`` command: argument parsing and output only, no HTTP logic."""

import os
import sys
import traceback
from typing import Annotated

import typer

from wekan_cli import __version__
from wekan_cli.errors import INTERNAL_ERROR_EXIT_CODE, WekanError

# Pretty exceptions are off: typer's rich tracebacks can show local variables, which may hold the password or the
# token. Errors are reported by main() instead.
app = typer.Typer(
    name="wekan",
    help="Work with a self-hosted Wekan board from the command line.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    add_completion=False,
    rich_markup_mode=None,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"wekan {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit.")
    ] = False,
) -> None:
    """Work with a self-hosted Wekan board from the command line."""


@app.command()
def version() -> None:
    """Show the version.

    Example: wekan version
    """
    typer.echo(f"wekan {__version__}")


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
