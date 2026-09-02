"""Monotone evidence scaffold for production alignment."""

from __future__ import annotations

import numpy as np


def _positive_evidence(evidence: np.ndarray) -> np.ndarray:
    bits = np.asarray(evidence, dtype=np.float64)
    if bits.ndim != 2:
        raise ValueError("顺序证据矩阵必须是二维数组")
    if not np.all(np.isfinite(bits)):
        raise ValueError("顺序证据矩阵必须只包含有限值")
    return np.maximum(bits, 0.0)


def maximum_monotone_evidence(
    evidence: np.ndarray,
) -> tuple[float, tuple[tuple[int, int, float], ...]]:
    """Return the exact maximum-weight strictly monotone one-to-one matching."""

    weights = _positive_evidence(evidence)
    if not weights.size or not np.any(weights > 0.0):
        return 0.0, ()

    source_count, target_count = weights.shape
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
