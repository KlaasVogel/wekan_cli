"""The write commands: each one changes the board, reads the change back from a fresh export, and reports it.

Nothing here knows about typer or printing; ``cli.py`` turns a ``Change`` into output. Every function gets the board
as it was just read (``Board``), so lookups and checks (WIP limits, "already there") use live data.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from wekan_cli.client import WekanClient
from wekan_cli.errors import NotFoundError, RefusedError, VerifyError
from wekan_cli.models import Board, Card, Checklist, Item, WList
from wekan_cli.resolve import find_checklist, find_items, find_label, find_list

#: Title of the checklist ``add-item`` creates on a card without one.
DEFAULT_CHECKLIST = "Steps"

#: "1. Step" or "1) Step" renders as an ordered list in Wekan, so every item shows as "1." (use "(1) Step").
_MARKDOWN_NUMBER = re.compile(r"^\s*\d+[.)]\s")
_ITEM_NUMBER = re.compile(r"^\s*\(\s*(\d+)\s*\)")


@dataclass
class Change:
    """One change (or a no-op), as reported to the user.

    Attributes:
        card: The card number.
        subject: What changed, e.g. ``"Steps: (2) Call the API"`` or ``"list"``.
        before: The old value (``None`` for something new).
        after: The new value.
        changed: False when nothing had to change (already ticked, already in that list).
        verified: True once a fresh export showed the new value.
        warnings: Things the user should know (soft WIP limit, Markdown-looking title).
    """

    card: int
    subject: str
    before: str | None
    after: str
    changed: bool = True
    verified: bool = False
    warnings: list[str] = field(default_factory=list[str])


def _card_path(board: Board, card: Card) -> str:
    return f"/api/boards/{board.id}/cards/{card.id}"


def _reread(client: WekanClient, board: Board) -> Board:
    return Board.from_export(client.export(board.id))


def _new_id(answer: Any) -> str:
    """The ``_id`` from a create's answer, or "" when there is none."""
    return str(cast(dict[str, Any], answer).get("_id", "")) if isinstance(answer, dict) else ""


def _item_state(finished: bool) -> str:
    return "done" if finished else "open"


def _find_item(board: Board, item_id: str) -> Item | None:
    return next((i for cl in board.checklists for i in cl.items if i.id == item_id), None)


def _item_is(item_id: str, finished: bool) -> Callable[[Board], bool]:
    """A check: the item exists in a fresh export and has this state."""

    def check(fresh: Board) -> bool:
        item = _find_item(fresh, item_id)
        return item is not None and item.finished == finished

    return check


def _verify(changes: list[Change], checks: list[Callable[[Board], bool]], fresh: Board) -> None:
    """Mark changes verified, or raise ``VerifyError`` naming the ones a fresh export doesn't show."""
    failed: list[str] = []
    for change, check in zip(changes, checks, strict=True):
        change.verified = check(fresh)
        if change.changed and not change.verified:
            failed.append(f"#{change.card} {change.subject}" if change.card else change.subject)
    if failed:
        raise VerifyError("sent, but a fresh read doesn't show the change: " + ", ".join(failed))


# --- add-item -----------------------------------------------------------------------------------------------------


def _pick_checklist(board: Board, card: Card, name: str | None) -> tuple[Checklist | None, str]:
    """The checklist to add to, or None plus the title of the one to create."""
    if name is not None:
        found = find_checklist(board, card, name)
        return found, found.title if found else name
    checklists = board.checklists_of(card.id)
    if not checklists:
        return None, DEFAULT_CHECKLIST
    if len(checklists) > 1:
        titles = ", ".join(cl.title for cl in checklists)
        raise RefusedError(f"#{card.number} has several checklists ({titles}); pick one with --checklist")
    return checklists[0], checklists[0].title


def next_number(checklist: Checklist | None) -> int:
    """The next free ``(N)`` on a checklist: one more than the highest number in use, or 1."""
    numbers = [int(m.group(1)) for i in (checklist.items if checklist else ()) if (m := _ITEM_NUMBER.match(i.title))]
    return max(numbers, default=0) + 1


