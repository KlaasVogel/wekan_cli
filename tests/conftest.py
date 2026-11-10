"""Shared fixtures: a fake Wekan, an isolated home folder, and a credentials file for it."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fakewekan import BASE_URL, PASSWORD, USERNAME, FakeWekan

from wekan_cli import cli
from wekan_cli.client import WekanClient
from wekan_cli.config import Credentials


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HOME and the XDG folders at a temp folder, so tests never touch the real config, credentials or cache.

    Also starts every test in an empty working folder, so no real ``.wekan`` file is found above it.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    for var in ("WEKAN_BOARD", "WEKAN_CREDENTIALS", "WEKAN_DEBUG", "WEKAN_LIVE_BOARD"):
        monkeypatch.delenv(var, raising=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
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


@pytest.fixture
def credentials_file(isolated_home: Path) -> Path:
    """Write a credentials file for the fake Wekan at the default location (folder 700, file 600)."""
    folder = isolated_home / ".config" / "wekan"
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    path = folder / "credentials"
    path.write_text(f"# test account\nWEKAN_URL={BASE_URL}/\nWEKAN_USERNAME={USERNAME}\nWEKAN_PASSWORD={PASSWORD}\n")
    path.chmod(0o600)
    return path


@pytest.fixture
def credentials(credentials_file: Path) -> Credentials:
    """Credentials for the fake Wekan."""
    return Credentials(url=BASE_URL, username=USERNAME, password=PASSWORD, path=credentials_file, source="default")


@pytest.fixture
def wired_cli(fake_wekan: FakeWekan, credentials_file: Path, monkeypatch: pytest.MonkeyPatch) -> FakeWekan:
    """Make the ``wekan`` commands talk to the fake Wekan. Returns the fake for assertions."""

    def make_client(creds: Credentials) -> WekanClient:
        return WekanClient(creds, transport=fake_wekan.transport())

    monkeypatch.setattr(cli, "make_client", make_client)
    return fake_wekan
