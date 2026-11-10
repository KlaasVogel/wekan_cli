"""Turn the names people use into Wekan objects: a board by alias, ID or title; a card by its number."""

from typing import Any

from wekan_cli.config import Aliases
from wekan_cli.errors import AmbiguousError, NotFoundError
from wekan_cli.models import Board, Card


def resolve_board(ref: str, boards: list[dict[str, Any]], aliases: Aliases) -> tuple[str, str]:
    """Find a board by alias, ID or title (case-insensitive), among the boards the account can see.

    Args:
        ref: What the user gave.
        boards: The account's boards (``_id`` and ``title``), from ``GET /api/users/:id/boards``.
        aliases: Board aliases from ``config.toml``.

    Returns:
        The board's ID and title.

    Raises:
        NotFoundError: No board matches, or an alias points to a board the account can't see.
        AmbiguousError: Several boards have this title.
    """
    by_id = {str(b["_id"]): str(b.get("title", "")) for b in boards}
    alias_target = aliases.boards.get(ref) or aliases.boards.get(ref.lower())
    if alias_target is not None:
        if alias_target not in by_id:
            raise NotFoundError(f"alias {ref!r} points to board {alias_target}, which this account can't see")
        return alias_target, by_id[alias_target]
    if ref in by_id:
        return ref, by_id[ref]
    matches = [(bid, title) for bid, title in by_id.items() if title.casefold() == ref.casefold()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(bid for bid, _ in matches)
        raise AmbiguousError(f"{len(matches)} boards are called {ref!r} ({ids}); use the ID or an alias")
    raise NotFoundError(f"no board {ref!r} (wekan boards lists the ones this account can see)")


def find_card(board: Board, number: int, include_archived: bool = False) -> Card:
    """Find a card by its number (the ``#14`` shown on the board).

    Args:
        board: The board, from its export.
        number: The card number.
        include_archived: Also return an archived card.

    Returns:
        The card.

    Raises:
        NotFoundError: No such card, or it's archived (and ``include_archived`` is off). Card deletes through the
            API are hard deletes, so a deleted card simply isn't there any more.
    """
    for card in board.cards:
        if card.number == number:
            if card.archived and not include_archived:
                raise NotFoundError(f"#{number} on board {board.title} is archived (use --archived to see it)")
            return card
    raise NotFoundError(f"no #{number} on board {board.title}")
