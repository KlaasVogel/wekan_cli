"""A fake Wekan server for unit tests, served through ``httpx.MockTransport``.

It answers like the real Wekan REST API does, including its quirks:

- an unknown route answers ``200`` with the web app's HTML page, not a 404;
- a bad or missing token gives ``401`` on ``/api/user`` but ``200`` with an error body on board routes;
- the board export holds every card with its ``cardNumber``, the lists with their ``wipLimit``, checklists, items,
  labels and usernames;
- a card ``PUT`` through a list the card isn't in answers ``200`` with an empty body and changes nothing;
- a card ``PUT`` with an empty ``description`` answers ``404 {"message": "Error"}`` (a single space works);
- writes ignore WIP limits (the tool has to enforce them).

The board data comes from a JSON fixture in the export's shape. Every ID, name and title in it is made up.
New routes are added here as the commands need them.
"""

import copy
import itertools
import json
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures"

BASE_URL = "https://wekan.example.com"
USERNAME = "robot"
# Holds "+" and "=" on purpose: a raw, unencoded form body breaks on both.
PASSWORD = "s3cret+pass=word"
USER_ID = "userRobot00000001"
TOKEN = "fake-token-0123456789"

_HTML = "<!DOCTYPE html><html><head><title>Wekan</title></head><body></body></html>"
_UNAUTHORIZED_BODY = {
    "isClientSafe": True,
    "error": "Unauthorized",
    "reason": "Unauthorized",
    "message": "Unauthorized [Unauthorized]",
    "errorType": "Meteor.Error",
    "statusCode": 401,
}

