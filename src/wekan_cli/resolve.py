"""Turn the names people use into Wekan objects: a board by alias, ID or title; a card by its number; a list,
checklist or checklist item by (part of) its title."""

import re
from dataclasses import dataclass
from typing import Any

from wekan_cli.config import Aliases
from wekan_cli.errors import AmbiguousError, NotFoundError
from wekan_cli.models import Board, Card, Checklist, Item, WList


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


def find_list(board: Board, title: str, swimlane: str | None = None) -> WList:
    """Find a list by title (case-insensitive), skipping archived lists.

    Args:
        board: The board.
        title: The list title the user gave.
        swimlane: Swimlane title, to pick one of several lists with the same title.

    Returns:
        The list.

    Raises:
        NotFoundError: No such list (or swimlane).
        AmbiguousError: The title repeats across swimlanes and no swimlane was given.
    """
    matches = [lst for lst in board.lists if not lst.archived and lst.title.casefold() == title.casefold()]
    if not matches:
        names = ", ".join(lst.title for lst in board.lists if not lst.archived)
        raise NotFoundError(f"no list {title!r} on board {board.title} (lists: {names})")
    if swimlane is not None:
        lanes = {s.id for s in board.swimlanes if s.title.casefold() == swimlane.casefold()}
        if not lanes:
            raise NotFoundError(f"no swimlane {swimlane!r} on board {board.title}")
        # A list without a swimlane ID is shared by every swimlane.
        matches = [lst for lst in matches if lst.swimlane_id in lanes or not lst.swimlane_id]
        if not matches:
            raise NotFoundError(f"no list {title!r} in swimlane {swimlane!r}")
    if len(matches) > 1:
        lane_titles = {s.id: s.title for s in board.swimlanes}
        where = ", ".join(lane_titles.get(lst.swimlane_id, lst.swimlane_id or "?") for lst in matches)
        raise AmbiguousError(f"{len(matches)} lists are called {title!r} (swimlanes: {where}); use --swimlane")
    return matches[0]


def find_checklist(board: Board, card: Card, name: str) -> Checklist | None:
    """Find a card's checklist by title (case-insensitive).

    Args:
        board: The board.
        card: The card.
        name: The checklist title.

    Returns:
        The checklist, or None when the card has none by that name.
    """
    return next((cl for cl in board.checklists_of(card.id) if cl.title.casefold() == name.casefold()), None)


@dataclass(frozen=True)
class ItemMatch:
    """A checklist item with the checklist it's on."""

    checklist: Checklist
    item: Item


def _matches(title: str, pattern: str) -> bool:
    if pattern.isdigit():
        # A bare number means the item numbered "(N)", so "2" doesn't also hit "(12)" or "2 tests".
        return re.match(rf"\(\s*{int(pattern)}\s*\)", title.strip()) is not None
    return pattern.casefold() in title.casefold()


def find_items(board: Board, card: Card, patterns: list[str], all_matches: bool = False) -> list[ItemMatch]:
    """Find checklist items on a card, across all its checklists.

    A bare number ``2`` matches an item that starts with ``(2)``. Anything else matches part of the title,
    case-insensitive.

    Args:
        board: The board.
        card: The card.
        patterns: One or more match strings.
        all_matches: Accept a pattern that fits several items (all of them are returned).

    Returns:
        The matching items, in checklist order, each once.

    Raises:
        NotFoundError: A pattern matches nothing.
        AmbiguousError: A pattern matches several items and ``all_matches`` is off; the message lists them.
    """
    everything = [ItemMatch(cl, item) for cl in board.checklists_of(card.id) for item in cl.items]
    found: list[ItemMatch] = []
    for pattern in patterns:
        hits = [m for m in everything if _matches(m.item.title, pattern)]
        if not hits:
            raise NotFoundError(f"no item matching {pattern!r} on #{card.number}")
        if len(hits) > 1 and not all_matches:
            listed = "; ".join(f"{m.checklist.title}: {m.item.title}" for m in hits)
            raise AmbiguousError(
                f"{len(hits)} items on #{card.number} match {pattern!r} ({listed}); be more specific or use --all"
            )
        found.extend(m for m in hits if m not in found)
    return found
