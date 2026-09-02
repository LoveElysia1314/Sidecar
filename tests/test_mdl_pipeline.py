import numpy as np

import dualign.core.aligner as aligner_module
from dualign.algorithms.mdl import align_mdl_pipeline
from dualign.algorithms.mdl.pipeline import (
    _hard_boundary_sum_gain,
    _resolve_hard_boundary_witnesses,
    _reviewable_uncertain_regions,
    _uncertain_regions,
)


def test_pipeline_does_not_semantically_reject_low_correspondence():
    vectors_a = np.eye(3)
    vectors_b = np.full((3, 3), 1.0)

    result = align_mdl_pipeline(
        ["a", "b", "c"],
        ["x", "y", "z"],
        vectors_a,
        vectors_b,
        lambda texts: np.ones((len(texts), 3)),
    )

    assert result.status == "aligned"
    assert result.centered is not None


def test_pipeline_stops_atomic_alignment_after_fixed_timeout(monkeypatch):
    monkeypatch.setattr(
        "dualign.algorithms.mdl.runtime.ATOMIC_ALIGNMENT_TIMEOUT_SECONDS",
        0.0,
    )

    result = align_mdl_pipeline(
        ["a", "b", "c"],
        ["x", "y", "z"],
        np.eye(3),
        np.full((3, 3), 1.0),
        lambda texts: np.ones((len(texts), 3)),
    )

    assert result.status == "rejected"
    assert result.reason == "alignment_timeout"
    assert result.centered is None
    assert result.stats["alignment_time_limit_seconds"] == 0.0
    assert result.stats["timeout_phase"] == "local_candidates"


def test_public_aligner_rejects_oversized_matrix_before_solver(monkeypatch):
    monkeypatch.setattr(aligner_module, "MAXIMUM_SIMILARITY_MATRIX_CELLS", 3)
    encode_called = False

    def encode(_texts):
        nonlocal encode_called
        encode_called = True
        return np.eye(2)

    result = aligner_module.align(
        ["a", "b"],
        ["x", "y"],
        np.eye(2),
        np.eye(2),
        encode_fn=encode,
    )

    assert result.status == "rejected"
    assert result.reason == "input_too_large"
    assert result.stats["matrix_cells"] == 4
    assert result.stats["maximum_matrix_cells"] == 3
    assert not encode_called


def test_pipeline_uses_rank_scaffold_and_returns_complete_alignment():
    vectors = np.eye(3)

    result = align_mdl_pipeline(
        ["a", "b", "c"],
        ["a", "b", "c"],
        vectors,
        vectors,
        lambda texts: np.ones((len(texts), 3)),
    )

    assert result.status == "aligned"
    assert len(result.scaffold) == 3
    assert [(source, target) for source, target, _score in result.all_ops] == [
        ((0,), (0,)),
        ((1,), (1,)),
        ((2,), (2,)),
    ]


def test_pipeline_gives_repeated_identical_text_pairs_identical_scores():
    vectors_a = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float64)
    vectors_b = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float64)

    result = align_mdl_pipeline(
        ["separator", "content", "separator"],
        ["separator", "content", "separator"],
        vectors_a,
        vectors_b,
        lambda texts: np.ones((len(texts), 2)),
    )

    assert result.status == "aligned"
    assert result.stats["local_candidate_seconds"] >= 0.0
    assert result.stats["global_solver_seconds"] >= 0.0
    assert result.stats["atomic_alignment_seconds"] >= 0.0


def test_composition_disagreement_is_returned_as_one_review_region():
    atomic = [((0,), (0,), 1.0), ((1,), (1,), 1.0)]
    compound = [((0, 1), (0,), 1.0), ((), (1,), 0.0)]

    assert _uncertain_regions(atomic, compound) == (((0, 0), (2, 2)),)


def test_every_dld_posterior_disagreement_is_reviewable():
    stable = [
        ((0,), (0,), 1.0),
        ((1,), (), 0.0),
        ((2,), (1,), 1.0),
    ]
    posterior = [((0, 1), (0,), 1.0), ((2,), (1,), 1.0)]

    reviewable = _reviewable_uncertain_regions(stable, posterior)

    assert reviewable == (((0, 0), (2, 1)),)


