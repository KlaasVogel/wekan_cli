"""Tests for the command layer and the error handling in ``main()``."""

import sys

import pytest
from typer.testing import CliRunner

from wekan_cli import __version__, cli
from wekan_cli.errors import NotFoundError

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
        secret = "do-not-print-me"  # noqa: F841  (a local that a rich traceback would show)
        raise error

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
