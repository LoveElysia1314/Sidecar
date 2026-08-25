import itertools

import numpy as np

from dualign.algorithms.mdl.robustness import (
    compare_monotone_evidence,
    conformal_upper_p,
    maximum_monotone_evidence,
    maximum_order_free_evidence,
    symmetric_nearest_score,
)


def _reference_order_free(weights: np.ndarray) -> float:
    rows, columns = weights.shape
    if rows > columns:
        return _reference_order_free(weights.T)
    best = 0.0
    for selected_columns in itertools.permutations(range(columns), rows):
        best = max(
            best,
            sum(
                max(0.0, weights[row, column])
                for row, column in enumerate(selected_columns)
            ),
        )
    return best


def _reference_monotone(weights: np.ndarray) -> float:
    rows, columns = weights.shape
    result = np.zeros((rows + 1, columns + 1), dtype=np.float64)
    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            result[row, column] = max(
                result[row - 1, column],
                result[row, column - 1],
                result[row - 1, column - 1] + max(0.0, weights[row - 1, column - 1]),
            )
    return float(result[-1, -1])


def test_symmetric_nearest_score_rewards_clear_correspondence():
    parallel = np.eye(4)
    flat = np.full((4, 4), 0.2)

    assert symmetric_nearest_score(parallel) > symmetric_nearest_score(flat)


def test_conformal_upper_p_has_finite_sample_correction():
    null = np.array([0.1, 0.2, 0.3])

    assert conformal_upper_p(0.9, null) == 0.25
    assert conformal_upper_p(0.15, null) == 0.75


def test_monotone_comparison_separates_identity_from_reverse_order():
    ordered = compare_monotone_evidence(np.eye(8))
    reversed_order = compare_monotone_evidence(np.fliplr(np.eye(8)))

    assert ordered.relative_loss == 0.0
    assert [(source, target) for source, target, _ in ordered.monotone_pairs] == [
        (index, index) for index in range(8)
    ]
    assert reversed_order.order_free_bits == 8.0
    assert reversed_order.monotone_bits == 1.0
    assert reversed_order.relative_loss == 0.875


def test_zero_evidence_has_no_artificial_order_loss():
    comparison = compare_monotone_evidence(np.zeros((2, 3)))

    assert comparison.order_free_bits == 0.0
    assert comparison.monotone_bits == 0.0
    assert comparison.relative_loss == 0.0
    assert comparison.order_free_pairs == ()
    assert comparison.monotone_pairs == ()


def test_exact_matchers_agree_with_small_reference_problems():
    random = np.random.default_rng(20260826)
    for rows in range(1, 5):
        for columns in range(1, 5):
            for _case in range(4):
                weights = random.integers(-2, 6, size=(rows, columns)).astype(float)
                order_free, order_free_pairs = maximum_order_free_evidence(weights)
                monotone, monotone_pairs = maximum_monotone_evidence(weights)

                assert np.isclose(order_free, _reference_order_free(weights))
                assert np.isclose(monotone, _reference_monotone(weights))
                assert len({source for source, _, _ in order_free_pairs}) == len(
                    order_free_pairs
                )
                assert len({target for _, target, _ in order_free_pairs}) == len(
                    order_free_pairs
                )
                assert all(
                    left[0] < right[0] and left[1] < right[1]
                    for left, right in zip(monotone_pairs, monotone_pairs[1:])
                )
    compare_monotone_evidence,
    maximum_monotone_evidence,
    maximum_order_free_evidence,
