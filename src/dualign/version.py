"""Project version sourced from installed package metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dualign")
except PackageNotFoundError:  # Direct source-tree execution without installation.
    __version__ = "0+unknown"


__all__ = ["__version__"]
