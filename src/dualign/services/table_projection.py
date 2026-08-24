"""Pure ownership projection for the seven-column alignment tables.

The repair state stores rows because rows are convenient for text editing.  A
table cell, however, may describe an original segment, the current relation,
or one current text member.  This module projects those different ownership
scopes before Qt rendering; spans and internal boundaries are consequences of
ownership rather than independent GUI rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable

from dualign.models.marker import is_merge

# Semantic columns before an optional GUI offset / relation-number column.
INITIAL_TYPE = 0
INITIAL_SCORE = 1
CURRENT_STATUS = 2
CURRENT_SCORE = 3
SOURCE_TEXT = 4
TARGET_TEXT = 5


@dataclass(frozen=True)
class TableCellProjection:
    """Derived ownership for one rendered row sequence."""

    spans: dict[tuple[int, int], tuple[int, int]]
    covered_cells: frozenset[tuple[int, int]]
    divider_cells: frozenset[tuple[int, int]]

    def covered_rows(self, column: int) -> frozenset[int]:
        return frozenset(row for row, col in self.covered_cells if col == column)


def current_relation_is_group_scoped(rows: Iterable) -> bool:
    """Whether multiple display rows describe one current semantic relation."""
    rows = tuple(rows)
    if len(rows) <= 1:
        return False
    first = rows[0]
    return is_merge(first.marker) or first.n_src != first.n_tgt


def _initial_segments(rows, start: int, end: int) -> list[tuple[int, int]]:
    """Recover initial relation segments from their explicit anchor labels."""
    result: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        while cursor < end and rows[cursor].init_type == "":
            cursor += 1
        if cursor >= end:
            break
        segment_start = cursor
        key = rows[cursor].init_type
        cursor += 1
        while cursor < end and rows[cursor].init_type == "":
            cursor += 1
        # A repeated non-empty key is a new explicit anchor too.  Labels are
        # display values, not identities, so equality must never fuse segments.
        result.append((segment_start, cursor))
    return result or [(start, end)]


def _display_group_key(row) -> Hashable:
    """Return an explicit view group when available, otherwise the relation id."""
    explicit = getattr(row, "display_group_id", None)
    return explicit if explicit is not None else ("relation", row.ordinal)


def project_table_cells(
    rows: list,
    *,
    col_offset: int = 0,
    relation_col: int | None = None,
) -> TableCellProjection:
    """Project row data to cell owners, spans, coverage and merge boundaries."""
    column_count = 6 + col_offset
    if relation_col is not None:
        column_count = max(column_count, relation_col + 1)

    # A unique default owner keeps unrelated row cells independent even when
    # their displayed values happen to be identical.
    owners: list[list[Hashable]] = [
        [("row", row, col) for col in range(column_count)] for row in range(len(rows))
    ]

    i = 0
    while i < len(rows):
        group_key = _display_group_key(rows[i])
        j = i + 1
        while j < len(rows) and _display_group_key(rows[j]) == group_key:
            j += 1

        if relation_col is not None:
            owner = ("relation", i)
            for row in range(i, j):
                owners[row][relation_col] = owner

        for segment_start, segment_end in _initial_segments(rows, i, j):
            for semantic_col in (INITIAL_TYPE, INITIAL_SCORE):
                col = semantic_col + col_offset
                owner = ("initial", segment_start, semantic_col)
                for row in range(segment_start, segment_end):
                    owners[row][col] = owner

        group_rows = rows[i:j]
        if current_relation_is_group_scoped(group_rows):
            for semantic_col in (CURRENT_STATUS, CURRENT_SCORE):
                col = semantic_col + col_offset
                owner = ("current", i, semantic_col)
                for row in range(i, j):
                    owners[row][col] = owner

            first = rows[i]
            short_col = None
            if first.n_src < first.n_tgt:
                short_col = SOURCE_TEXT + col_offset
            elif first.n_src > first.n_tgt:
                short_col = TARGET_TEXT + col_offset
            if short_col is not None:
                owner = ("current-side", i, short_col)
                for row in range(i, j):
                    owners[row][short_col] = owner
        i = j

    spans: dict[tuple[int, int], tuple[int, int]] = {}
    covered: set[tuple[int, int]] = set()
    for col in range(column_count):
        row = 0
        while row < len(rows):
            end = row + 1
            while end < len(rows) and owners[end][col] == owners[row][col]:
                end += 1
            if end - row > 1:
                spans[(row, col)] = (end - row, 1)
                covered.update(
                    (covered_row, col) for covered_row in range(row + 1, end)
                )
            row = end

    # A dashed boundary means: still inside one explicit merge relation, but
    # this text side has distinct row members.  The short side has one owner
    # and therefore one span, so it naturally receives no internal divider.
    dividers: set[tuple[int, int]] = set()
    for row in range(len(rows) - 1):
        if _display_group_key(rows[row]) != _display_group_key(rows[row + 1]):
            continue
        if not is_merge(rows[row].marker):
            continue
        for semantic_col in (SOURCE_TEXT, TARGET_TEXT):
            col = semantic_col + col_offset
            if owners[row][col] != owners[row + 1][col]:
                dividers.add((row, col))

    return TableCellProjection(
        spans=spans,
        covered_cells=frozenset(covered),
        divider_cells=frozenset(dividers),
    )
