"""Canonical effective-source vocabulary and trust ordering.

The effective source describes the actor responsible for the current result,
not a separate review history.  ``agent`` is accepted only at compatibility
boundaries and normalized to ``ai``.
"""

from __future__ import annotations

from collections.abc import Iterable

SOURCE_NONE = "none"
SOURCE_AUTO = "auto"
SOURCE_AI = "ai"
SOURCE_USER = "user"

ALL_EFFECTIVE_SOURCES = (SOURCE_NONE, SOURCE_AUTO, SOURCE_AI, SOURCE_USER)
SOURCE_LABELS = {value: value for value in ALL_EFFECTIVE_SOURCES}

_SOURCE_ALIASES = {"agent": SOURCE_AI}
_SOURCE_RANK = {source: rank for rank, source in enumerate(ALL_EFFECTIVE_SOURCES)}


def canonical_source(value: object, *, default: str = SOURCE_NONE) -> str:
    """Return a canonical source, accepting the legacy ``agent`` spelling."""

    source = str(value or "").strip().lower()
    source = _SOURCE_ALIASES.get(source, source)
    return source if source in _SOURCE_RANK else default


def highest_source(values: Iterable[object], *, default: str = SOURCE_NONE) -> str:
    """Return the most trusted canonical source in ``values``."""

    sources = (canonical_source(value, default=default) for value in values)
    return max(sources, key=_SOURCE_RANK.__getitem__, default=default)
