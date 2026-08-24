"""Self-normalizing minimum-description-length alignment experiment.

This prototype has no learned corpus prior and no semantic, gap, merge, or
span threshold. Embedding scores are converted to mutual rank-code savings
inside the current document. Alignment structure is selected with an
enumerative universal code over all admissible edit scripts of the same
complexity.

The grammar contains 1:1, arbitrary contiguous N:1 and 1:N relations, plus
1:0 and 0:1 gaps. A span of length N has structural complexity N - 1. General
spans use additive atomic evidence and prefix-optimal recurrences, so they do
not require joined-span embeddings or explicit span enumeration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

IndexTuple = tuple[int, ...]
Operation = tuple[IndexTuple, IndexTuple, float]
_Backtrace = tuple[str, int]

_NEGATIVE_INFINITY = float("-inf")


def normalize_embeddings(vectors: np.ndarray) -> np.ndarray:
    """Return row-normalized embeddings for cosine-similarity matrices."""

    matrix = np.asarray(vectors, dtype=np.float64)
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def _harmonic_number(size: int) -> float:
    if size < 1:
        return 1.0
    return math.fsum(1.0 / value for value in range(1, size + 1))


def mutual_rank_code_evidence(scores: np.ndarray) -> np.ndarray:
    """Convert a score matrix to conservative, bidirectional code savings.

    A rank ``r`` among ``k`` alternatives receives the finite Zipf universal
    code ``log2(r * H_k)``. Subtracting it from the uniform code ``log2(k)``
    yields bits saved by semantic ordering. The weaker direction wins, so an
    edge must be distinctive from both documents' perspectives.

    Only score ordering matters; every strictly increasing score transform
    therefore produces exactly the same evidence matrix.
    """

    matrix = np.asarray(scores, dtype=np.float64)
    if matrix.ndim != 2:
        raise ValueError("分数矩阵必须是二维数组")
    n, m = matrix.shape
    if not n or not m:
        return np.empty_like(matrix)

    row_ranks = np.empty((n, m), dtype=np.int32)
    column_ranks = np.empty((n, m), dtype=np.int32)
    for i in range(n):
        ordered = np.sort(matrix[i, :])
        row_ranks[i, :] = m - np.searchsorted(ordered, matrix[i, :], side="left")
    for j in range(m):
        ordered = np.sort(matrix[:, j])
        column_ranks[:, j] = n - np.searchsorted(ordered, matrix[:, j], side="left")

    row_savings = np.log2(m / (_harmonic_number(m) * row_ranks))
    column_savings = np.log2(n / (_harmonic_number(n) * column_ranks))
    return np.minimum(row_savings, column_savings)


def _elias_delta_length(value: int) -> int:
    """Bit length of the Elias-delta code for a positive integer."""

    if value < 1:
        raise ValueError("Elias-delta 只能编码正整数")
    bit_length = value.bit_length()
    return bit_length + 2 * (bit_length.bit_length() - 1)


def _set_max(states: dict[int, float], complexity: int, semantic: float) -> None:
    current = states.get(complexity)
    if current is None or semantic > current:
        states[complexity] = semantic


def _prune_dominated_states(states: dict[int, float]) -> None:
    """Drop states no better than a path with lower structural complexity."""

    strongest = _NEGATIVE_INFINITY
    for complexity in sorted(tuple(states)):
        semantic = states[complexity]
        if semantic <= strongest:
            del states[complexity]
        else:
            strongest = semantic


def _semantic_frontier(evidence: np.ndarray) -> dict[int, float]:
    """Find terminal semantic optima for every non-dominated complexity.

    For an N:1 relation ending at ``(i, j)``, a predecessor ``(p, j-1)`` has
    resulting complexity ``c = c_prev + i - p - 1``. Rearranging gives the
    invariant key ``c_prev - p = c - i + 1``. Keeping the best predecessor per
    key turns arbitrary-span search into a prefix maximum. The 1:N recurrence
    is symmetric.
    """

    n, m = evidence.shape
    source_prefix = np.vstack(
        (np.zeros((1, m), dtype=np.float64), np.cumsum(evidence, axis=0))
    )
    target_prefix = np.hstack(
        (np.zeros((n, 1), dtype=np.float64), np.cumsum(evidence, axis=1))
    )
    vertical: list[dict[int, float]] = [{} for _j in range(m + 1)]
    previous: Optional[list[dict[int, float]]] = None

    for i in range(n + 1):
        if previous is not None:
            source_start = i - 1
            for j in range(1, m + 1):
                prefix = float(source_prefix[source_start, j - 1])
                accumulator = vertical[j]
                for complexity, semantic in previous[j - 1].items():
                    _set_max(
                        accumulator,
                        complexity - source_start,
                        semantic - prefix,
                    )
                _prune_dominated_states(accumulator)

        current: list[dict[int, float]] = [{} for _j in range(m + 1)]
        horizontal: dict[int, float] = {}
        for j in range(m + 1):
            states = current[j]
            if i == 0 and j == 0:
                states[0] = 0.0
            if previous is not None:
                for complexity, semantic in previous[j].items():
                    _set_max(states, complexity + 1, semantic)
            if j:
                for complexity, semantic in current[j - 1].items():
                    _set_max(states, complexity + 1, semantic)

            if previous is not None and j:
                target_start = j - 1
                prefix = float(target_prefix[i - 1, target_start])
                for complexity, semantic in previous[target_start].items():
                    _set_max(
                        horizontal,
                        complexity - target_start,
                        semantic - prefix,
                    )
                _prune_dominated_states(horizontal)

                source_end_prefix = float(source_prefix[i, j - 1])
                for key, semantic in vertical[j].items():
                    _set_max(states, key + i - 1, semantic + source_end_prefix)

                target_end_prefix = float(target_prefix[i - 1, j])
                for key, semantic in horizontal.items():
                    _set_max(states, key + j - 1, semantic + target_end_prefix)

            _prune_dominated_states(states)
        previous = current

    if previous is None:
        return {0: 0.0}
    return previous[m]


def _structure_counts(n: int, m: int, max_complexity: int) -> dict[int, int]:
    """Count all full-grammar scripts by complexity combinatorially.

    Every semantic operation consumes at least one row from each side and has
    complexity ``source_size + target_size - 2``; every gap has complexity
    equal to its one consumed row.  Therefore a script of complexity ``c``
    contains exactly ``r = (n + m - c) / 2`` semantic operations.

    For fixed ``r``, distribute source/target excess rows over disjoint
    semantic-operation slots, then interleave the remaining source and target
    gaps.  Since ``n-r`` and ``m-r`` are at most ``c``, runtime depends on the
    small requested complexity frontier rather than on ``n*m``.
    """

    def positive_compositions(total: int, parts: int) -> int:
        if total == 0:
            return 1 if parts == 0 else 0
        if parts < 1 or parts > total:
            return 0
        return math.comb(total - 1, parts - 1)

    def semantic_allocations(
        relations: int,
        source_excess: int,
        target_excess: int,
    ) -> int:
        total = 0
        source_parts = (
            range(0, 1)
            if source_excess == 0
            else range(1, min(relations, source_excess) + 1)
        )
        for source_slots in source_parts:
            remaining = relations - source_slots
            target_parts = (
                range(0, 1)
                if target_excess == 0
                else range(1, min(remaining, target_excess) + 1)
            )
            for target_slots in target_parts:
                total += (
                    math.comb(relations, source_slots)
                    * math.comb(remaining, target_slots)
                    * positive_compositions(source_excess, source_slots)
                    * positive_compositions(target_excess, target_slots)
                )
        return total

    counts: dict[int, int] = {}
    for complexity in range(abs(n - m), min(max_complexity, n + m) + 1):
        relation_numerator = n + m - complexity
        if relation_numerator % 2:
            continue
        relations = relation_numerator // 2
        if relations < 0 or relations > min(n, m):
            continue
        maximum_source_excess = n - relations
        maximum_target_excess = m - relations
        count = 0
        for source_excess in range(maximum_source_excess + 1):
            source_gaps = maximum_source_excess - source_excess
            for target_excess in range(maximum_target_excess + 1):
                target_gaps = maximum_target_excess - target_excess
                allocations = semantic_allocations(
                    relations, source_excess, target_excess
                )
                if not allocations:
                    continue
                operation_count = relations + source_gaps + target_gaps
                interleavings = math.comb(operation_count, source_gaps) * math.comb(
                    operation_count - source_gaps, target_gaps
                )
                count += interleavings * allocations
        if count:
            counts[complexity] = count
    return counts


@dataclass(frozen=True)
class MDLAlignmentResult:
    all_ops: list[Operation]
    complexity: int
    semantic_bits: float
    structure_bits: float
    objective_bits: float
    frontier: tuple[tuple[int, float, float, float], ...]


def _collapse_gaps(operations: list[Operation]) -> list[Operation]:
    collapsed: list[Operation] = []
    for source, target, score in operations:
        if collapsed and source and not target and not collapsed[-1][1]:
            old_source, _, _ = collapsed[-1]
            collapsed[-1] = (old_source + source, (), 0.0)
        elif collapsed and target and not source and not collapsed[-1][0]:
            _, old_target, _ = collapsed[-1]
            collapsed[-1] = ((), old_target + target, 0.0)
        else:
            collapsed.append((source, target, score))
    return collapsed


def _reconstruct_fixed_complexity(
    evidence: np.ndarray,
    scores: np.ndarray,
    target_complexity: int,
) -> list[Operation]:
    """Recover the best general-span path for one exact complexity."""

    n, m = evidence.shape
    source_evidence_prefix = np.vstack(
        (np.zeros((1, m), dtype=np.float64), np.cumsum(evidence, axis=0))
    )
    target_evidence_prefix = np.hstack(
        (np.zeros((n, 1), dtype=np.float64), np.cumsum(evidence, axis=1))
    )
    source_score_prefix = np.vstack(
        (np.zeros((1, m), dtype=np.float64), np.cumsum(scores, axis=0))
    )
    target_score_prefix = np.hstack(
        (np.zeros((n, 1), dtype=np.float64), np.cumsum(scores, axis=1))
    )

    vertical: list[dict[int, tuple[float, int, int]]] = [{} for _j in range(m + 1)]
    previous: Optional[list[dict[int, float]]] = None
    backtrace: dict[tuple[int, int, int], _Backtrace] = {}

    def update(
        states: dict[int, float],
        i: int,
        j: int,
        complexity: int,
        semantic: float,
        operation: _Backtrace,
    ) -> None:
        if complexity > target_complexity:
            return
        remaining_difference = abs((n - i) - (m - j))
        if complexity + remaining_difference > target_complexity:
            return
        current = states.get(complexity)
        if current is None or semantic > current:
            states[complexity] = semantic
            backtrace[(i, j, complexity)] = operation

    for i in range(n + 1):
        if previous is not None:
            source_start = i - 1
            for j in range(1, m + 1):
                prefix = float(source_evidence_prefix[source_start, j - 1])
                accumulator = vertical[j]
                for complexity, semantic in previous[j - 1].items():
                    key = complexity - source_start
                    candidate = semantic - prefix
                    old = accumulator.get(key)
                    if old is None or candidate > old[0]:
                        accumulator[key] = (candidate, source_start, complexity)

        current_row: list[dict[int, float]] = [{} for _j in range(m + 1)]
        horizontal: dict[int, tuple[float, int, int]] = {}
        for j in range(m + 1):
            states = current_row[j]
            if i == 0 and j == 0:
                states[0] = 0.0
            if previous is not None:
                for complexity, semantic in previous[j].items():
                    update(states, i, j, complexity + 1, semantic, ("source_gap", 1))
            if j:
                for complexity, semantic in current_row[j - 1].items():
                    update(states, i, j, complexity + 1, semantic, ("target_gap", 1))

            if previous is not None and j:
                target_start = j - 1
                prefix = float(target_evidence_prefix[i - 1, target_start])
                for complexity, semantic in previous[target_start].items():
                    key = complexity - target_start
                    candidate = semantic - prefix
                    old = horizontal.get(key)
                    if old is None or candidate > old[0]:
                        horizontal[key] = (candidate, target_start, complexity)

                source_end_prefix = float(source_evidence_prefix[i, j - 1])
                for key, (semantic, source_start, _old_complexity) in vertical[
                    j
                ].items():
                    span = i - source_start
                    update(
                        states,
                        i,
                        j,
                        key + i - 1,
                        semantic + source_end_prefix,
                        ("many_to_one", span),
                    )

                target_end_prefix = float(target_evidence_prefix[i - 1, j])
                for key, (
                    semantic,
                    target_start,
                    _old_complexity,
                ) in horizontal.items():
                    span = j - target_start
                    update(
                        states,
                        i,
                        j,
                        key + j - 1,
                        semantic + target_end_prefix,
                        ("one_to_many", span),
                    )
        previous = current_row

    if previous is None or target_complexity not in previous[m]:
        raise RuntimeError("无法重建选定复杂度的 MDL 对齐路径")

    operations: list[Operation] = []
    i, j, complexity = n, m, target_complexity
    while i or j:
        operation = backtrace.get((i, j, complexity))
        if operation is None:
            raise RuntimeError("MDL 实验路径缺少回溯操作")
        kind, span = operation
        if kind == "source_gap":
            i -= 1
            complexity -= 1
            operations.append(((i,), (), 0.0))
        elif kind == "target_gap":
            j -= 1
            complexity -= 1
            operations.append(((), (j,), 0.0))
        elif kind == "many_to_one":
            source_start = i - span
            target_index = j - 1
            raw_score = (
                source_score_prefix[i, target_index]
                - source_score_prefix[source_start, target_index]
            ) / span
            operations.append(
                (
                    tuple(range(source_start, i)),
                    (target_index,),
                    float(raw_score),
                )
            )
            i = source_start
            j = target_index
            complexity -= span - 1
        elif kind == "one_to_many":
            source_index = i - 1
            target_start = j - span
            raw_score = (
                target_score_prefix[source_index, j]
                - target_score_prefix[source_index, target_start]
            ) / span
            operations.append(
                (
                    (source_index,),
                    tuple(range(target_start, j)),
                    float(raw_score),
                )
            )
            i = source_index
            j = target_start
            complexity -= span - 1
        else:
            raise RuntimeError(f"未知 MDL 回溯操作: {kind}")
    operations.reverse()
    return _collapse_gaps(operations)


def align_evidence_lattice_mdl(
    evidence_11: np.ndarray,
    *,
    scores_11: Optional[np.ndarray] = None,
) -> MDLAlignmentResult:
    """Select a general-span alignment using semantic and structural bits."""

    evidence = np.asarray(evidence_11, dtype=np.float64)
    if evidence.ndim != 2:
        raise ValueError("1:1 证据矩阵必须是二维数组")
    n, m = evidence.shape
    scores = (
        np.asarray(scores_11, dtype=np.float64)
        if scores_11 is not None
        else np.zeros((n, m), dtype=np.float64)
    )
    if scores.shape != (n, m):
        raise ValueError(f"1:1 分数矩阵形状应为 {(n, m)}")

    terminal = _semantic_frontier(evidence)
    maximum_complexity = max(terminal)
    counts = _structure_counts(n, m, maximum_complexity)
    minimum_complexity = min(terminal)
    frontier = []
    monotone_structure_bits = 0.0
    for complexity, semantic_bits in sorted(terminal.items()):
        excess = complexity - minimum_complexity
        raw_structure_bits = math.log2(counts[complexity]) + (
            _elias_delta_length(excess + 1) - 1
        )
        monotone_structure_bits = max(monotone_structure_bits, raw_structure_bits)
        structure_bits = monotone_structure_bits
        objective = semantic_bits - structure_bits
        frontier.append((complexity, semantic_bits, structure_bits, objective))
    chosen = max(frontier, key=lambda item: (item[3], -item[0]))
    complexity, semantic_bits, structure_bits, objective = chosen

    operations = _reconstruct_fixed_complexity(evidence, scores, complexity)
    return MDLAlignmentResult(
        all_ops=operations,
        complexity=complexity,
        semantic_bits=semantic_bits,
        structure_bits=structure_bits,
        objective_bits=objective,
        frontier=tuple(frontier),
    )


def align_similarity_lattices_mdl(scores_11: np.ndarray) -> MDLAlignmentResult:
    """Self-normalize an atomic score matrix and run general-span alignment."""

    scores = np.asarray(scores_11, dtype=np.float64)
    return align_evidence_lattice_mdl(
        mutual_rank_code_evidence(scores),
        scores_11=scores,
    )
