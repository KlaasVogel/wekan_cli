"""wekan_cli: a command-line tool for a self-hosted Wekan."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("wekan-cli")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"
