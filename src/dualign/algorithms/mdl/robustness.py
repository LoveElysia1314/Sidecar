"""Statistical diagnostics for alignment existence and monotone order."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class MonotoneEvidenceComparison:
    """Best order-free and monotone explanations of positive rank evidence."""

    order_free_bits: float
    monotone_bits: float
    relative_loss: float
    order_free_pairs: tuple[tuple[int, int, float], ...] = ()
    monotone_pairs: tuple[tuple[int, int, float], ...] = ()


def _positive_evidence(evidence: np.ndarray) -> np.ndarray:
    bits = np.asarray(evidence, dtype=np.float64)
    if bits.ndim != 2:
        raise ValueError("顺序证据矩阵必须是二维数组")
    if not np.all(np.isfinite(bits)):
        raise ValueError("顺序证据矩阵必须只包含有限值")
    return np.maximum(bits, 0.0)


def maximum_order_free_evidence(
    evidence: np.ndarray,
) -> tuple[float, tuple[tuple[int, int, float], ...]]:
    """Return the exact maximum-weight one-to-one matching.

    Zero-weight assignments represent unmatched rows.  Assigning every item
    on the smaller side is therefore equivalent to adding private zero-weight
    dummy vertices, without increasing the rectangular assignment problem.
    """

    original = _positive_evidence(evidence)
    if not original.size:
        return 0.0, ()

    transposed = original.shape[0] > original.shape[1]
    weights = original.T if transposed else original
    row_count, column_count = weights.shape
    maximum = float(np.max(weights))
    costs = maximum - weights

    # Rectangular Hungarian algorithm.  The inner relaxation is vectorized;
    # this keeps the exact dependency-free solver practical for chapter-sized
    # matrices while preserving deterministic tie handling.
    row_potential = np.zeros(row_count + 1, dtype=np.float64)
    column_potential = np.zeros(column_count + 1, dtype=np.float64)
    matched_row = np.zeros(column_count + 1, dtype=np.int32)
    predecessor_column = np.zeros(column_count + 1, dtype=np.int32)

    for row in range(1, row_count + 1):
        matched_row[0] = row
        current_column = 0
        minimum_slack = np.full(column_count + 1, np.inf, dtype=np.float64)
        used = np.zeros(column_count + 1, dtype=bool)
        while True:
            used[current_column] = True
            current_row = int(matched_row[current_column])
            slack = (
                costs[current_row - 1]
                - row_potential[current_row]
                - column_potential[1:]
            )
            available = ~used[1:]
            improved = available & (slack < minimum_slack[1:])
            minimum_slack[1:][improved] = slack[improved]
            predecessor_column[1:][improved] = current_column

            candidates = np.where(available, minimum_slack[1:], np.inf)
            next_column = int(np.argmin(candidates)) + 1
            delta = float(candidates[next_column - 1])
            row_potential[matched_row[used]] += delta
            column_potential[used] -= delta
            minimum_slack[~used] -= delta
            current_column = next_column
            if matched_row[current_column] == 0:
                break

        while True:
            previous_column = int(predecessor_column[current_column])
            matched_row[current_column] = matched_row[previous_column]
            current_column = previous_column
            if current_column == 0:
                break

    pairs = []
    for column in range(1, column_count + 1):
        row = int(matched_row[column])
        if not row:
            continue
        weight = float(weights[row - 1, column - 1])
        if weight <= 0.0:
            continue
        source, target = (column - 1, row - 1) if transposed else (row - 1, column - 1)
        pairs.append((source, target, weight))
    pairs.sort(key=lambda item: (item[0], item[1]))
    return float(math.fsum(item[2] for item in pairs)), tuple(pairs)


def maximum_monotone_evidence(
    evidence: np.ndarray,
) -> tuple[float, tuple[tuple[int, int, float], ...]]:
    """Return the exact maximum-weight strictly monotone one-to-one matching."""

    weights = _positive_evidence(evidence)
    if not weights.size:
        return 0.0, ()
    if not np.any(weights > 0.0):
        return 0.0, ()

    source_count, target_count = weights.shape
    # Weighted-LCS recurrence:
    #   D[i,j] = max(D[i-1,j], D[i,j-1], D[i-1,j-1] + w[i,j])
    # For one source row, the left dependency is exactly the prefix maximum of
    # every diagonal candidate. NumPy evaluates that prefix in compiled code;
    # the full table is retained only for exact deterministic backtracking.
    table = np.zeros((source_count + 1, target_count + 1), dtype=np.float64)
    for source in range(source_count):
        diagonal_candidates = table[source, :-1] + weights[source]
        table[source + 1, 1:] = np.maximum(
            table[source, 1:],
            np.maximum.accumulate(diagonal_candidates),
        )

    selected = []
    source = source_count
    target = target_count
    while source and target:
        weight = float(weights[source - 1, target - 1])
        if (
            weight > 0.0
            and table[source, target] == table[source - 1, target - 1] + weight
        ):
            selected.append((source - 1, target - 1, weight))
            source -= 1
            target -= 1
        elif table[source, target] == table[source - 1, target]:
            source -= 1
        else:
            target -= 1
    selected.reverse()
    return float(table[-1, -1]), tuple(selected)


def compare_monotone_evidence(evidence: np.ndarray) -> MonotoneEvidenceComparison:
    """Compare order-free evidence with its best monotone explanation."""

    order_free_bits, order_free_pairs = maximum_order_free_evidence(evidence)
    monotone_bits, monotone_pairs = maximum_monotone_evidence(evidence)
    relative_loss = (
        max(0.0, min(1.0, (order_free_bits - monotone_bits) / order_free_bits))
        if order_free_bits > 0.0
        else 0.0
    )
    return MonotoneEvidenceComparison(
        order_free_bits=order_free_bits,
        monotone_bits=monotone_bits,
        relative_loss=relative_loss,
        order_free_pairs=order_free_pairs,
        monotone_pairs=monotone_pairs,
    )


def symmetric_nearest_score(scores: np.ndarray) -> float:
    """Symmetric document-level nearest-neighbour cosine statistic."""

    matrix = np.asarray(scores, dtype=np.float64)
    if matrix.ndim != 2 or not matrix.shape[0] or not matrix.shape[1]:
        raise ValueError("文档存在性统计需要非空二维分数矩阵")
    return 0.5 * (
        float(np.mean(np.max(matrix, axis=1))) + float(np.mean(np.max(matrix, axis=0)))
    )


def conformal_upper_p(value: float, null_values: np.ndarray) -> float:
    """Finite-sample conformal p-value for a large-is-significant statistic."""

    null = np.asarray(null_values, dtype=np.float64)
    if null.ndim != 1 or not null.size:
        raise ValueError("conformal null 样本不能为空")
    return float((1 + np.count_nonzero(null >= value)) / (null.size + 1))
