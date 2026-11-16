"""Tests for building a Board from an export."""

import copy

from fakewekan import load_fixture

from wekan_cli.models import Board, WipLimit


def board() -> Board:
    return Board.from_export(load_fixture("board_export.json"))


def test_lists_cards_and_checklists() -> None:
    b = board()
    assert [lst.title for lst in b.lists] == ["Backlog", "To Do", "Doing", "Waiting", "Done"]
    assert [c.number for c in b.cards] == [1, 2, 3, 4]
    steps, checks = b.checklists_of("cardTwo0000000001")
    assert (steps.title, steps.done, len(steps.items)) == ("Steps", 1, 3)
    assert checks.items[0].title == "(1) Tests pass"


def test_wip_limits() -> None:
    lists = {lst.title: lst for lst in board().lists}
    assert lists["Doing"].wip == WipLimit(value=2, enabled=True, soft=False)
    assert lists["Doing"].wip is not None and lists["Doing"].wip.hard
    assert lists["Waiting"].wip is not None and not lists["Waiting"].wip.hard
    assert lists["Backlog"].wip is None


def test_disabled_wip_limit_is_none() -> None:
    assert WipLimit.from_json({"value": 3, "enabled": False}) is None


def test_soft_deleted_objects_are_dropped() -> None:
    data = copy.deepcopy(load_fixture("board_export.json"))
    data["cards"][0]["deletedAt"] = "2026-01-01T00:00:00Z"
    assert 1 not in [c.number for c in Board.from_export(data).cards]


def test_sort_field_orders_lists() -> None:
    data = copy.deepcopy(load_fixture("board_export.json"))
    data["lists"][4]["sort"] = -1  # "Done" moves to the front
    lists = Board.from_export(data).lists
    assert [lst.title for lst in lists] == ["Done", "Backlog", "To Do", "Doing", "Waiting"]
    assert all(lst.positioned for lst in lists)


def test_lists_without_sort_come_first_in_export_order() -> None:
    """Wekan's browser shows lists without ``sort`` first; the tool must show the same order."""
    data = copy.deepcopy(load_fixture("board_export.json"))
    data["lists"][4]["sort"] = None  # "Done" has no position yet
    data["lists"][2]["sort"] = None  # nor has "Doing"
    lists = Board.from_export(data).lists
    assert [lst.title for lst in lists] == ["Doing", "Done", "Backlog", "To Do", "Waiting"]
    assert [lst.title for lst in lists if not lst.positioned] == ["Doing", "Done"]


def test_checklists_without_sort_still_go_last() -> None:
    data = copy.deepcopy(load_fixture("board_export.json"))
    data["checklists"][0]["sort"] = None  # "Steps"
    assert [c.title for c in Board.from_export(data).checklists] == ["Checks", "Steps"]


def test_names() -> None:
    b = board()
    assert b.label_name("lblDecision") == "Decision"
    assert b.username("userAlice00000001") == "alice"
    assert b.username("unknown") == "unknown"
