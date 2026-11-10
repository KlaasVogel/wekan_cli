"""Tests for the command layer and the error handling in ``main()``."""

import json
import sys
from pathlib import Path

import pytest
from fakewekan import PASSWORD, TOKEN, FakeWekan
from typer.testing import CliRunner

from wekan_cli import __version__, cli
from wekan_cli.errors import AmbiguousError, AuthError, NotFoundError, RefusedError

runner = CliRunner()


def test_version_option() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"wekan {__version__}"


def test_version_command() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(cli.app, [])
    assert "Usage" in result.output


def test_pretty_exceptions_are_off() -> None:
    # Rich tracebacks can print local variables (password, token): they must stay off.
    assert cli.app.pretty_exceptions_enable is False


def _run_main(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def broken_app() -> None:
        secret = "do-not-print-me"  # a local that a rich traceback would show
        raise error if secret else error

    monkeypatch.setattr(cli, "app", broken_app)
    monkeypatch.setattr(sys, "argv", ["wekan"])
    cli.main()


def test_main_turns_known_error_into_one_line_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run_main(monkeypatch, NotFoundError("no #12 on board Demo Board"))
    assert exit_info.value.code == 3
    err = capsys.readouterr().err
    assert err == "error: no #12 on board Demo Board\n"


def test_main_hides_message_and_traceback_of_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run_main(monkeypatch, RuntimeError("Authorization: Bearer leaked-token"))
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "internal error: RuntimeError" in captured.err
    for secret in ("leaked-token", "do-not-print-me", "Traceback"):
        assert secret not in captured.err + captured.out


def test_main_debug_shows_traceback_without_locals(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("WEKAN_DEBUG", "1")
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, RuntimeError("boom"))
    err = capsys.readouterr().err
    assert "Traceback" in err
    assert "do-not-print-me" not in err


def test_help_is_plain_text() -> None:
    # Agents read --help: box-drawing characters only cost tokens.
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert not set("╭╮╰╯│─") & set(result.output)


# --- commands against the fake Wekan ------------------------------------------------------------------------------


def write_dotwekan(board: str = "Demo Board") -> None:
    Path(".wekan").write_text(f'board = "{board}"\n')


def test_whoami(wired_cli: FakeWekan) -> None:
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "robot on https://wekan.example.com"


def test_boards(wired_cli: FakeWekan) -> None:
    result = runner.invoke(cli.app, ["boards"])
    assert result.output.strip() == "Demo Board"
    data = runner.invoke(cli.app, ["boards", "--json"]).output
    assert '"id": "boardDemo00000001"' in data


def test_board_from_dotwekan(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["board"])
    assert result.exit_code == 0, result.output
    assert "== Doing [1/2 hard]" in result.output


def test_board_flag_beats_env(wired_cli: FakeWekan, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEKAN_BOARD", "no such board")
    result = runner.invoke(cli.app, ["board", "-b", "boardDemo00000001"])
    assert result.exit_code == 0, result.output


def test_card(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["card", "2"])
    assert result.exit_code == 0, result.output
    assert "Steps [1/3]" in result.output


def test_card_not_found(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["card", "12"])
    assert isinstance(result.exception, NotFoundError)


def test_no_board_given(wired_cli: FakeWekan) -> None:
    result = runner.invoke(cli.app, ["board"])
    assert isinstance(result.exception, NotFoundError)
    assert "no board given" in str(result.exception)


def test_config_shows_sources_but_no_secrets(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    runner.invoke(cli.app, ["whoami"])  # caches a token
    result = runner.invoke(cli.app, ["config"])
    assert result.exit_code == 0, result.output
    assert "(default)" in result.output
    assert "password: set" in result.output
    assert "token: cached" in result.output
    assert "board: Demo Board (from " in result.output
    assert PASSWORD not in result.output and TOKEN not in result.output


def test_world_readable_credentials_warn(wired_cli: FakeWekan, credentials_file: Path) -> None:
    credentials_file.chmod(0o644)
    result = runner.invoke(cli.app, ["whoami"])
    assert "chmod 600" in result.output


def test_wrong_password_via_main(
    wired_cli: FakeWekan, credentials_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    credentials_file.write_text(credentials_file.read_text().replace(PASSWORD, "wrong+pw=x"))
    monkeypatch.setattr(sys, "argv", ["wekan", "whoami"])
    with pytest.raises(SystemExit) as info:
        cli.main()
    assert info.value.code == AuthError.exit_code
    captured = capsys.readouterr()
    assert captured.err.startswith("error: login failed")
    for secret in ("wrong+pw=x", PASSWORD, TOKEN):
        assert secret not in captured.err + captured.out


@pytest.mark.parametrize(
    "args", [["whoami"], ["boards", "--json"], ["board", "--ids"], ["card", "2", "--json"], ["config"]]
)
def test_no_command_prints_password_or_token(wired_cli: FakeWekan, args: list[str]) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert PASSWORD not in result.output
    assert TOKEN not in result.output


# --- write commands -----------------------------------------------------------------------------------------------


def test_add_item(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["add-item", "2", "Lint", "--checklist", "Checks", "--numbered"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "#2 Checks: (2) Lint: new → open (verified)"


def test_tick_json(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["tick", "2", "2", "3", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [c["after"] for c in data] == ["done", "done"] and all(c["verified"] for c in data)


def test_tick_ambiguous_exit(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["tick", "2", "1"])
    assert isinstance(result.exception, AmbiguousError)


def test_move_and_hard_wip(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["move", "3", "doing", "--from", "backlog"])
    assert result.output.strip() == "#3 list: Backlog → Doing (verified)"
    result = runner.invoke(cli.app, ["move", "1", "Doing"])
    assert isinstance(result.exception, RefusedError)
    assert RefusedError.exit_code == 7


def test_describe_from_file_and_stdin(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    Path("desc.md").write_text("Depends on: #2\n\nMore text\n")
    result = runner.invoke(cli.app, ["describe", "3", "--file", "desc.md"])
    assert result.output.strip() == "#3 description: 1 line → 3 lines (verified)"
    result = runner.invoke(cli.app, ["describe", "3", "--file", "-"], input="Short\n")
    assert result.output.strip() == "#3 description: 3 lines → 1 line (verified)"


def test_describe_missing_file(wired_cli: FakeWekan) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, ["describe", "3", "--file", "nope.md"])
    assert isinstance(result.exception, NotFoundError)


@pytest.mark.parametrize("args", [["boards"], ["whoami"], ["config"], ["card", "2", "-b", "Demo Board"]])
def test_credentials_after_the_command(wired_cli: FakeWekan, credentials_file: Path, args: list[str]) -> None:
    moved = credentials_file.parent / "elsewhere"
    credentials_file.rename(moved)
    result = runner.invoke(cli.app, [*args, "--credentials", str(moved)])
    assert result.exit_code == 0, result.output
    if args == ["config"]:
        assert f"credentials: {moved} (--credentials)" in result.output


def test_command_credentials_beat_the_global_one(wired_cli: FakeWekan, credentials_file: Path) -> None:
    result = runner.invoke(cli.app, ["--credentials", "/nope", "whoami", "--credentials", str(credentials_file)])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "args", [["add-item", "3", "x"], ["tick", "2", "2"], ["move", "3", "Doing"], ["describe", "3", "--file", "-"]]
)
def test_write_commands_print_no_secrets(wired_cli: FakeWekan, args: list[str]) -> None:
    write_dotwekan()
    result = runner.invoke(cli.app, args, input="text\n")
    assert result.exit_code == 0, result.output
    assert PASSWORD not in result.output and TOKEN not in result.output
