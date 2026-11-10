"""Tests for the fake Wekan itself, so the other tests can trust it."""

import httpx
from fakewekan import PASSWORD, TOKEN, USER_ID, USERNAME, FakeWekan

AUTH = {"Authorization": f"Bearer {TOKEN}", "X-User-Id": USER_ID}


def test_login_with_form_encoding_accepts_plus_and_equals(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    response = http.post("/users/login", data={"username": USERNAME, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["token"] == TOKEN
    assert fake_wekan.logins == 1


def test_login_with_raw_unencoded_body_fails(http: httpx.Client) -> None:
    raw = f"username={USERNAME}&password={PASSWORD}"  # "+" becomes a space, "=" splits the value
    response = http.post("/users/login", content=raw, headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 400


def test_unknown_route_answers_html_with_200(http: httpx.Client) -> None:
    response = http.get("/api/boards/boardDemo00000001/members", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/html")


def test_bad_token_gives_401_on_api_user(http: httpx.Client) -> None:
    response = http.get("/api/user", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_bad_token_gives_200_with_error_body_on_board_routes(http: httpx.Client) -> None:
    response = http.get("/api/boards/boardDemo00000001/export", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 200
    assert response.json()["statusCode"] == 401


def test_export_holds_card_numbers_and_wip_limits(http: httpx.Client) -> None:
    export = http.get("/api/boards/boardDemo00000001/export", headers=AUTH).json()
    assert [c["cardNumber"] for c in export["cards"]] == [1, 2, 3, 4]
    doing = next(lst for lst in export["lists"] if lst["title"] == "Doing")
    assert doing["wipLimit"] == {"value": 2, "enabled": True}


def test_card_by_id_and_missing_card(http: httpx.Client) -> None:
    card = http.get("/api/cards/cardTwo0000000001", headers=AUTH).json()
    assert card["cardNumber"] == 2
    missing = http.get("/api/cards/nope", headers=AUTH)
    assert missing.status_code == 404
    assert missing.json() == {"error": "Card not found"}


def test_user_boards_lists_the_fixture_board(http: httpx.Client) -> None:
    boards = http.get(f"/api/users/{USER_ID}/boards", headers=AUTH).json()
    assert boards == [{"_id": "boardDemo00000001", "title": "Demo Board"}]


def test_requests_are_recorded(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    http.get("/api/user", headers=AUTH)
    assert [r.url.path for r in fake_wekan.requests] == ["/api/user"]


CARD_TWO = "/api/boards/boardDemo00000001/cards/cardTwo0000000001"


def test_add_and_tick_item(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    created = http.post(f"{CARD_TWO}/checklists/clTwoChecks000001/items", json={"title": "Lint"}, headers=AUTH)
    item_id = created.json()["_id"]
    item = fake_wekan.find("boardDemo00000001", "checklistItems", item_id)
    assert item is not None and item["sort"] == 1 and item["isFinished"] is False
    http.put(f"{CARD_TWO}/checklists/clTwoChecks000001/items/{item_id}", json={"isFinished": True}, headers=AUTH)
    assert item["isFinished"] is True


def test_card_put_through_wrong_list_is_an_empty_200(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    path = "/api/boards/boardDemo00000001/lists/listBacklog000001/cards/cardTwo0000000001"
    response = http.put(path, json={"listId": "listDone000000001"}, headers=AUTH)
    assert response.status_code == 200 and response.content == b""
    card = fake_wekan.find("boardDemo00000001", "cards", "cardTwo0000000001")
    assert card is not None and card["listId"] == "listDoing00000001"


def test_drop_writes(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    fake_wekan.drop_writes = True
    response = http.post(f"{CARD_TWO}/checklists", json={"title": "Ghost"}, headers=AUTH)
    assert response.status_code == 200
    assert len(fake_wekan.boards["boardDemo00000001"]["checklists"]) == 2


def test_write_needs_auth(http: httpx.Client) -> None:
    response = http.post(f"{CARD_TWO}/checklists", json={"title": "x"})
    assert response.json()["statusCode"] == 401


def test_empty_description_is_refused(http: httpx.Client) -> None:
    path = "/api/boards/boardDemo00000001/lists/listDoing00000001/cards/cardTwo0000000001"
    response = http.put(path, json={"description": ""}, headers=AUTH)
    assert response.status_code == 404 and response.json() == {"message": "Error"}


def test_card_post_ignores_label_ids(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    body = {"title": "New", "authorId": USER_ID, "swimlaneId": "swimDefault000001", "labelIds": ["lblRobot"]}
    created = http.post("/api/boards/boardDemo00000001/lists/listToDo000000001/cards", json=body, headers=AUTH)
    card = fake_wekan.find("boardDemo00000001", "cards", created.json()["_id"])
    assert card is not None and card["labelIds"] == [] and card["cardNumber"] == 5


def test_item_delete_is_hard(fake_wekan: FakeWekan, http: httpx.Client) -> None:
    path = f"{CARD_TWO}/checklists/clTwoSteps0000001/items/itemTwoStep300001"
    assert http.delete(path, headers=AUTH).status_code == 200
    assert fake_wekan.find("boardDemo00000001", "checklistItems", "itemTwoStep300001") is None
    assert http.delete(path, headers=AUTH).status_code == 404
