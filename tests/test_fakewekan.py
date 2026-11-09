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
