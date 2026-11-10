"""Tests for credentials, aliases and board selection."""

from pathlib import Path

import pytest
from fakewekan import BASE_URL, PASSWORD

from wekan_cli import config
from wekan_cli.errors import AuthError, NotFoundError


def test_parse_splits_on_first_equals_and_skips_comments() -> None:
    text = "# comment\n\n WEKAN_URL = https://x \nWEKAN_PASSWORD=a=b+c\nnot a pair\n"
    assert config.parse_credentials(text) == {"WEKAN_URL": "https://x", "WEKAN_PASSWORD": "a=b+c"}


def test_load_default_location(credentials_file: Path) -> None:
    creds = config.load_credentials()
    assert creds.url == BASE_URL  # trailing slash stripped
    assert creds.password == PASSWORD
    assert creds.source == "default"


def test_password_not_in_repr(credentials_file: Path) -> None:
    creds = config.load_credentials()
    assert PASSWORD not in repr(creds)


def test_order_flag_then_env_then_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flag, env = tmp_path / "flag", tmp_path / "env"
    monkeypatch.setenv("WEKAN_CREDENTIALS", str(env))
    assert config.credentials_path(flag) == (flag, "--credentials")
    assert config.credentials_path() == (env, "WEKAN_CREDENTIALS")
    monkeypatch.delenv("WEKAN_CREDENTIALS")
    assert config.credentials_path()[1] == "default"


def test_missing_file_is_config_error() -> None:
    with pytest.raises(config.ConfigError, match="no credentials file"):
        config.load_credentials()


def test_missing_keys_named_without_values(tmp_path: Path) -> None:
    path = tmp_path / "creds"
    path.write_text("WEKAN_URL=https://x\nWEKAN_PASSWORD=hunter2\n")
    with pytest.raises(config.ConfigError) as info:
        config.load_credentials(path)
    assert "WEKAN_USERNAME" in str(info.value)
    assert "hunter2" not in str(info.value)


def test_config_error_is_an_auth_error() -> None:
    assert issubclass(config.ConfigError, AuthError)
    assert config.ConfigError.exit_code == 5


def test_is_private(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_text("x")
    path.chmod(0o600)
    assert config.is_private(path)
    path.chmod(0o644)
    assert not config.is_private(path)


def test_aliases_missing_file_is_empty() -> None:
    assert config.load_aliases() == config.Aliases()


def test_aliases_read(isolated_home: Path) -> None:
    path = isolated_home / ".config" / "wekan" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[boards]\ndemo = "boardDemo00000001"\n\n[users]\nalice = "userAlice00000001"\n')
    aliases = config.load_aliases()
    assert aliases.boards == {"demo": "boardDemo00000001"}
    assert aliases.users == {"alice": "userAlice00000001"}


def test_aliases_bad_shape(isolated_home: Path) -> None:
    path = isolated_home / ".config" / "wekan" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[boards]\ndemo = 3\n")
    with pytest.raises(config.ConfigError, match="boards"):
        config.load_aliases()


def test_board_ref_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".wekan").write_text('board = "from-file"\n')
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert config.board_ref(None, cwd=sub) == config.BoardRef("from-file", str(tmp_path / ".wekan"))
    monkeypatch.setenv("WEKAN_BOARD", "from-env")
    assert config.board_ref(None, cwd=sub) == config.BoardRef("from-env", "WEKAN_BOARD")
    assert config.board_ref("from-flag", cwd=sub) == config.BoardRef("from-flag", "--board")


def test_board_ref_none_given(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError, match="no board given"):
        config.board_ref(None, cwd=tmp_path)


def test_dotfile_without_board(tmp_path: Path) -> None:
    (tmp_path / ".wekan").write_text('swimlane = "x"\n')
    with pytest.raises(config.ConfigError, match="board ="):
        config.board_ref(None, cwd=tmp_path)
