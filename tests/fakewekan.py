"""A fake Wekan server for unit tests, served through ``httpx.MockTransport``.

It answers like the real Wekan REST API does, including its quirks:

- an unknown route answers ``200`` with the web app's HTML page, not a 404;
- a bad or missing token gives ``401`` on ``/api/user`` but ``200`` with an error body on board routes;
- the board export holds every card with its ``cardNumber``, the lists with their ``wipLimit``, checklists, items,
  labels and usernames.

The board data comes from a JSON fixture in the export's shape. Every ID, name and title in it is made up.
New routes are added here as the commands need them.
"""

import copy
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
    """

    boards: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])
    logins: int = 0
    token: str = TOKEN

    def __post_init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler, bool]] = [
            ("POST", re.compile(r"/users/login"), self._login, False),
            ("GET", re.compile(r"/api/user"), self._user, True),
            ("GET", re.compile(r"/api/users/(?P<user>[^/]+)/boards"), self._user_boards, True),
            ("GET", re.compile(r"/api/boards/(?P<board>[^/]+)/export"), self._export, True),
            ("GET", re.compile(r"/api/cards/(?P<card>[^/]+)"), self._card, True),
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

    def _card(self, _request: httpx.Request, match: re.Match[str]) -> httpx.Response:
        for board in self.boards.values():
            for card in board["cards"]:
                if card["_id"] == match["card"]:
                    return httpx.Response(200, json=card | {"boardId": board["_id"]})
        return httpx.Response(404, json={"error": "Card not found"})
