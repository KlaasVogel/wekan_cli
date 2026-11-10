"""Tests for finding boards and cards by the names people use."""

import pytest
from fakewekan import load_fixture

from wekan_cli.config import Aliases
from wekan_cli.errors import AmbiguousError, NotFoundError
from wekan_cli.models import Board
from wekan_cli.resolve import find_card, find_checklist, find_items, find_list, resolve_board

BOARDS = [{"_id": "b1", "title": "Demo Board"}, {"_id": "b2", "title": "Other"}, {"_id": "b3", "title": "Twin"}]


def test_board_by_alias_id_and_title() -> None:
    aliases = Aliases(boards={"demo": "b1"})
    assert resolve_board("demo", BOARDS, aliases) == ("b1", "Demo Board")
    assert resolve_board("b2", BOARDS, Aliases()) == ("b2", "Other")
    assert resolve_board("demo board", BOARDS, Aliases()) == ("b1", "Demo Board")


def test_alias_to_invisible_board() -> None:
    with pytest.raises(NotFoundError, match="can't see"):
        resolve_board("x", BOARDS, Aliases(boards={"x": "gone"}))


def test_ambiguous_title() -> None:
    with pytest.raises(AmbiguousError, match="b3"):
        resolve_board("twin", [*BOARDS, {"_id": "b4", "title": "TWIN"}], Aliases())


def test_unknown_board() -> None:
    with pytest.raises(NotFoundError, match="wekan boards"):
        resolve_board("nope", BOARDS, Aliases())


def test_card_by_number() -> None:
    board = Board.from_export(load_fixture("board_export.json"))
    assert find_card(board, 2).title == "Write the first command"


def test_archived_card_needs_flag() -> None:
    board = Board.from_export(load_fixture("board_export.json"))
    with pytest.raises(NotFoundError, match="archived"):
        find_card(board, 4)
    assert find_card(board, 4, include_archived=True).archived


def test_missing_card_names_the_board() -> None:
    board = Board.from_export(load_fixture("board_export.json"))
    with pytest.raises(NotFoundError, match="no #12 on board Demo Board"):
        find_card(board, 12)


DEMO = Board.from_export(load_fixture("board_export.json"))


def test_find_list_case_insensitive() -> None:
    assert find_list(DEMO, "to do").id == "listToDo000000001"


def test_find_list_unknown_names_the_lists() -> None:
    with pytest.raises(NotFoundError, match="lists: Backlog, To Do, Doing, Waiting, Done"):
        find_list(DEMO, "Review")


def test_find_list_repeated_across_swimlanes() -> None:
    data = load_fixture("board_export.json")
    data["swimlanes"].append({"_id": "swimTeam000000001", "title": "Team", "sort": 1})
    data["lists"].append({"_id": "listDoingTeam0001", "title": "Doing", "swimlaneId": "swimTeam000000001", "sort": 9})
    board = Board.from_export(data)
    with pytest.raises(AmbiguousError, match="Default"):
        find_list(board, "Doing")
    assert find_list(board, "Doing", swimlane="team").id == "listDoingTeam0001"
    with pytest.raises(NotFoundError, match="no swimlane"):
        find_list(board, "Doing", swimlane="Nope")


def test_find_checklist() -> None:
    card = find_card(DEMO, 2)
    found = find_checklist(DEMO, card, "CHECKS")
    assert found is not None and found.id == "clTwoChecks000001"
    assert find_checklist(DEMO, card, "Nope") is None


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [("2", ["(2) Call the API"]), ("call", ["(2) Call the API"]), ("( 3 )", []), ("RESULT", ["(3) Print the result"])],
)
def test_find_items(pattern: str, expected: list[str]) -> None:
    card = find_card(DEMO, 2)
    if not expected:
        with pytest.raises(NotFoundError):
            find_items(DEMO, card, [pattern])
        return
    assert [m.item.title for m in find_items(DEMO, card, [pattern])] == expected


def test_bare_number_matches_only_the_item_number() -> None:
    data = load_fixture("board_export.json")
    data["checklistItems"][2]["title"] = "(12) Print 2 results"
    card_board = Board.from_export(data)
    with pytest.raises(NotFoundError):
        find_items(card_board, find_card(card_board, 2), ["12 "])  # not a bare number: substring, no match
    assert [m.item.title for m in find_items(card_board, find_card(card_board, 2), ["2"])] == ["(2) Call the API"]


def test_find_items_dedupes_and_keeps_checklist() -> None:
    found = find_items(DEMO, find_card(DEMO, 2), ["1", "tests"], all_matches=True)
    assert [(m.checklist.title, m.item.title) for m in found] == [
        ("Steps", "(1) Parse the arguments"),
        ("Checks", "(1) Tests pass"),
    ]
