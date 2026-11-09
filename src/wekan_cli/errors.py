"""Errors the tool reports, each with its own exit code.

Every error the user should see is a ``WekanError``. Its message must be safe to print: it never contains a
password, a token, or a request header.
"""

from typing import ClassVar


class WekanError(Exception):
    """Base class for errors that end the command with one short line on stderr."""

    exit_code: ClassVar[int] = 1


class NotFoundError(WekanError):
    """A board, list, card or checklist item doesn't exist (or is archived)."""

    exit_code = 3


class AmbiguousError(WekanError):
    """A name or match fits more than one thing; the message lists the candidates."""

    exit_code = 4


class AuthError(WekanError):
    """Login failed, or the account has no access."""

    exit_code = 5


class NetworkError(WekanError):
    """Wekan couldn't be reached, or answered with a server error."""

    exit_code = 6


class RefusedError(WekanError):
    """The tool refused a change (hard WIP limit, ``--from`` mismatch, duplicate card, missing ``--yes``)."""

    exit_code = 7


class VerifyError(WekanError):
    """A change was sent, but reading it back didn't show it."""

    exit_code = 8


#: Exit code for an unexpected error (a bug): one line naming the exception type, no traceback.
INTERNAL_ERROR_EXIT_CODE = 1
