"""Statistical diagnostics for alignment existence and monotone order."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class MonotoneOrderEvidence:
    """Deterministic order evidence extracted from mutual nearest pairs."""

    mutual_pairs: int
    chain_length: int
    chain_weight: float
    coverage: float
    kendall_tau: float

    @property
    def out_of_chain_pairs(self) -> int:
        return self.mutual_pairs - self.chain_length


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


def fit_beta_binomial_order_model(counts: np.ndarray) -> tuple[float, float]:
    """Fit document-level order-error heterogeneity by method of moments.

    ``counts`` contains ``(out_of_chain_pairs, mutual_pairs)`` rows.  Each
    document has a latent order-error rate drawn from Beta(alpha, beta), while
    its observed errors are binomial conditional on that rate.  The beta layer
    prevents a long but otherwise parallel document from being rejected merely
    because independent-binomial variance was too optimistic.
    """

    values = np.asarray(counts, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 2 or values.shape[0] < 2:
        raise ValueError("顺序错误率校准至少需要两个 (错误数, 总数) 文档")
    failures, totals = values.T
    if np.any(totals <= 0) or np.any(failures < 0) or np.any(failures > totals):
        raise ValueError("顺序错误率校准计数无效")
    rates = failures / totals
    mean = float(np.mean(rates))
    variance = float(np.var(rates, ddof=1))
    if not 0.0 < mean < 1.0 or variance <= 0.0:
        raise ValueError("顺序错误率 calibration 缺少可估计的文档间变异")
    concentration = mean * (1.0 - mean) / variance - 1.0
    if concentration <= 0.0:
        raise ValueError("顺序错误率方差无法由 beta-binomial 模型表达")
    return mean * concentration, (1.0 - mean) * concentration


def beta_binomial_upper_p(
    failures: int,
    total: int,
    alpha: float,
    beta: float,
) -> float:
    """Posterior-predictive upper-tail probability for order failures."""

    if not 0 <= failures <= total or total < 1 or alpha <= 0.0 or beta <= 0.0:
        raise ValueError("beta-binomial 参数或计数无效")
    if failures == 0:
        return 1.0

    def log_beta(left, right):
        return math.lgamma(left) + math.lgamma(right) - math.lgamma(left + right)

    baseline = log_beta(alpha, beta)
    logs = [
        math.lgamma(total + 1)
        - math.lgamma(value + 1)
        - math.lgamma(total - value + 1)
        + log_beta(value + alpha, total - value + beta)
        - baseline
        for value in range(failures, total + 1)
    ]
    maximum = max(logs)
    return float(
        min(1.0, math.exp(maximum) * math.fsum(math.exp(v - maximum) for v in logs))
    )


def mutual_best_pairs(scores: np.ndarray) -> list[tuple[int, int]]:
    matrix = np.asarray(scores, dtype=np.float64)
    if matrix.ndim != 2 or not matrix.shape[0] or not matrix.shape[1]:
        return []
    row_best = np.argmax(matrix, axis=1)
    column_best = np.argmax(matrix, axis=0)
    return [
        (source, int(target))
        for source, target in enumerate(row_best)
        if column_best[target] == source
    ]


def _weighted_increasing_chain_indices(
    target_indices: np.ndarray,
    weights: np.ndarray,
) -> tuple[float, int, list[int]]:
    if not target_indices.size:
        return 0.0, 0, []
    ordered_values = {
        value: rank + 1 for rank, value in enumerate(sorted(target_indices))
    }
    size = len(ordered_values)
    tree = [(0.0, 0, -1)] * (size + 1)
    predecessors = np.full(target_indices.size, -1, dtype=np.int32)

    def better(left, right):
        return left if (left[0], left[1]) >= (right[0], right[1]) else right

    def query(position):
        result = (0.0, 0, -1)
        while position:
            result = better(result, tree[position])
            position -= position & -position
        return result

    def update(position, value):
        while position <= size:
            tree[position] = better(tree[position], value)
            position += position & -position

    for index, (target, weight) in enumerate(zip(target_indices, weights)):
        position = ordered_values[int(target)]
        previous_weight, previous_length, previous_index = query(position - 1)
        predecessors[index] = previous_index
        update(
            position,
            (previous_weight + float(weight), previous_length + 1, index),
        )
    total_weight, length, cursor = query(size)
    selected = []
    while cursor >= 0:
        selected.append(int(cursor))
        cursor = int(predecessors[cursor])
    selected.reverse()
    return total_weight, length, selected


def _weighted_increasing_chain(
    target_indices: np.ndarray,
    weights: np.ndarray,
) -> tuple[float, int]:
    weight, length, _indices = _weighted_increasing_chain_indices(
        target_indices, weights
    )
    return weight, length


def mutual_monotone_chain(
    scores: np.ndarray,
    evidence: np.ndarray,
) -> list[tuple[int, int, float]]:
    """Return the maximum-weight monotone chain of mutual nearest pairs.

    This is a rank-derived scaffold, not a set of mandatory alignment edges.
    It has no cosine threshold or trust-margin parameter.
    """

    matrix = np.asarray(scores, dtype=np.float64)
    bits = np.asarray(evidence, dtype=np.float64)
    if matrix.ndim != 2 or bits.shape != matrix.shape:
        raise ValueError("分数和证据矩阵必须形状一致")
    pairs = mutual_best_pairs(matrix)
    if not pairs:
        return []
    targets = np.array([target for _source, target in pairs], dtype=np.int32)
    weights = np.array(
        [max(0.0, float(bits[source, target])) for source, target in pairs],
        dtype=np.float64,
    )
    _weight, _length, selected = _weighted_increasing_chain_indices(targets, weights)
    return [
        (pairs[index][0], pairs[index][1], float(weights[index])) for index in selected
    ]


def _inversion_count(values: np.ndarray) -> int:
    if not values.size:
        return 0
    ordered_values = {value: rank + 1 for rank, value in enumerate(sorted(values))}
    tree = [0] * (len(ordered_values) + 1)
    inversions = 0
    seen = 0
    for value in values:
        position = ordered_values[int(value)]
        prefix = 0
        cursor = position
        while cursor:
            prefix += tree[cursor]
            cursor -= cursor & -cursor
        inversions += seen - prefix
        cursor = position
        while cursor < len(tree):
            tree[cursor] += 1
            cursor += cursor & -cursor
        seen += 1
    return inversions


def monotone_order_evidence(
    scores: np.ndarray,
    evidence: np.ndarray,
) -> MonotoneOrderEvidence:
    """Summarize monotonicity without a simulation budget or score threshold.

    The maximum-weight increasing chain is the same object used as the
    alignment scaffold.  Its omitted-pair count is calibrated directly on
    known parallel documents by the beta-binomial model.  A former
    permutation test was removed from the decision path: it tested a second,
    less relevant null (random order), duplicated the calibrated order gate,
    and made the result depend on an arbitrary number of shuffles.
    """

    matrix = np.asarray(scores, dtype=np.float64)
    bits = np.asarray(evidence, dtype=np.float64)
    if matrix.ndim != 2 or bits.shape != matrix.shape:
        raise ValueError("分数和证据矩阵必须形状一致")
    pairs = mutual_best_pairs(matrix)
    pair_count = len(pairs)
    if pair_count < 2:
        return MonotoneOrderEvidence(
            pair_count,
            pair_count,
            0.0,
            pair_count / max(1, min(matrix.shape)),
            0.0,
        )

    targets = np.array([target for _source, target in pairs], dtype=np.int32)
    weights = np.array(
        [max(0.0, float(bits[source, target])) for source, target in pairs],
        dtype=np.float64,
    )
    observed_weight, observed_length = _weighted_increasing_chain(targets, weights)
    inversions = _inversion_count(targets)
    pair_total = pair_count * (pair_count - 1) / 2
    tau = 1.0 - 2.0 * inversions / pair_total
    return MonotoneOrderEvidence(
        mutual_pairs=pair_count,
        chain_length=observed_length,
        chain_weight=float(observed_weight),
        coverage=observed_length / max(1, min(matrix.shape)),
        kendall_tau=float(tau),
    )
