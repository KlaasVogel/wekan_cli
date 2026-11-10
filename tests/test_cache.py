"""Tests for the token cache."""

import stat
from pathlib import Path

from wekan_cli.cache import CachedToken, TokenCache, cache_dir

TOKEN = CachedToken(url="https://w", username="u", user_id="id1", token="tok-secret", expires="2099")


def test_default_location_follows_xdg(isolated_home: Path) -> None:
    assert cache_dir() == isolated_home / ".cache" / "wekan"


def test_round_trip_and_permissions() -> None:
    cache = TokenCache()
    cache.save(TOKEN)
    assert cache.load("https://w", "u") == TOKEN
    assert stat.S_IMODE(cache.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache.path.parent.stat().st_mode) == 0o700


def test_other_server_or_user_is_ignored() -> None:
    cache = TokenCache()
    cache.save(TOKEN)
    assert cache.load("https://other", "u") is None
    assert cache.load("https://w", "someone") is None


def test_missing_or_broken_file_is_none() -> None:
    cache = TokenCache()
    assert cache.load("https://w", "u") is None
    cache.path.parent.mkdir(parents=True)
    cache.path.write_text("{not json")
    assert cache.load("https://w", "u") is None


def test_clear() -> None:
    cache = TokenCache()
    cache.save(TOKEN)
    cache.clear()
    assert not cache.path.exists()
    cache.clear()  # no error when already gone


def test_token_not_in_repr() -> None:
    assert "tok-secret" not in repr(TOKEN)
