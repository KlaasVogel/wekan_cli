"""Credentials, the global config file, and the per-folder ``.wekan`` file.

Where things come from (first match wins):

- credentials: ``--credentials PATH`` > ``WEKAN_CREDENTIALS`` > ``~/.config/wekan/credentials``
- board: ``--board`` > ``WEKAN_BOARD`` > ``.wekan`` in the current folder or a folder above it
- aliases: ``~/.config/wekan/config.toml`` (``[boards]`` and ``[users]`` tables)
"""

import os
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from wekan_cli.errors import AuthError, NotFoundError

CREDENTIALS_ENV = "WEKAN_CREDENTIALS"
BOARD_ENV = "WEKAN_BOARD"
DOTFILE = ".wekan"
REQUIRED_KEYS = ("WEKAN_URL", "WEKAN_USERNAME", "WEKAN_PASSWORD")


class ConfigError(AuthError):
    """A config, credentials or ``.wekan`` file can't be read or is incomplete.

    A kind of ``AuthError`` (exit code 5): either way the tool can't log in, or doesn't know what to log in with.
    """


def config_dir() -> Path:
    """Return the tool's config folder (``$XDG_CONFIG_HOME/wekan``, default ``~/.config/wekan``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "wekan"


@dataclass(frozen=True)
class Credentials:
    """Login details for one Wekan account.

    Attributes:
        url: Base URL of the Wekan server, without a trailing slash.
        username: The account's username.
        password: The account's password. Left out of ``repr`` so it can't end up in output by accident.
        path: The file the credentials came from.
        source: How that file was chosen (``--credentials``, ``WEKAN_CREDENTIALS`` or ``default``).
    """

    url: str
    username: str
    password: str = field(repr=False)
    path: Path
    source: str


def parse_credentials(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines.

    Splits on the first ``=`` only (a password may contain ``=``), strips spaces around keys and values, and skips
    blank lines and ``#`` comments.

    Args:
        text: The file's contents.

    Returns:
        The keys and values found.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def credentials_path(override: Path | None = None) -> tuple[Path, str]:
    """Choose the credentials file.

    Args:
        override: The ``--credentials`` option, if given.

    Returns:
        The path and where the choice came from.
    """
    if override is not None:
        return override.expanduser(), "--credentials"
    env = os.environ.get(CREDENTIALS_ENV)
    if env:
        return Path(env).expanduser(), CREDENTIALS_ENV
    return config_dir() / "credentials", "default"


def load_credentials(override: Path | None = None) -> Credentials:
    """Read the credentials file.

    Args:
        override: The ``--credentials`` option, if given.

    Returns:
        The credentials.

    Raises:
        ConfigError: The file is missing, unreadable, or lacks a required key. The message names the file and the
            missing keys, never a value.
    """
    path, source = credentials_path(override)
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"no credentials file at {path} (see README: Credentials)") from None
    except OSError as exc:
        raise ConfigError(f"can't read credentials file {path}: {exc.strerror}") from None
    values = parse_credentials(text)
    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise ConfigError(f"credentials file {path} lacks {', '.join(missing)}")
    return Credentials(
        url=values["WEKAN_URL"].rstrip("/"),
        username=values["WEKAN_USERNAME"],
        password=values["WEKAN_PASSWORD"],
        path=path,
        source=source,
    )


def is_private(path: Path) -> bool:
    """Return True when no one but the owner can read or write the file (mode 600 or stricter)."""
    mode = path.stat().st_mode
    return not mode & (stat.S_IRWXG | stat.S_IRWXO)


@dataclass(frozen=True)
class Aliases:
    """Names from ``config.toml``: board aliases and user aliases (alias → ID)."""

    boards: dict[str, str] = field(default_factory=dict[str, str])
    users: dict[str, str] = field(default_factory=dict[str, str])
    path: Path | None = None


def _string_table(data: dict[str, Any], name: str, path: Path) -> dict[str, str]:
    table: object = data.get(name, {})
    entries = cast(dict[str, object], table) if isinstance(table, dict) else None
    if entries is None or not all(isinstance(v, str) for v in entries.values()):
        raise ConfigError(f'{path}: [{name}] must hold name = "id" lines')
    return {k: str(v) for k, v in entries.items()}


def load_aliases(path: Path | None = None) -> Aliases:
    """Read board and user aliases from ``config.toml``.

    Args:
        path: The file to read; defaults to ``config_dir() / "config.toml"``.

    Returns:
        The aliases; empty when the file doesn't exist.

    Raises:
        ConfigError: The file isn't valid TOML or has the wrong shape.
    """
    path = path or config_dir() / "config.toml"
    if not path.exists():
        return Aliases()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} isn't valid TOML: {exc}") from None
    return Aliases(boards=_string_table(data, "boards", path), users=_string_table(data, "users", path), path=path)


def find_dotfile(start: Path) -> Path | None:
    """Find ``.wekan`` in ``start`` or the nearest folder above it, the way git finds ``.git``.

    Args:
        start: The folder to start in (usually the current folder).

    Returns:
        The file, or None when there is none up to the root.
    """
    for folder in (start, *start.parents):
        candidate = folder / DOTFILE
        if candidate.is_file():
            return candidate
    return None


def read_dotfile(path: Path) -> str:
    """Read the board from a ``.wekan`` file (``board = "alias or ID"``).

    Raises:
        ConfigError: The file isn't valid TOML or has no ``board`` string.
    """
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} isn't valid TOML: {exc}") from None
    board = data.get("board")
    if not isinstance(board, str) or not board.strip():
        raise ConfigError(f'{path} needs a line: board = "alias or ID"')
    return board.strip()


@dataclass(frozen=True)
class BoardRef:
    """The board the user asked for, before it's matched against the real boards."""

    value: str
    source: str


def board_ref(flag: str | None, cwd: Path | None = None) -> BoardRef:
    """Pick the board: ``--board`` > ``WEKAN_BOARD`` > ``.wekan``.

    Args:
        flag: The ``--board`` option, if given.
        cwd: Folder to start the ``.wekan`` search in; defaults to the current folder.

    Returns:
        The board as given (alias, ID or title) and where it came from.

    Raises:
        NotFoundError: No board given anywhere.
    """
    if flag:
        return BoardRef(flag, "--board")
    env = os.environ.get(BOARD_ENV)
    if env:
        return BoardRef(env, BOARD_ENV)
    dotfile = find_dotfile(cwd or Path.cwd())
    if dotfile is not None:
        return BoardRef(read_dotfile(dotfile), str(dotfile))
    raise NotFoundError(f"no board given: use --board, {BOARD_ENV}, or a {DOTFILE} file")
