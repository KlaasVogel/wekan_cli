"""Live tests against a real Wekan. Opt-in: ``WEKAN_LIVE_BOARD=<board id> pytest -m live``.

They run every write command once on a throwaway board and refuse any board whose title doesn't contain "test".
One card is created per run; its checklist items are deleted afterwards, and the card is left for a person to archive
(the API's card delete can't be undone). Labels are only tested when the board has some.

The environment is read when this module is imported, before ``conftest.py`` points ``HOME`` at a temp folder for
each test, so the real credentials file and token cache are used (one login per 90 days, not one per run).
"""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from wekan_cli import actions
from wekan_cli.cache import TokenCache, cache_dir
from wekan_cli.client import WekanClient
from wekan_cli.config import credentials_path, load_credentials
from wekan_cli.errors import RefusedError
from wekan_cli.models import Board, Card
from wekan_cli.resolve import find_card

LIVE_BOARD = os.environ.get("WEKAN_LIVE_BOARD", "")
_CREDENTIALS: Path = credentials_path(None)[0]  # WEKAN_CREDENTIALS, else ~/.config/wekan/credentials
_TOKEN_CACHE: Path = cache_dir() / "token.json"

pytestmark = [pytest.mark.live, pytest.mark.skipif(not LIVE_BOARD, reason="WEKAN_LIVE_BOARD isn't set")]


@pytest.fixture(scope="module")
def client() -> Iterator[WekanClient]:
    with WekanClient(load_credentials(_CREDENTIALS), cache=TokenCache(_TOKEN_CACHE)) as c:
        board = Board.from_export(c.export(LIVE_BOARD))
        if "test" not in board.title.casefold():
            pytest.fail(f"refusing to run live tests on {board.title!r}: its title doesn't contain 'test'")
        yield c


def read(client: WekanClient) -> Board:
    return Board.from_export(client.export(LIVE_BOARD))


def open_list(board: Board) -> str:
    """The title of a list that isn't archived and has room under its WIP limit."""
    for lst in board.lists:
        full = lst.wip is not None and len(board.cards_in(lst.id)) >= lst.wip.value
        if not lst.archived and not full:
            return lst.title
    pytest.skip("the live board has no list with room")


@pytest.fixture(scope="module")
def live_card(client: WekanClient) -> Iterator[int]:
    board = read(client)
    change = actions.new_card(client, board, open_list(board), f"wekan-cli live test {time.strftime('%Y-%m-%d %H:%M')}")
    assert change.verified and change.card > 0
    yield change.card
    board = read(client)
    card = find_card(board, change.card)
    for checklist in board.checklists_of(card.id):
        for item in checklist.items:
            client.delete(f"/api/boards/{board.id}/cards/{card.id}/checklists/{checklist.id}/items/{item.id}")


def fresh(client: WekanClient, number: int) -> tuple[Board, Card]:
    board = read(client)
    return board, find_card(board, number)


def test_duplicate_title_is_refused(client: WekanClient, live_card: int) -> None:
    board, card = fresh(client, live_card)
    with pytest.raises(RefusedError):
        actions.new_card(client, board, open_list(board), card.title)


def test_items(client: WekanClient, live_card: int) -> None:
    first = actions.add_item(client, *fresh(client, live_card), "First", numbered=True)
    second = actions.add_item(client, *fresh(client, live_card), "Second", numbered=True, done=True)
    assert (first.subject, second.subject, second.after) == ("Steps: (1) First", "Steps: (2) Second", "done")
    assert [c.after for c in actions.tick(client, *fresh(client, live_card), ["1"])] == ["done"]
    assert [c.after for c in actions.tick(client, *fresh(client, live_card), ["first", "2"], undo=True)] == [
        "open",
        "open",
    ]
    with pytest.raises(RefusedError):
        actions.delete_item(client, *fresh(client, live_card), "2")
    assert actions.delete_item(client, *fresh(client, live_card), "2", yes=True).verified


def test_describe_and_clear(client: WekanClient, live_card: int) -> None:
    assert actions.describe(client, *fresh(client, live_card), "Line one\nLine two").after == "2 lines"
    assert actions.describe(client, *fresh(client, live_card), "").after == "empty"


def test_move_there_and_back(client: WekanClient, live_card: int) -> None:
    board, card = fresh(client, live_card)
    home = board.list_by_id(card.list_id)
    assert home is not None
    others = [lst.title for lst in board.lists if not lst.archived and lst.id != home.id]
    if not others:
        pytest.skip("the live board has only one list")
    there = actions.move(client, board, card, others[0], from_list=home.title, over_wip=True)
    back = actions.move(client, *fresh(client, live_card), home.title, over_wip=True)
    assert there.verified and back.verified and back.after == home.title


def test_label_on_and_off(client: WekanClient, live_card: int) -> None:
    board, card = fresh(client, live_card)
    if not board.labels:
        pytest.skip("the live board has no labels")
    name = next(iter(board.labels.values()))
    title = name.name or name.color
    assert actions.label(client, board, card, title).after == "on"
    assert actions.label(client, *fresh(client, live_card), title, remove=True).after == "off"
