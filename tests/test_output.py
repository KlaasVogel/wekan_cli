"""Tests for the text and JSON output."""

import json

from fakewekan import load_fixture

from wekan_cli.actions import Change
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

BOARD = Board.from_export(load_fixture("board_export.json"))


def test_boards_sorted_by_title() -> None:
    rows = [{"_id": "2", "title": "beta"}, {"_id": "1", "title": "Alpha"}]
    assert format_boards(rows, ids=False) == "Alpha\nbeta"
    assert format_boards(rows, ids=True).splitlines()[0] == "Alpha (1)"


def test_board_text() -> None:
    text = format_board(BOARD, include_archived=False, ids=False)
    assert "== Doing [1/2 hard]" in text
    assert "== Waiting [0/5 soft]" in text
    assert "#2 Write the first command [Robot]" in text
    assert "#4" not in text  # archived
    assert "(" not in text.split("\n")[0]  # no IDs by default


def test_board_text_archived_and_ids() -> None:
    text = format_board(BOARD, include_archived=True, ids=True)
    assert "#4 An old idea (archived) (cardFour000000001)" in text


def test_full_list_is_flagged() -> None:
    data = load_fixture("board_export.json")
    data["cards"][2]["listId"] = "listDoing00000001"  # a second card in Doing (limit 2)
    assert "== Doing [2/2 hard FULL]" in format_board(Board.from_export(data), False, False)


def test_card_text() -> None:
    card = next(c for c in BOARD.cards if c.number == 2)
    text = format_card(BOARD, card, ids=False)
    lines = text.splitlines()
    assert lines[0] == "#2 Write the first command"
    assert lines[1] == "List: Doing | Labels: Robot"
    assert "Depends on: #1" in text
    assert "Steps [1/3]" in text
    assert "  [x] (1) Parse the arguments" in text
    assert "Checks [0/1]" in text


def test_card_json_round_trips() -> None:
    card = next(c for c in BOARD.cards if c.number == 2)
    data = json.loads(to_json(card_json(BOARD, card)))
    assert data["list"] == "Doing"
    assert [cl["title"] for cl in data["checklists"]] == ["Steps", "Checks"]


def test_board_json_wip() -> None:
    data = board_json(BOARD, include_archived=False)
    doing = next(lst for lst in data["lists"] if lst["title"] == "Doing")
    assert doing["wip_limit"] == {"value": 2, "hard": True}
    assert [c["number"] for c in doing["cards"]] == [2]


def test_change_lines() -> None:
    done = Change(2, "Steps: (2) Call the API", "open", "done", verified=True)
    assert format_change(done) == "#2 Steps: (2) Call the API: open → done (verified)"
    new = Change(3, "Steps: Ask Alice", None, "open", verified=True, warnings=["created checklist 'Steps'"])
    assert format_change(new) == "#3 Steps: Ask Alice: new → open (verified)\n  warning: created checklist 'Steps'"
    noop = Change(2, "list", "Doing", "Doing", changed=False, verified=True)
    assert format_change(noop) == "#2 list: unchanged (Doing)"
    assert format_change(Change(2, "list", "A", "B")).endswith("(NOT verified)")


def test_change_json() -> None:
    data = change_json(Change(2, "list", "To Do", "Doing", verified=True))
    assert data == {
        "card": 2,
        "subject": "list",
        "before": "To Do",
        "after": "Doing",
        "changed": True,
        "verified": True,
        "warnings": [],
    }
