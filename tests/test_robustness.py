import numpy as np

from dualign.algorithms.mdl.robustness import maximum_monotone_evidence


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


def test_monotone_matcher_agrees_with_small_reference_problems():
    random = np.random.default_rng(20260826)
    for rows in range(1, 5):
        for columns in range(1, 5):
            for _case in range(4):
                weights = random.integers(-2, 6, size=(rows, columns)).astype(float)
                value, pairs = maximum_monotone_evidence(weights)

                assert np.isclose(value, _reference_monotone(weights))
                assert all(
                    left[0] < right[0] and left[1] < right[1]
                    for left, right in zip(pairs, pairs[1:])
                )