Handler = Callable[[httpx.Request, re.Match[str]], httpx.Response]


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture from ``tests/fixtures``.

    Args:
        name: File name, e.g. ``"board_export.json"``.

    Returns:
        The parsed JSON object.
    """
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


@dataclass
class FakeWekan:
    """In-memory Wekan with one account and any number of boards (keyed by board ``_id``).

    Attributes:
        boards: Board exports, keyed by board ID. Tests may change them to set up a case.
        requests: Every request received, in order, for assertions.
        logins: How many successful logins happened (the token cache should keep this low).
        drop_writes: Answer writes as usual but don't store them (to test the read-back check).
    """

    boards: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])
    logins: int = 0
    token: str = TOKEN
    drop_writes: bool = False

    def __post_init__(self) -> None:
        self._ids = itertools.count(1)
        board = r"/api/boards/(?P<board>[^/]+)"
        card = board + r"/cards/(?P<card>[^/]+)"
        self._routes: list[tuple[str, re.Pattern[str], Handler, bool]] = [
            ("POST", re.compile(r"/users/login"), self._login, False),
            ("GET", re.compile(r"/api/user"), self._user, True),
            ("GET", re.compile(r"/api/users/(?P<user>[^/]+)/boards"), self._user_boards, True),
            ("GET", re.compile(r"/api/boards/(?P<board>[^/]+)/export"), self._export, True),
            ("GET", re.compile(r"/api/cards/(?P<card>[^/]+)"), self._card, True),
            ("POST", re.compile(card + r"/checklists"), self._add_checklist, True),
            ("POST", re.compile(card + r"/checklists/(?P<cl>[^/]+)/items"), self._add_item, True),
            ("PUT", re.compile(card + r"/checklists/(?P<cl>[^/]+)/items/(?P<item>[^/]+)"), self._put_item, True),
            ("PUT", re.compile(board + r"/lists/(?P<list>[^/]+)/cards/(?P<card>[^/]+)"), self._put_card, True),
        ]

    @classmethod
    def with_fixture(cls, *names: str) -> "FakeWekan":
        """Create a fake Wekan holding the boards from the given export fixtures.

        Args:
            names: Fixture file names in the export's shape.

        Returns:
            The fake server.
        """
        fake = cls()
        for name in names:
            board = load_fixture(name)
            fake.boards[board["_id"]] = copy.deepcopy(board)
        return fake

    def transport(self) -> httpx.MockTransport:
        """Return a transport to pass to ``httpx.Client(transport=...)``."""
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.Client:
        """Return an ``httpx.Client`` wired to this fake, with the usual base URL."""
        return httpx.Client(base_url=BASE_URL, transport=self.transport())

    # --- dispatch -------------------------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request like Wekan would."""
        self.requests.append(request)
        for method, pattern, handler, needs_auth in self._routes:
            match = pattern.fullmatch(request.url.path)
            if match and request.method == method:
                if needs_auth and not self._authorized(request):
                    return self._unauthorized(request)
                return handler(request, match)
        return httpx.Response(200, text=_HTML, headers={"Content-Type": "text/html; charset=utf-8"})

    def _authorized(self, request: httpx.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.token}"

    def _unauthorized(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/user":
            return httpx.Response(401, json={"error": "Unauthorized"})
        return httpx.Response(200, json=_UNAUTHORIZED_BODY)

    # --- routes ---------------------------------------------------------------------------------------------------

    def _login(self, request: httpx.Request, _match: re.Match[str]) -> httpx.Response:
        form = urllib.parse.parse_qs(request.content.decode())
        if form.get("username") == [USERNAME] and form.get("password") == [PASSWORD]:
            self.logins += 1
            return httpx.Response(
                200, json={"id": USER_ID, "token": self.token, "tokenExpires": "2099-01-01T00:00:00.000Z"}
            )
        # TODO: record the real wrong-password response (status and body) on the test board in v0.1.0.
        return httpx.Response(400, json={"error": 400, "reason": "Incorrect username or password"})

    def _user(self, _request: httpx.Request, _match: re.Match[str]) -> httpx.Response:
        return httpx.Response(200, json={"_id": USER_ID, "username": USERNAME})

    def _user_boards(self, _request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        if match["user"] != USER_ID:
            return httpx.Response(403, json={"error": "Forbidden"})
        return httpx.Response(200, json=[{"_id": b["_id"], "title": b["title"]} for b in self.boards.values()])

    def _export(self, _request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        board = self.boards.get(match["board"])
        if board is None:
            return httpx.Response(404, json={"error": "Board not found"})
        return httpx.Response(200, json=board)

    # --- helpers for tests ----------------------------------------------------------------------------------------

    def find(self, board_id: str, collection: str, obj_id: str) -> dict[str, Any] | None:
        """Return an object from a board's export by collection (``"cards"``, ``"checklistItems"``…) and ID."""
        return next((o for o in self.boards[board_id][collection] if o["_id"] == obj_id), None)

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}New{next(self._ids):06d}"

    def _body(self, request: httpx.Request) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(request.content or b"{}")
        return data

    def _card(self, _request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        for board in self.boards.values():
            for card in board["cards"]:
                if card["_id"] == match["card"]:
                    return httpx.Response(200, json=card | {"boardId": board["_id"]})
        return httpx.Response(404, json={"error": "Card not found"})

    def _add_checklist(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        board = self.boards[match["board"]]
        new = {"_id": self._new_id("cl"), "cardId": match["card"], "title": self._body(request)["title"], "sort": 9}
        if not self.drop_writes:
            board["checklists"].append(new)
        return httpx.Response(200, json={"_id": new["_id"]})

    def _add_item(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        board = self.boards[match["board"]]
        siblings = [i for i in board["checklistItems"] if i["checklistId"] == match["cl"]]
        new = {
            "_id": self._new_id("item"),
            "checklistId": match["cl"],
            "cardId": match["card"],
            "title": self._body(request)["title"],
            "isFinished": False,
            "sort": max((i["sort"] for i in siblings), default=-1) + 1,
        }
        if not self.drop_writes:
            board["checklistItems"].append(new)
        return httpx.Response(200, json={"_id": new["_id"]})

    def _put_item(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        item = self.find(match["board"], "checklistItems", match["item"])
        if item is None:
            return httpx.Response(404, json={"error": "Item not found"})
        body = self._body(request)
        if not self.drop_writes:
            item.update({k: v for k, v in body.items() if k in ("isFinished", "title")})
        return httpx.Response(200, json={"_id": item["_id"]})

    def _put_card(self, request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        card = self.find(match["board"], "cards", match["card"])
        if card is None or card["listId"] != match["list"]:
            # Wekan's quirk: a card asked for through the wrong list gives an empty 200 and no change.
            return httpx.Response(200, content=b"", headers={"Content-Type": "application/json"})
        body = self._body(request)
        if body.get("description") == "":
            return httpx.Response(404, json={"message": "Error"})
        if not self.drop_writes:
            card.update({k: v for k, v in body.items() if k in ("listId", "swimlaneId", "description", "title")})
        return httpx.Response(200, json={"_id": card["_id"]})
