"""Tests for the error classes and their exit codes."""

from wekan_cli import errors


def test_exit_codes_match_the_documented_table() -> None:
    assert errors.NotFoundError.exit_code == 3
    assert errors.AmbiguousError.exit_code == 4
    assert errors.AuthError.exit_code == 5
    assert errors.NetworkError.exit_code == 6
    assert errors.RefusedError.exit_code == 7
    assert errors.VerifyError.exit_code == 8


def test_exit_codes_are_unique_and_avoid_typer_usage_code() -> None:
    codes = [cls.exit_code for cls in errors.WekanError.__subclasses__()]
    assert len(codes) == len(set(codes))
    assert 2 not in codes  # typer/click use 2 for usage errors
    assert errors.INTERNAL_ERROR_EXIT_CODE not in codes
