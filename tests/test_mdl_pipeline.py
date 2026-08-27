import numpy as np
import pytest

from dualign.algorithms.mdl import (
    AlignmentCalibration,
    align_mdl_pipeline,
    assess_alignment_applicability,
)
from dualign.algorithms.mdl.pipeline import (
    _reviewable_uncertain_regions,
    _uncertain_regions,
)
from dualign.core.aligner import _gate_payload


def _calibration():
    return AlignmentCalibration(
        existence_null=np.array([0.8, 0.8, 0.8]),
        acceptable_monotone_losses=np.array([0.0, 0.01, 0.02]),
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

    assert not result.gate.accepted
    assert result.gate.reason == "no_correspondence"
    assert result.all_ops == []
    assert result.centered is None


def test_correspondence_rejection_skips_rank_and_order_work(monkeypatch):
    def unexpected_rank(_scores):
        raise AssertionError("不存在对应关系时不应计算秩证据")

    monkeypatch.setattr(
        "dualign.algorithms.mdl.pipeline.mutual_rank_code_evidence",
        unexpected_rank,
    )

    gate = assess_alignment_applicability(
        np.full((3, 3), 0.1),
        _calibration(),
    )

    assert not gate.accepted
    assert gate.reason == "no_correspondence"
    assert gate.order is None
    assert gate.order_compatibility_p is None
    assert "order_compatibility_p" not in _gate_payload(gate)


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


def test_pipeline_gives_repeated_identical_text_pairs_identical_scores():
    vectors_a = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float64)
    vectors_b = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float64)

    result = align_mdl_pipeline(
        ["separator", "content", "separator"],
        ["separator", "content", "separator"],
        vectors_a,
        vectors_b,
        lambda texts: np.ones((len(texts), 2)),
        _calibration(),
    )

    assert result.gate.accepted
    assert result.gate.order is not None
    assert result.gate.order.relative_loss == 0.0


def test_single_line_parallel_document_is_not_rejected_for_lack_of_permutation_power():
    scores = np.array([[1.0]])

    gate = assess_alignment_applicability(
        scores,
        _calibration(),
    )

    assert gate.accepted
    assert gate.order is not None
    assert gate.order.relative_loss == 0.0


def test_large_order_loss_rejects_without_a_third_gate_state():
    gate = assess_alignment_applicability(
        np.fliplr(np.eye(4)),
        _calibration(),
    )

    assert not gate.accepted
    assert gate.reason == "order_incompatible"
    assert gate.order is not None
    assert gate.order.relative_loss == pytest.approx(0.75)


def test_gate_payload_serializes_monotone_evidence_loss():
    scores = np.eye(3)
    gate = assess_alignment_applicability(
        scores,
        _calibration(),
    )

    payload = _gate_payload(gate)

    assert gate.order is not None
    assert payload["monotone_evidence_loss"] == gate.order.relative_loss == 0.0
    assert payload["monotone_pairs"] == len(gate.order.monotone_pairs) == 3


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
