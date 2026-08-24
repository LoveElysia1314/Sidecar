import numpy as np

from dualign.algorithms.mdl import (
    AlignmentCalibration,
    align_mdl_pipeline,
    assess_alignment_applicability,
    mutual_rank_code_evidence,
)
from dualign.algorithms.mdl.pipeline import (
    _reviewable_uncertain_regions,
    _uncertain_regions,
)
from dualign.core.aligner import _gate_payload


def _calibration():
    return AlignmentCalibration(
        existence_null=np.array([0.8, 0.8, 0.8]),
        parallel_order_counts=np.array([[1, 100], [2, 100], [1, 80]]),
        alpha=0.30,
    )


def test_pipeline_abstains_before_alignment_when_correspondence_is_absent():
    vectors_a = np.eye(3)
    vectors_b = np.full((3, 3), 1.0)

    result = align_mdl_pipeline(
        ["a", "b", "c"],
        ["x", "y", "z"],
        vectors_a,
        vectors_b,
        lambda texts: np.ones((len(texts), 3)),
        _calibration(),
    )

    assert result.gate.status == "rejected_no_correspondence"
    assert result.all_ops == []
    assert result.centered is None


def test_pipeline_uses_rank_scaffold_and_returns_complete_alignment():
    vectors = np.eye(3)

    result = align_mdl_pipeline(
        ["a", "b", "c"],
        ["a", "b", "c"],
        vectors,
        vectors,
        lambda texts: np.ones((len(texts), 3)),
        _calibration(),
    )

    assert result.gate.accepted
    assert result.status == "aligned"
    assert len(result.scaffold) == 3
    assert [(source, target) for source, target, _score in result.all_ops] == [
        ((0,), (0,)),
        ((1,), (1,)),
        ((2,), (2,)),
    ]


def test_single_line_parallel_document_is_not_rejected_for_lack_of_permutation_power():
    scores = np.array([[1.0]])

    gate = assess_alignment_applicability(
        scores,
        mutual_rank_code_evidence(scores),
        _calibration(),
    )

    assert gate.accepted
    assert gate.order.mutual_pairs == 1
    assert gate.order.out_of_chain_pairs == 0


def test_gate_payload_serializes_the_order_chain_length():
    scores = np.eye(3)
    gate = assess_alignment_applicability(
        scores,
        mutual_rank_code_evidence(scores),
        _calibration(),
    )

    payload = _gate_payload(gate)

    assert payload["longest_chain_pairs"] == gate.order.chain_length == 3


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
