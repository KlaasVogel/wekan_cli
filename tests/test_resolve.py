"""Tests for finding boards and cards by the names people use."""

import pytest
from fakewekan import load_fixture

from wekan_cli.config import Aliases
from wekan_cli.errors import AmbiguousError, NotFoundError
from wekan_cli.models import Board
from wekan_cli.resolve import find_card, resolve_board

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
