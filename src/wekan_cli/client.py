"""HTTP access to Wekan: login, token cache, re-login on an auth failure, and error mapping.

Messages raised from here never contain the password, the token, or a request header.
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from wekan_cli.cache import CachedToken, TokenCache
from wekan_cli.config import Credentials
from wekan_cli.errors import AuthError, NetworkError, NotFoundError, WekanError

DEFAULT_TIMEOUT = 10.0
#: An auth failure that took this long is Wekan waiting for its database, not a bad token (outage of 2026-11-09:
#: the MongoDB driver gives up after 30 s and Wekan then answers 401).
SLOW_AUTH_SECONDS = 25.0
_DB_HINT = "Wekan answered but seems unable to reach its database; check the server"


class WekanClient:
    """A logged-in session with one Wekan server.

    Args:
        credentials: Where and as whom to log in.
        cache: Token cache; ``None`` uses the default location.
        transport: httpx transport (tests pass a ``MockTransport``).
        timeout: Seconds to wait for an answer.
        clock: Time source, replaceable in tests.
    """

    def __init__(
        self,
        credentials: Credentials,
        cache: TokenCache | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.credentials = credentials
        self.cache = cache or TokenCache()
        self._http = httpx.Client(base_url=credentials.url, transport=transport, timeout=timeout)
        self._clock = clock
        self._token: CachedToken | None = None

    def close(self) -> None:
        """Close the HTTP connection."""
        self._http.close()

    def __enter__(self) -> "WekanClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- public API -----------------------------------------------------------------------------------------------

    @property
    def user_id(self) -> str:
        """The logged-in account's user ID (logs in if needed)."""
        return self._ensure_token().user_id

    def get(self, path: str) -> Any:
        """GET a JSON resource, logging in or again as needed.

        Args:
            path: Path below the server URL, e.g. ``/api/user``.

        Returns:
            The parsed JSON.
        """
        return self._request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        """POST a JSON body (Wekan wants JSON everywhere except the login).

        Args:
            path: Path below the server URL.
            body: The JSON body.

        Returns:
            The parsed JSON answer (for a create: ``{"_id": ...}``).
        """
        return self._request("POST", path, body)

    def put(self, path: str, body: dict[str, Any]) -> Any:
        """PUT a JSON body.

        Args:
            path: Path below the server URL.
            body: The JSON body.

        Returns:
            The parsed JSON answer.
        """
        return self._request("PUT", path, body)

    def delete(self, path: str) -> Any:
        """DELETE a resource. Wekan's deletes through the API are hard deletes.

        Args:
            path: Path below the server URL.

        Returns:
            The parsed JSON answer.
        """
        return self._request("DELETE", path)

    def me(self) -> dict[str, Any]:
        """Return the logged-in account (``GET /api/user``)."""
        data = self.get("/api/user")
        if not isinstance(data, dict):
            raise WekanError("unexpected answer from /api/user")
        return cast(dict[str, Any], data)

    def boards(self) -> list[dict[str, Any]]:
        """Return the boards the account is a member of (``_id`` and ``title``)."""
        data = self.get(f"/api/users/{self.user_id}/boards")
        if not isinstance(data, list):
            raise WekanError("unexpected answer from the board list")
        return [cast(dict[str, Any], b) for b in cast(list[Any], data) if isinstance(b, dict)]

    def export(self, board_id: str) -> dict[str, Any]:
        """Return a board's full export: cards, lists, swimlanes, labels, checklists, items, users."""
        data = self.get(f"/api/boards/{board_id}/export")
        if not isinstance(data, dict) or "cards" not in data:
            raise NotFoundError(f"board {board_id} not found or not readable")
        return cast(dict[str, Any], data)

    # --- internals ------------------------------------------------------------------------------------------------

    def _ensure_token(self) -> CachedToken:
        if self._token is None:
            self._token = self.cache.load(self.credentials.url, self.credentials.username) or self._login()
        return self._token

    def _login(self) -> CachedToken:
        try:
            response = self._http.post(
                "/users/login",
                data={"username": self.credentials.username, "password": self.credentials.password},
            )
        except httpx.TimeoutException:
            raise NetworkError(f"login: no answer from {self.credentials.url} within the timeout") from None
        except httpx.HTTPError as exc:
            raise NetworkError(f"login: can't reach {self.credentials.url} ({type(exc).__name__})") from None
        if response.status_code >= 500:
            raise NetworkError(f"login: server error {response.status_code}")
        body = _json_dict(response)
        if response.status_code != 200 or body is None or "token" not in body:
            raise AuthError(f"login failed for user {self.credentials.username} (check the credentials file)")
        token = CachedToken(
            url=self.credentials.url,
            username=self.credentials.username,
            user_id=str(body.get("id", "")),
            token=str(body["token"]),
            expires=str(body.get("tokenExpires", "")),
        )
        self.cache.save(token)
        return token

    def _request(self, method: str, path: str, json_body: Any = None) -> Any:
        token = self._ensure_token()
        fresh = False
        while True:
            started = self._clock()
            response = self._send(method, path, token, json_body)
            elapsed = self._clock() - started
            if not _is_auth_failure(response):
                return self._parse(response, path)
            if elapsed >= SLOW_AUTH_SECONDS:
                raise NetworkError(f"{path}: auth failure after {elapsed:.0f} s: {_DB_HINT}")
            if fresh:
                raise AuthError(f"{path}: not authorized (no access, or the account was changed)")
            # The cached token was refused: forget it and log in once more.
            self.cache.clear()
            self._token = token = self._login()
            fresh = True

    def _send(self, method: str, path: str, token: CachedToken, json_body: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token.token}", "X-User-Id": token.user_id}
        try:
            return self._http.request(method, path, headers=headers, json=json_body)
        except httpx.TimeoutException:
            raise NetworkError(f"{path}: no answer within the timeout; {_DB_HINT}") from None
        except httpx.HTTPError as exc:
            raise NetworkError(f"{path}: can't reach {self.credentials.url} ({type(exc).__name__})") from None

    def _parse(self, response: httpx.Response, path: str) -> Any:
        status = response.status_code
        if status >= 500:
            raise NetworkError(f"{path}: server error {status}")
        if status == 403:
            raise AuthError(f"{path}: forbidden (the account lacks access)")
        if status == 404:
            raise NotFoundError(f"{path}: not found")
        if status >= 400:
            raise WekanError(f"{path}: unexpected status {status}")
        if response.headers.get("Content-Type", "").startswith("text/html"):
            # Wekan answers unknown API routes with its web page and a 200.
            raise WekanError(f"{path}: not an API route (got the web page)")
        if not response.content:
            # E.g. a card asked for through the wrong list: 200 with an empty body.
            raise NotFoundError(f"{path}: empty answer")
        body = _json_or_none(response)
        if body is None:
            raise WekanError(f"{path}: answer isn't JSON")
        return body


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _json_dict(response: httpx.Response) -> dict[str, Any] | None:
    body = _json_or_none(response)
    return cast(dict[str, Any], body) if isinstance(body, dict) else None


def _is_auth_failure(response: httpx.Response) -> bool:
    """Wekan's two ways to say "not authorized": a 401, or a 200 whose JSON body carries ``statusCode: 401``."""
    if response.status_code == 401:
        return True
    if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("application/json"):
        return False
    body = _json_dict(response)
    return body is not None and body.get("statusCode") == 401
