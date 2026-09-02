"""Search projection for the current bilingual relation view."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextSearchMatch:
    """One matching current-text cell in stable table coordinates."""

    ordinal: int
    sub: int
    side: str


def find_current_text(repair_state, query: str) -> tuple[TextSearchMatch, ...]:
    """Find text in the full current chapter, independent of GUI filtering.

    Matching is Unicode-aware and case-insensitive.  A cell contributes at
    most one navigation stop even when the query occurs multiple times in it.
    """

    needle = query.strip().casefold()
    if not needle:
        return ()

    matches: list[TextSearchMatch] = []
    for group in repair_state.current.groups:
        for row in group.rows:
            if needle in row.src_text.casefold():
                matches.append(TextSearchMatch(row.ordinal, row.sub, "src"))
            if needle in row.tgt_text.casefold():
                matches.append(TextSearchMatch(row.ordinal, row.sub, "tgt"))
    return tuple(matches)