def add_item(
    client: WekanClient,
    board: Board,
    card: Card,
    text: str,
    done: bool = False,
    checklist_name: str | None = None,
    numbered: bool = False,
) -> Change:
    """Add an item to a card's checklist, creating the checklist when the card has none (or none by that name).

    Args:
        client: The API client.
        board: The board as just read.
        card: The card.
        text: The item title.
        done: Add it ticked.
        checklist_name: Which checklist; default: the card's only one, or a new "Steps".
        numbered: Put the next free ``(N)`` in front.

    Returns:
        The change, verified.

    Raises:
        RefusedError: The card has several checklists and none was named.
        VerifyError: The item isn't in a fresh export.
    """
    checklist, checklist_title = _pick_checklist(board, card, checklist_name)
    title = f"({next_number(checklist)}) {text}" if numbered else text
    change = Change(card.number, f"{checklist_title}: {title}", None, _item_state(done))
    if _MARKDOWN_NUMBER.match(title):
        change.warnings.append(f"{title!r} renders as a numbered list in Wekan (every item shows as 1.); use '(1) …'")
    if checklist is None:
        created = client.post(f"{_card_path(board, card)}/checklists", {"title": checklist_title})
        checklist_id = _new_id(created)
        if not checklist_id:
            raise VerifyError(f"#{card.number}: Wekan didn't return the new checklist's ID")
        change.warnings.append(f"created checklist {checklist_title!r}")
    else:
        checklist_id = checklist.id
    items_path = f"{_card_path(board, card)}/checklists/{checklist_id}/items"
    created = client.post(items_path, {"title": title})
    item_id = _new_id(created)
    if not item_id:
        raise VerifyError(f"#{card.number}: Wekan didn't return the new item's ID")
    if done:
        client.put(f"{items_path}/{item_id}", {"isFinished": True})

    def check(fresh: Board) -> bool:
        item = _find_item(fresh, item_id)
        return item is not None and item.title == title and item.finished == done

    _verify([change], [check], _reread(client, board))
    return change


# --- tick ---------------------------------------------------------------------------------------------------------


def tick(
    client: WekanClient,
    board: Board,
    card: Card,
    patterns: list[str],
    undo: bool = False,
    all_matches: bool = False,
) -> list[Change]:
    """Tick (or untick) checklist items. Items already in the wanted state are reported, not sent.

    Args:
        client: The API client.
        board: The board as just read.
        card: The card.
        patterns: Match strings (see ``resolve.find_items``).
        undo: Untick instead.
        all_matches: Accept a pattern that fits several items.

    Returns:
        One change per matched item.

    Raises:
        NotFoundError: A pattern matches nothing.
        AmbiguousError: A pattern matches several items and ``all_matches`` is off.
        VerifyError: A fresh export doesn't show a change.
    """
    wanted = not undo
    changes: list[Change] = []
    checks: list[Callable[[Board], bool]] = []
    for match in find_items(board, card, patterns, all_matches):
        item = match.item
        change = Change(
            card.number,
            f"{match.checklist.title}: {item.title}",
            _item_state(item.finished),
            _item_state(wanted),
            changed=item.finished != wanted,
        )
        if change.changed:
            path = f"{_card_path(board, card)}/checklists/{match.checklist.id}/items/{item.id}"
            client.put(path, {"isFinished": wanted})
        changes.append(change)
        checks.append(_item_is(item.id, wanted))
    _verify(changes, checks, _reread(client, board))
    return changes


def _wip_check(board: Board, target: WList, over_wip: bool, verb: str) -> list[str]:
    """Refuse a card into a full hard-limited list (unless ``over_wip``); return a warning for a full list.

    The API ignores WIP limits, so the tool keeps to them, as the browser does for people.
    """
    if target.wip is None:
        return []
    count = len(board.cards_in(target.id))
    if count < target.wip.value:
        return []
    full = f"{target.title} is full ({count}/{target.wip.value}"
    if target.wip.hard and not over_wip:
        raise RefusedError(f"{full}, hard limit); finish a card there first, or use --over-wip")
    kind = f"hard limit, {verb} with --over-wip" if target.wip.hard else "soft limit"
    return [f"{full}, {kind})"]


# --- move ---------------------------------------------------------------------------------------------------------


