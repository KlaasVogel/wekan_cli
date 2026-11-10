"""The token cache in ``~/.cache/wekan/`` (folder 700, file 600).

One login token lasts about 90 days. Keeping it means one login per token instead of one per command, and Wekan has
no working logout, so every extra login leaves another valid token behind.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


def cache_dir() -> Path:
    """Return the tool's cache folder (``$XDG_CACHE_HOME/wekan``, default ``~/.cache/wekan``)."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "wekan"


@dataclass(frozen=True)
class CachedToken:
    """A login token, with the server and account it belongs to.

    Attributes:
        url: The Wekan server it was issued by.
        username: The account it belongs to.
        user_id: The account's user ID (needed for ``X-User-Id`` and some routes).
        token: The token itself. Left out of ``repr``.
        expires: Expiry time as Wekan reported it (ISO 8601), or "".
    """

    url: str
    username: str
    user_id: str
    token: str = field(repr=False)
    expires: str = ""


class TokenCache:
    """Reads and writes the cached token."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cache_dir() / "token.json"

    def load(self, url: str, username: str) -> CachedToken | None:
        """Return the cached token for this server and account, or None (missing, unreadable or someone else's)."""
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        data = cast(dict[str, Any], data)
        try:
            cached = CachedToken(
                url=str(data["url"]),
                username=str(data["username"]),
                user_id=str(data["user_id"]),
                token=str(data["token"]),
                expires=str(data.get("expires", "")),
            )
        except KeyError:
            return None
        if cached.url != url or cached.username != username:
            return None
        return cached

    def save(self, cached: CachedToken) -> None:
        """Write the token atomically, with the folder at 700 and the file at 600."""
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        payload = json.dumps(
            {
                "url": cached.url,
                "username": cached.username,
                "user_id": cached.user_id,
                "token": cached.token,
                "expires": cached.expires,
            }
        )
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".token-", suffix=".tmp")  # mkstemp creates it with mode 600
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def clear(self) -> None:
        """Forget the cached token (locally only: Wekan keeps it valid until it expires)."""
        self.path.unlink(missing_ok=True)
