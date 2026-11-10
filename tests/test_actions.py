"""Tests for the write actions against the fake Wekan: the change, the read-back check, and the refusals."""

from collections.abc import Iterator

import pytest
from fakewekan import USER_ID, FakeWekan

from wekan_cli import actions
from wekan_cli.client import WekanClient
from wekan_cli.config import Credentials
from wekan_cli.errors import AmbiguousError, NotFoundError, RefusedError, VerifyError
from wekan_cli.models import Board, Card
from wekan_cli.resolve import find_card

BOARD_ID = "boardDemo00000001"


@pytest.fixture
def client(credentials: Credentials, fake_wekan: FakeWekan) -> Iterator[WekanClient]:
    with WekanClient(credentials, transport=fake_wekan.transport()) as c:
        yield c


def read(client: WekanClient) -> Board:
    return Board.from_export(client.export(BOARD_ID))


def card(client: WekanClient, number: int) -> tuple[Board, Card]:
    board = read(client)
    return board, find_card(board, number)


def item_titles(board: Board, number: int) -> list[str]:
    c = find_card(board, number)
    return [i.title for cl in board.checklists_of(c.id) for i in cl.items]


def writes(fake: FakeWekan) -> int:
    return sum(r.method in ("POST", "PUT", "DELETE") and r.url.path.startswith("/api/") for r in fake.requests)


# --- add-item -----------------------------------------------------------------------------------------------------


def test_add_item_creates_steps_checklist_on_a_card_without_one(client: WekanClient) -> None:
    change = actions.add_item(client, *card(client, 3), "Ask Alice")
    assert change.verified and change.subject == "Steps: Ask Alice"
    assert "created checklist 'Steps'" in change.warnings
    assert item_titles(read(client), 3) == ["Ask Alice"]


def test_add_item_to_named_checklist_numbered_and_done(client: WekanClient) -> None:
    change = actions.add_item(client, *card(client, 2), "Ship it", done=True, checklist_name="steps", numbered=True)
    assert change.subject == "Steps: (4) Ship it" and change.after == "done" and change.verified
    board = read(client)
    steps = board.checklists_of(find_card(board, 2).id)[0]
    assert steps.items[-1].title == "(4) Ship it" and steps.items[-1].finished


def test_add_item_refuses_to_guess_between_checklists(client: WekanClient, fake_wekan: FakeWekan) -> None:
    with pytest.raises(RefusedError, match="Steps, Checks"):
        actions.add_item(client, *card(client, 2), "Where does this go?")
    assert writes(fake_wekan) == 0


def test_add_item_warns_about_markdown_numbering(client: WekanClient) -> None:
    change = actions.add_item(client, *card(client, 3), "1. First step")
    assert any("numbered list" in w for w in change.warnings)


