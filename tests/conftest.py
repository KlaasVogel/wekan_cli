"""Shared fixtures: a fake Wekan and an isolated home folder."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fakewekan import FakeWekan


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME and the XDG folders at a temp folder, so tests never touch the real config, credentials or cache."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    for var in ("WEKAN_BOARD", "WEKAN_CREDENTIALS", "WEKAN_DEBUG", "WEKAN_LIVE_BOARD"):
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def fake_wekan() -> FakeWekan:
    """A fake Wekan holding the made-up demo board."""
    return FakeWekan.with_fixture("board_export.json")


@pytest.fixture
def http(fake_wekan: FakeWekan) -> Iterator[httpx.Client]:
    """An ``httpx.Client`` wired to ``fake_wekan``."""
    with fake_wekan.client() as client:
        yield client
