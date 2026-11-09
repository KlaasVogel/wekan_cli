"""Tests for the HTTP client: login, token cache, re-login, error mapping, outage detection."""

import time
from collections.abc import Callable, Iterator

import httpx
import pytest
from fakewekan import TOKEN, USER_ID, FakeWekan

from wekan_cli.cache import CachedToken, TokenCache
from wekan_cli.client import WekanClient
from wekan_cli.config import Credentials
from wekan_cli.errors import AuthError, NetworkError, NotFoundError, WekanError


def make(credentials: Credentials, fake: FakeWekan, clock: Callable[[], float] = time.monotonic) -> WekanClient:
    return WekanClient(credentials, transport=fake.transport(), clock=clock)


def test_logs_in_once_and_caches_the_token(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    with make(credentials, fake_wekan) as client:
        assert client.me()["_id"] == USER_ID
        client.boards()
    assert fake_wekan.logins == 1
    with make(credentials, fake_wekan) as client:  # a second command reuses the cached token
        client.me()
    assert fake_wekan.logins == 1
    cached = TokenCache().load(credentials.url, credentials.username)
    assert cached is not None and cached.token == TOKEN


def test_sends_bearer_and_user_id(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    with make(credentials, fake_wekan) as client:
        client.me()
    request = fake_wekan.requests[-1]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["X-User-Id"] == USER_ID


def test_refused_cached_token_triggers_one_relogin(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    TokenCache().save(CachedToken(credentials.url, credentials.username, USER_ID, "expired-token"))
    with make(credentials, fake_wekan) as client:
        # board routes say "unauthorized" with a 200 and an error body
        assert client.export("boardDemo00000001")["title"] == "Demo Board"
    assert fake_wekan.logins == 1
    cached = TokenCache().load(credentials.url, credentials.username)
    assert cached is not None and cached.token == TOKEN


def test_still_refused_after_relogin_is_auth_error(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    def refuse_all(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/login":
            return fake_wekan.handle(request)
        return httpx.Response(401, json={"error": "Unauthorized"})

    with (
        WekanClient(credentials, transport=httpx.MockTransport(refuse_all)) as client,
        pytest.raises(AuthError, match="not authorized"),
    ):
        client.me()


def test_wrong_password_is_auth_error(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    bad = Credentials(credentials.url, credentials.username, "wrong", credentials.path, "default")
    with make(bad, fake_wekan) as client, pytest.raises(AuthError, match="login failed") as info:
        client.me()
    assert "wrong" not in str(info.value)


def test_slow_auth_failure_is_reported_as_database_problem(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    TokenCache().save(CachedToken(credentials.url, credentials.username, USER_ID, "some-token"))
    ticks: Iterator[float] = iter([0.0, 30.0])  # the request "takes" 30 s, like the 2026-11-09 outage
    with (
        make(credentials, fake_wekan, clock=lambda: next(ticks)) as client,
        pytest.raises(NetworkError, match="database"),
    ):
        client.me()
    assert fake_wekan.logins == 0  # no re-login loop


def test_timeout_is_network_error(credentials: Credentials) -> None:
    TokenCache().save(CachedToken(credentials.url, credentials.username, USER_ID, "t"))

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with (
        WekanClient(credentials, transport=httpx.MockTransport(hang)) as client,
        pytest.raises(NetworkError, match="no answer"),
    ):
        client.me()


def test_unreachable_is_network_error(credentials: Credentials) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with (
        WekanClient(credentials, transport=httpx.MockTransport(refuse)) as client,
        pytest.raises(NetworkError, match="can't reach"),
    ):
        client.me()


def test_html_answer_is_not_an_api_route(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    with make(credentials, fake_wekan) as client, pytest.raises(WekanError, match="not an API route"):
        client.get("/api/boards/boardDemo00000001/members")


def test_404_and_empty_body_are_not_found(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    with make(credentials, fake_wekan) as client:
        with pytest.raises(NotFoundError):
            client.get("/api/cards/nope")
        with pytest.raises(NotFoundError):
            client.export("noSuchBoard")


def test_server_error_is_network_error(credentials: Credentials) -> None:
    TokenCache().save(CachedToken(credentials.url, credentials.username, USER_ID, "t"))
    transport = httpx.MockTransport(lambda request: httpx.Response(502, text="bad gateway"))
    with WekanClient(credentials, transport=transport) as client, pytest.raises(NetworkError, match="502"):
        client.me()


def test_errors_never_contain_secrets(credentials: Credentials, fake_wekan: FakeWekan) -> None:
    TokenCache().save(CachedToken(credentials.url, credentials.username, USER_ID, "cached-secret-token"))
    transport = httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    with WekanClient(credentials, transport=transport) as client, pytest.raises(WekanError) as info:
        client.me()
    for secret in (credentials.password, "cached-secret-token", "Bearer"):
        assert secret not in str(info.value)