def test_add_item_verify_failure(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board, c = card(client, 2)
    fake_wekan.drop_writes = True
    with pytest.raises(VerifyError, match="#2 Checks: Lint"):
        actions.add_item(client, board, c, "Lint", checklist_name="Checks")


def test_next_number_without_checklist() -> None:
    assert actions.next_number(None) == 1


# --- tick ---------------------------------------------------------------------------------------------------------


def test_tick_by_number_and_text(client: WekanClient) -> None:
    changes = actions.tick(client, *card(client, 2), ["2", "print"])
    assert [(c.subject, c.before, c.after, c.verified) for c in changes] == [
        ("Steps: (2) Call the API", "open", "done", True),
        ("Steps: (3) Print the result", "open", "done", True),
    ]
    board = read(client)
    assert all(i.finished for i in board.checklists_of(find_card(board, 2).id)[0].items)


def test_tick_already_done_sends_nothing(client: WekanClient, fake_wekan: FakeWekan) -> None:
    (change,) = actions.tick(client, *card(client, 2), ["parse"])
    assert not change.changed and change.after == "done"
    assert writes(fake_wekan) == 0


def test_untick(client: WekanClient) -> None:
    (change,) = actions.tick(client, *card(client, 2), ["parse"], undo=True)
    assert change.before == "done" and change.after == "open" and change.verified


def test_tick_number_across_checklists_is_ambiguous(client: WekanClient, fake_wekan: FakeWekan) -> None:
    with pytest.raises(AmbiguousError, match="Checks: \\(1\\) Tests pass"):
        actions.tick(client, *card(client, 2), ["1"])
    assert writes(fake_wekan) == 0


def test_tick_all(client: WekanClient) -> None:
    changes = actions.tick(client, *card(client, 2), ["1"], all_matches=True)
    assert [c.changed for c in changes] == [False, True]


def test_tick_no_match(client: WekanClient) -> None:
    with pytest.raises(NotFoundError, match="no item matching 'deploy' on #2"):
        actions.tick(client, *card(client, 2), ["deploy"])


def test_tick_verify_failure(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board, c = card(client, 2)
    fake_wekan.drop_writes = True
    with pytest.raises(VerifyError):
        actions.tick(client, board, c, ["2"])


# --- move ---------------------------------------------------------------------------------------------------------


def test_move(client: WekanClient) -> None:
    change = actions.move(client, *card(client, 3), "doing")
    assert (change.before, change.after, change.verified) == ("Backlog", "Doing", True)
    assert find_card(read(client), 3).list_id == "listDoing00000001"


def test_move_already_there(client: WekanClient, fake_wekan: FakeWekan) -> None:
    change = actions.move(client, *card(client, 2), "Doing")
    assert not change.changed
    assert writes(fake_wekan) == 0


def test_move_from_mismatch_is_refused(client: WekanClient, fake_wekan: FakeWekan) -> None:
    with pytest.raises(RefusedError, match="#3 is in Backlog, not in To Do"):
        actions.move(client, *card(client, 3), "Doing", from_list="To Do")
    assert writes(fake_wekan) == 0


def test_move_into_full_hard_limit_is_refused(client: WekanClient, fake_wekan: FakeWekan) -> None:
    actions.move(client, *card(client, 3), "Doing")  # Doing: 2/2 now
    with pytest.raises(RefusedError, match="Doing is full \\(2/2, hard limit\\)"):
        actions.move(client, *card(client, 1), "Doing")
    change = actions.move(client, *card(client, 1), "Doing", over_wip=True)
    assert change.verified and "hard limit, moved with --over-wip" in change.warnings[0]


def test_move_into_full_soft_limit_warns(client: WekanClient, fake_wekan: FakeWekan) -> None:
    waiting = fake_wekan.find(BOARD_ID, "lists", "listWaiting000001")
    assert waiting is not None
    waiting["wipLimit"]["value"] = 0
    change = actions.move(client, *card(client, 3), "Waiting")
    assert change.verified and change.warnings == ["Waiting is full (0/0, soft limit)"]


def test_move_unknown_list(client: WekanClient) -> None:
    with pytest.raises(NotFoundError, match="lists: Backlog, To Do"):
        actions.move(client, *card(client, 3), "Review")


def test_move_card_moved_meanwhile(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board, c = card(client, 3)
    moved = fake_wekan.find(BOARD_ID, "cards", c.id)
    assert moved is not None
    moved["listId"] = "listToDo000000001"  # someone moved it in the browser after our read
    with pytest.raises(NotFoundError, match="empty answer"):
        actions.move(client, board, c, "Doing")


# --- describe -----------------------------------------------------------------------------------------------------


def test_describe(client: WekanClient) -> None:
    change = actions.describe(client, *card(client, 3), "Line one\nLine two\n\n")
    assert (change.after, change.verified) == ("2 lines", True)
    assert find_card(read(client), 3).description == "Line one\nLine two"


def test_describe_same_text_sends_nothing(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board, c = card(client, 2)
    change = actions.describe(client, board, c, c.description + "\n")
    assert not change.changed
    assert writes(fake_wekan) == 0


def test_describe_verify_failure(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board, c = card(client, 3)
    fake_wekan.drop_writes = True
    with pytest.raises(VerifyError, match="#3 description"):
        actions.describe(client, board, c, "New text")


def test_describe_clear_sends_a_space(client: WekanClient, fake_wekan: FakeWekan) -> None:
    change = actions.describe(client, *card(client, 3), "\n")
    assert (change.before, change.after, change.verified) == ("1 line", "empty", True)
    assert fake_wekan.requests[-2].content == b'{"description":" "}'


# --- new-card -----------------------------------------------------------------------------------------------------


def test_new_card_with_labels_and_description(client: WekanClient, fake_wekan: FakeWekan) -> None:
    change = actions.new_card(
        client, read(client), "to do", "Write the docs", "Depends on: #2\n", ["robot", "Decision"]
    )
    assert (change.card, change.subject, change.before, change.after, change.verified) == (
        5,
        "Write the docs",
        None,
        "To Do",
        True,
    )
    raw = next(c for c in fake_wekan.boards[BOARD_ID]["cards"] if c["cardNumber"] == 5)
    assert raw["userId"] == USER_ID and raw["swimlaneId"] == "swimDefault000001"
    assert raw["labelIds"] == ["lblRobot", "lblDecision"] and raw["description"] == "Depends on: #2"


def test_new_card_duplicate_title_is_refused(client: WekanClient, fake_wekan: FakeWekan) -> None:
    with pytest.raises(RefusedError, match="#2 already has the title"):
        actions.new_card(client, read(client), "Backlog", "write the FIRST command")
    assert writes(fake_wekan) == 0
    assert actions.new_card(client, read(client), "Backlog", "Write the first command", force=True).verified


def test_new_card_archived_twin_is_no_duplicate(client: WekanClient) -> None:
    assert actions.new_card(client, read(client), "Backlog", "An old idea").verified


def test_new_card_unknown_label_sends_nothing(client: WekanClient, fake_wekan: FakeWekan) -> None:
    with pytest.raises(NotFoundError, match="labels: Alice, Robot, Decision"):
        actions.new_card(client, read(client), "Backlog", "New", labels=["Nope"])
    assert writes(fake_wekan) == 0


def test_new_card_keeps_to_hard_wip(client: WekanClient) -> None:
    actions.move(client, *card(client, 3), "Doing")  # Doing: 2/2
    with pytest.raises(RefusedError, match="Doing is full"):
        actions.new_card(client, read(client), "Doing", "One too many")
    change = actions.new_card(client, read(client), "Doing", "One too many", over_wip=True)
    assert "hard limit, created with --over-wip" in change.warnings[0]


def test_new_card_verify_failure(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board = read(client)
    fake_wekan.drop_writes = True
    with pytest.raises(VerifyError, match="Ghost card"):
        actions.new_card(client, board, "Backlog", "Ghost card")


# --- label --------------------------------------------------------------------------------------------------------


def test_label_add_keeps_the_others(client: WekanClient) -> None:
    change = actions.label(client, *card(client, 2), "decision")
    assert (change.subject, change.before, change.after, change.verified) == ("label Decision", "off", "on", True)
    assert find_card(read(client), 2).label_ids == ("lblRobot", "lblDecision")


def test_label_remove(client: WekanClient) -> None:
    change = actions.label(client, *card(client, 2), "Robot", remove=True)
    assert change.after == "off" and find_card(read(client), 2).label_ids == ()


def test_label_already_there_sends_nothing(client: WekanClient, fake_wekan: FakeWekan) -> None:
    assert not actions.label(client, *card(client, 2), "Robot").changed
    assert not actions.label(client, *card(client, 2), "Alice", remove=True).changed
    assert writes(fake_wekan) == 0


def test_label_by_colour_when_unnamed(client: WekanClient, fake_wekan: FakeWekan) -> None:
    fake_wekan.boards[BOARD_ID]["labels"].append({"_id": "lblRed", "name": "", "color": "red"})
    assert actions.label(client, *card(client, 3), "RED").subject == "label red"


# --- delete-item --------------------------------------------------------------------------------------------------


def test_delete_item_needs_yes(client: WekanClient, fake_wekan: FakeWekan) -> None:
    with pytest.raises(RefusedError, match=r"would delete #2 Steps: \(3\) Print the result"):
        actions.delete_item(client, *card(client, 2), "3")
    assert writes(fake_wekan) == 0


def test_delete_item(client: WekanClient) -> None:
    change = actions.delete_item(client, *card(client, 2), "print", yes=True)
    assert (change.before, change.after, change.verified) == ("open", "deleted", True)
    assert "(3) Print the result" not in item_titles(read(client), 2)


def test_delete_item_must_match_one(client: WekanClient) -> None:
    with pytest.raises(AmbiguousError):
        actions.delete_item(client, *card(client, 2), "1", yes=True)


def test_delete_item_verify_failure(client: WekanClient, fake_wekan: FakeWekan) -> None:
    board, c = card(client, 2)
    fake_wekan.drop_writes = True
    with pytest.raises(VerifyError):
        actions.delete_item(client, board, c, "3", yes=True)