def move(
    client: WekanClient,
    board: Board,
    card: Card,
    to_list: str,
    from_list: str | None = None,
    swimlane: str | None = None,
    over_wip: bool = False,
) -> Change:
    """Move a card to another list, keeping to the WIP limits (the API itself ignores them).

    Args:
        client: The API client.
        board: The board as just read.
        card: The card.
        to_list: Title of the target list.
        from_list: Only move when the card is in this list now.
        swimlane: Swimlane title, when the target title repeats across swimlanes.
        over_wip: Move into a full hard-limited list anyway (an exception someone OK'd).

    Returns:
        The change (``changed`` False when the card is already there).

    Raises:
        RefusedError: ``from_list`` doesn't match, or the target's hard WIP limit is reached.
        VerifyError: A fresh export doesn't show the card in the target list.
    """
    target = find_list(board, to_list, swimlane)
    current = board.list_by_id(card.list_id)
    current_title = current.title if current else card.list_id
    if from_list is not None:
        expected = find_list(board, from_list, swimlane)
        if expected.id != card.list_id:
            raise RefusedError(f"#{card.number} is in {current_title}, not in {expected.title}; nothing moved")
    change = Change(card.number, "list", current_title, target.title, changed=card.list_id != target.id)
    if not change.changed:
        change.verified = True
        return change
    change.warnings.extend(_wip_check(board, target, over_wip, "moved"))
    body: dict[str, str] = {"listId": target.id}
    if target.swimlane_id and target.swimlane_id != card.swimlane_id:
        body["swimlaneId"] = target.swimlane_id
    client.put(f"/api/boards/{board.id}/lists/{card.list_id}/cards/{card.id}", body)

    def check(fresh: Board) -> bool:
        moved = next((c for c in fresh.cards if c.id == card.id), None)
        return moved is not None and moved.list_id == target.id

    _verify([change], [check], _reread(client, board))
    return change


# --- describe -----------------------------------------------------------------------------------------------------


def _lines(text: str) -> str:
    count = len(text.strip().splitlines())
    return "empty" if count == 0 else f"{count} line{'s' if count != 1 else ''}"


def describe(client: WekanClient, board: Board, card: Card, text: str) -> Change:
    """Replace a card's description.

    Args:
        client: The API client.
        board: The board as just read.
        card: The card.
        text: The new description (Markdown).

    Returns:
        The change (``changed`` False when the text is the same), with line counts as before/after.

    Raises:
        NotFoundError: The card's list is gone (the card moved while this ran).
        VerifyError: A fresh export shows a different description.
    """
    new = text.rstrip()
    change = Change(card.number, "description", _lines(card.description), _lines(new))
    if card.description.rstrip() == new.rstrip():
        change.changed = False
        change.verified = True
        return change
    if board.list_by_id(card.list_id) is None:
        raise NotFoundError(f"#{card.number}: its list isn't on the board")
    # Wekan answers an empty description with 404 {"message": "Error"}; a single space clears it.
    client.put(f"/api/boards/{board.id}/lists/{card.list_id}/cards/{card.id}", {"description": new or " "})

    def check(fresh: Board) -> bool:
        updated = next((c for c in fresh.cards if c.id == card.id), None)
        return updated is not None and updated.description.rstrip() == new.rstrip()

    _verify([change], [check], _reread(client, board))
    return change


# --- new-card -----------------------------------------------------------------------------------------------------