def test_dld_only_change_remains_reviewable():
    atomic_and_posterior = [
        ((0, 1), (0,), 1.0),
        ((2,), (1,), 1.0),
    ]
    dld = [
        ((0,), (0,), 1.0),
        ((1,), (), 0.0),
        ((2,), (1,), 1.0),
    ]

    reviewable = _reviewable_uncertain_regions(dld, atomic_and_posterior)

    assert reviewable == (((0, 0), (2, 1)),)


def test_atomic_path_cannot_create_review_when_composition_models_agree():
    composition = [((0,), (0,), 1.0), ((1,), (), 0.0)]

    assert _reviewable_uncertain_regions(composition, composition) == ()


def test_positive_sum_hard_boundary_witness_promotes_posterior_merge():
    lines_a = ["first", "second"]
    lines_b = ["First. Second."]
    source_vectors = np.eye(2)
    target_vectors = np.array([[0.8, 0.6]])
    provisional = [((0,), (), 0.0), ((1,), (0,), 0.6)]
    posterior = [((0, 1), (0,), 0.7)]
    regions = (((0, 0), (2, 1)),)

    def encode(texts):
        vectors = {"First.": (1.0, 0.0), "Second.": (0.1, 0.995)}
        return np.array([vectors[text] for text in texts])

    resolved, remaining = _resolve_hard_boundary_witnesses(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        provisional,
        posterior,
        regions,
        encode,
    )

    assert resolved == posterior
    assert remaining == ()


def test_sum_witness_allows_one_small_negative_delta():
    lines_a = ["first", "second"]
    lines_b = ["First. Second."]
    source_vectors = np.eye(2)
    target_vectors = np.array([[0.7, 0.714]])
    provisional = [((0,), (), 0.0), ((1,), (0,), 0.7)]
    posterior = [((0, 1), (0,), 0.8)]

    def encode(texts):
        vectors = {"First.": (1.0, 0.0), "Second.": (0.2, 0.98)}
        return np.array([vectors[text] for text in texts])

    gain = _hard_boundary_sum_gain(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        provisional,
        posterior,
        encode,
    )

    assert gain is not None and gain > 0.0


def test_hard_boundary_witness_failure_keeps_review_region():
    lines_a = ["first", "second"]
    lines_b = ["First. Second."]
    source_vectors = np.eye(2)
    target_vectors = np.array([[0.8, 0.6]])
    provisional = [((0,), (), 0.0), ((1,), (0,), 0.6)]
    posterior = [((0, 1), (0,), 0.7)]
    regions = (((0, 0), (2, 1)),)

    def encode(texts):
        return np.array([(0.0, 1.0) for _text in texts])

    resolved, remaining = _resolve_hard_boundary_witnesses(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        provisional,
        posterior,
        regions,
        encode,
    )

    assert resolved == provisional
    assert remaining == regions


def test_hard_boundary_witness_is_not_applied_in_reverse_direction():
    lines_a = ["first", "second"]
    lines_b = ["First. Second."]
    source_vectors = np.eye(2)
    target_vectors = np.array([[0.8, 0.6]])
    provisional_merge = [((0, 1), (0,), 0.7)]
    posterior_gap = [((0,), (), 0.0), ((1,), (0,), 0.6)]

    gain = _hard_boundary_sum_gain(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        provisional_merge,
        posterior_gap,
        lambda texts: np.eye(len(texts), 2),
    )

    assert gain is None


def test_hard_boundary_witness_supports_mirrored_one_to_two_case():
    lines_a = ["First. Second."]
    lines_b = ["first", "second"]
    source_vectors = np.array([[0.8, 0.6]])
    target_vectors = np.eye(2)
    provisional = [((), (0,), 0.0), ((0,), (1,), 0.6)]
    posterior = [((0,), (0, 1), 0.7)]

    def encode(texts):
        vectors = {"First.": (1.0, 0.0), "Second.": (0.1, 0.995)}
        return np.array([vectors[text] for text in texts])

    gain = _hard_boundary_sum_gain(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        provisional,
        posterior,
        encode,
    )

    assert gain is not None and gain > 0.0


def test_hard_boundary_witness_requires_a_real_internal_boundary():
    gain = _hard_boundary_sum_gain(
        ["first", "second"],
        ["no boundary"],
        np.eye(2),
        np.array([[0.8, 0.6]]),
        [((0,), (), 0.0), ((1,), (0,), 0.6)],
        [((0, 1), (0,), 0.7)],
        lambda texts: np.ones((len(texts), 2)),
    )

    assert gain is None
