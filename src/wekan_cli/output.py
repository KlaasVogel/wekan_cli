"""Plain-text and JSON output. Short by default: agents read this, and every line costs tokens."""

import json
from dataclasses import asdict
from typing import Any

from wekan_cli.actions import Change
from wekan_cli.models import Board, Card, WList


def to_json(data: Any) -> str:
    """Serialise for ``--json`` (stable key order, UTF-8 kept readable)."""
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)


def _id(value: str, ids: bool) -> str:
    return f" ({value})" if ids else ""


def _list_header(board: Board, lst: WList, include_archived: bool, ids: bool) -> str:
    count = len(board.cards_in(lst.id, include_archived=False))
    wip = ""
    if lst.wip is not None:
        kind = "soft" if lst.wip.soft else "hard"
        flag = " FULL" if count >= lst.wip.value else ""
        wip = f" [{count}/{lst.wip.value} {kind}{flag}]"
    archived = " (archived)" if lst.archived else ""
    return f"== {lst.title}{wip}{archived}{_id(lst.id, ids)}"


def _card_line(board: Board, card: Card, ids: bool) -> str:
    parts = [f"#{card.number} {card.title}"]
    if card.label_ids:
        parts.append("[" + ", ".join(board.label_name(i) for i in card.label_ids) + "]")
    if card.assignee_ids:
        parts.append(" ".join("@" + board.username(u) for u in card.assignee_ids))
    if card.archived:
        parts.append("(archived)")
    return " ".join(parts) + _id(card.id, ids)


def format_boards(boards: list[dict[str, Any]], ids: bool) -> str:
    """One board per line, sorted by title."""
    rows = sorted(boards, key=lambda b: str(b.get("title", "")).casefold())
    return "\n".join(f"{b.get('title', '')}{_id(str(b['_id']), ids)}" for b in rows)


def format_board(board: Board, include_archived: bool, ids: bool) -> str:
    """Lists with their cards; one section per swimlane when there are several."""
    lines = [f"{board.title}{_id(board.id, ids)}"]
    swimlanes = [s for s in board.swimlanes if include_archived or not s.archived]
    many = len(swimlanes) > 1
    for swimlane in swimlanes or [None]:
        if many and swimlane is not None:
            lines.append(f"\n# {swimlane.title}{_id(swimlane.id, ids)}")
        for lst in board.lists:
            if lst.archived and not include_archived:
                continue
            if many and swimlane is not None and lst.swimlane_id != swimlane.id:
                continue
            lines.append("")
            lines.append(_list_header(board, lst, include_archived, ids))
            cards = board.cards_in(lst.id, include_archived)
            lines.extend(_card_line(board, c, ids) for c in cards)
    return "\n".join(lines)


def format_card(board: Board, card: Card, ids: bool) -> str:
    """A card with its list, labels, assignees, description and every checklist."""
    lst = board.list_by_id(card.list_id)
    lines = [f"#{card.number} {card.title}{_id(card.id, ids)}"]
    meta = [f"List: {lst.title if lst else '?'}"]
    if len(board.swimlanes) > 1:
        swimlane = next((s for s in board.swimlanes if s.id == card.swimlane_id), None)
        meta.append(f"Swimlane: {swimlane.title if swimlane else '?'}")
    if card.label_ids:
        meta.append("Labels: " + ", ".join(board.label_name(i) for i in card.label_ids))
    if card.assignee_ids:
        meta.append("Assignees: " + ", ".join(board.username(u) for u in card.assignee_ids))
    if card.archived:
        meta.append("ARCHIVED")
    lines.append(" | ".join(meta))
    if card.description.strip():
        lines.append("")
        lines.extend(card.description.rstrip().splitlines())
    for checklist in board.checklists_of(card.id):
        lines.append("")
        lines.append(f"{checklist.title} [{checklist.done}/{len(checklist.items)}]{_id(checklist.id, ids)}")
        for item in checklist.items:
            mark = "x" if item.finished else " "
            lines.append(f"  [{mark}] {item.title}{_id(item.id, ids)}")
    return "\n".join(lines)


def card_json(board: Board, card: Card) -> dict[str, Any]:
    """A card with names resolved, for ``--json``."""
    lst = board.list_by_id(card.list_id)
    return {
        "number": card.number,
        "id": card.id,
        "title": card.title,
        "list": lst.title if lst else None,
        "list_id": card.list_id,
        "swimlane_id": card.swimlane_id,
        "labels": [board.label_name(i) for i in card.label_ids],
        "assignees": [board.username(u) for u in card.assignee_ids],
        "archived": card.archived,
        "description": card.description,
        "checklists": [
            {
                "id": cl.id,
                "title": cl.title,
                "items": [{"id": i.id, "title": i.title, "finished": i.finished} for i in cl.items],
            }
            for cl in board.checklists_of(card.id)
        ],
    }


def board_json(board: Board, include_archived: bool) -> dict[str, Any]:
    """A board's lists and cards, for ``--json``."""
    return {
        "id": board.id,
        "title": board.title,
        "lists": [
            {
                "id": lst.id,
                "title": lst.title,
                "swimlane_id": lst.swimlane_id,
                "wip_limit": ({"value": lst.wip.value, "hard": lst.wip.hard} if lst.wip is not None else None),
                "cards": [
                    {
                        "number": c.number,
                        "id": c.id,
                        "title": c.title,
                        "labels": [board.label_name(i) for i in c.label_ids],
                        "assignees": [board.username(u) for u in c.assignee_ids],
                        "archived": c.archived,
                    }
                    for c in board.cards_in(lst.id, include_archived)
                ],
            }
            for lst in board.lists
            if include_archived or not lst.archived
        ],
    }


def format_change(change: Change) -> str:
    """One line per change: ``#2 Steps: (2) Call the API: open → done (verified)``, then any warnings.

    A no-op says so (``unchanged (done)``) instead of showing an arrow.
    """
    if not change.changed:
        line = f"#{change.card} {change.subject}: unchanged ({change.after})"
    else:
        before = change.before if change.before is not None else "new"
        line = f"#{change.card} {change.subject}: {before} → {change.after}"
        line += " (verified)" if change.verified else " (NOT verified)"
    return "\n".join([line, *(f"  warning: {w}" for w in change.warnings)])


def change_json(change: Change) -> dict[str, Any]:
    """A change as a dict, for ``--json``."""
    return asdict(change)