def new_card(
    client: WekanClient,
    board: Board,
    list_title: str,
    title: str,
    description: str = "",
    labels: list[str] | None = None,
    swimlane: str | None = None,
    force: bool = False,
    over_wip: bool = False,
) -> Change:
    """Create a card at the top of a list, with the logged-in account as its author.

    Args:
        client: The API client.
        board: The board as just read.
        list_title: The list to create it in.
        title: The card title.
        description: Its description (Markdown), or "".
        labels: Label names to put on it.
        swimlane: Swimlane title, when the list title repeats across swimlanes.
        force: Create it even when a card with this title exists.
        over_wip: Create it in a full hard-limited list anyway.

    Returns:
        The change; ``card`` holds the new card's number.

    Raises:
        RefusedError: A card with this title exists (without ``force``), or the list's hard WIP limit is reached.
        NotFoundError: The list or a label doesn't exist.
        VerifyError: The card isn't in a fresh export as asked.
    """
    target = find_list(board, list_title, swimlane)
    twin = next((c for c in board.cards if not c.archived and c.title.casefold() == title.strip().casefold()), None)
    if twin is not None and not force:
        raise RefusedError(f"#{twin.number} already has the title {title!r}; use --force to make a second one")
    label_ids = [find_label(board, name).id for name in labels or []]
    change = Change(0, title, None, target.title)
    change.warnings.extend(_wip_check(board, target, over_wip, "created"))
    lane_id = target.swimlane_id or next((s.id for s in board.swimlanes if not s.archived), "")
    body: dict[str, str] = {"title": title, "authorId": client.user_id, "swimlaneId": lane_id}
    if description.strip():
        body["description"] = description.rstrip()
    card_id = _new_id(client.post(f"/api/boards/{board.id}/lists/{target.id}/cards", body))
    if not card_id:
        raise VerifyError(f"{title!r}: Wekan didn't return the new card's ID")
    if label_ids:
        # POST ignores labelIds: set them with a PUT afterwards.
        client.put(f"/api/boards/{board.id}/lists/{target.id}/cards/{card_id}", {"labelIds": label_ids})

    def check(fresh: Board) -> bool:
        created = next((c for c in fresh.cards if c.id == card_id), None)
        if created is None:
            return False
        change.card = created.number  # Wekan numbers the card; known only after the read-back
        return created.title == title and created.list_id == target.id and set(created.label_ids) == set(label_ids)

    _verify([change], [check], _reread(client, board))
    return change


# --- label --------------------------------------------------------------------------------------------------------


def label(client: WekanClient, board: Board, card: Card, name: str, remove: bool = False) -> Change:
    """Put a label on a card, or take it off. The other labels stay (Wekan replaces the whole set on a ``PUT``).

    Args:
        client: The API client.
        board: The board as just read.
        card: The card.
        name: The label name (or colour, for a label without a name).
        remove: Take the label off instead.

    Returns:
        The change (``changed`` False when the card already has, or lacks, the label).

    Raises:
        NotFoundError: No such label on the board.
        VerifyError: A fresh export shows a different set of labels.
    """
    found = find_label(board, name)
    has = found.id in card.label_ids
    change = Change(
        card.number, f"label {found.name or found.color}", "on" if has else "off", "off" if remove else "on"
    )
    change.changed = has == remove
    if not change.changed:
        change.verified = True
        return change
    new_ids = [i for i in card.label_ids if i != found.id] if remove else [*card.label_ids, found.id]
    client.put(f"/api/boards/{board.id}/lists/{card.list_id}/cards/{card.id}", {"labelIds": new_ids})

    def check(fresh: Board) -> bool:
        updated = next((c for c in fresh.cards if c.id == card.id), None)
        return updated is not None and set(updated.label_ids) == set(new_ids)

    _verify([change], [check], _reread(client, board))
    return change


# --- delete-item --------------------------------------------------------------------------------------------------


def delete_item(client: WekanClient, board: Board, card: Card, pattern: str, yes: bool = False) -> Change:
    """Delete one checklist item. Wekan's delete is a hard delete, so it needs ``yes``.

    Args:
        client: The API client.
        board: The board as just read.
        card: The card.
        pattern: Which item (see ``resolve.find_items``); it must match exactly one.
        yes: Really delete. Without it, nothing is sent and the refusal names the item.

    Returns:
        The change.

    Raises:
        NotFoundError: No item matches.
        AmbiguousError: Several items match.
        RefusedError: ``yes`` wasn't given.
        VerifyError: The item is still in a fresh export.
    """
    (match,) = find_items(board, card, [pattern])
    subject = f"{match.checklist.title}: {match.item.title}"
    if not yes:
        raise RefusedError(f"would delete #{card.number} {subject} (it can't be restored); add --yes to delete it")
    change = Change(card.number, subject, _item_state(match.item.finished), "deleted")
    client.delete(f"{_card_path(board, card)}/checklists/{match.checklist.id}/items/{match.item.id}")
    _verify([change], [lambda fresh: _find_item(fresh, match.item.id) is None], _reread(client, board))
    return change
