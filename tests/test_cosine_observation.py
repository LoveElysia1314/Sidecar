import numpy as np
import pytest

from dualign.algorithms.mdl.cosine_observation import observed_cosine_matrix


def test_cosine_observations_are_binary16_values():
    source = np.array([[1.0, 0.0], [0.8, 0.6]], dtype=np.float64)
    target = np.array([[0.6, 0.8]], dtype=np.float64)

    scores = observed_cosine_matrix(["a", "b"], ["x"], source, target)

    assert scores.dtype == np.float16
    np.testing.assert_array_equal(
        scores,
        np.asarray(source @ target.T, dtype=np.float16),
    )


def test_duplicate_text_pairs_alias_one_computed_score_cell():
    # The second copies deliberately carry inconsistent vectors. Text identity
    # still chooses one representative per axis before any dot product runs.
    source = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)
    target = np.array([[0.8, 0.6], [0.6, 0.8]], dtype=np.float64)

    scores = observed_cosine_matrix(
        ["same source", "same source"],
        ["same target", "same target"],
        source,
        target,
    )

    assert scores.shape == (2, 2)
    assert np.unique(scores).tolist() == [np.float16(0.8)]


def test_exact_text_identity_does_not_ignore_punctuation():
    source = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)
    target = np.array([[1.0, 0.0]], dtype=np.float64)

    scores = observed_cosine_matrix(["same", "same。"], ["target"], source, target)

    assert scores[0, 0] != scores[1, 0]


def test_cosine_observations_clip_arithmetic_overshoot():
    scores = observed_cosine_matrix(
        ["a"],
        ["b"],
        np.array([[1.001, 0.0]]),
        np.array([[1.001, 0.0]]),
    )

    assert scores[0, 0] == np.float16(1.0)


def test_cosine_observation_validates_text_and_vector_shapes():
    with pytest.raises(ValueError, match="行数"):
        observed_cosine_matrix(["a"], ["b"], np.eye(2), np.eye(1, 2))

    with pytest.raises(ValueError, match="维度"):
        observed_cosine_matrix(
            ["a"],
            ["b"],
            np.ones((1, 2)),
            np.ones((1, 3)),
        )
