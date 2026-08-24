import numpy as np

from dualign.algorithms.mdl.mdl_aligner import mutual_rank_code_evidence
from dualign.algorithms.mdl.robustness import (
    beta_binomial_upper_p,
    conformal_upper_p,
    fit_beta_binomial_order_model,
    monotone_order_evidence,
    mutual_monotone_chain,
    symmetric_nearest_score,
)


def test_symmetric_nearest_score_rewards_clear_correspondence():
    parallel = np.eye(4)
    flat = np.full((4, 4), 0.2)

    assert symmetric_nearest_score(parallel) > symmetric_nearest_score(flat)


def test_conformal_upper_p_has_finite_sample_correction():
    null = np.array([0.1, 0.2, 0.3])

    assert conformal_upper_p(0.9, null) == 0.25
    assert conformal_upper_p(0.15, null) == 0.75


def test_order_evidence_separates_identity_from_reverse_order_without_sampling():
    scores = np.eye(12)
    evidence = mutual_rank_code_evidence(scores)
    ordered = monotone_order_evidence(scores, evidence)
    reversed_order = monotone_order_evidence(scores[:, ::-1], evidence[:, ::-1])

    assert ordered.coverage == 1.0
    assert ordered.kendall_tau == 1.0
    assert reversed_order.kendall_tau == -1.0
    assert reversed_order.out_of_chain_pairs == 11


def test_mutual_monotone_chain_returns_weighted_lis_without_score_threshold():
    scores = np.array(
        [
            [9.0, 0.0, 0.0],
            [0.0, 1.0, 8.0],
            [0.0, 7.0, 1.0],
        ]
    )
    evidence = np.array(
        [
            [4.0, 0.0, 0.0],
            [0.0, 0.0, 3.0],
            [0.0, 2.0, 0.0],
        ]
    )

    chain = mutual_monotone_chain(scores, evidence)

    assert [(source, target) for source, target, _weight in chain] == [(0, 0), (1, 2)]


def test_beta_binomial_order_model_allows_baseline_heterogeneity():
    alpha, beta = fit_beta_binomial_order_model(
        np.array([[1, 100], [3, 120], [0, 80], [2, 90]])
    )

    ordinary = beta_binomial_upper_p(2, 100, alpha, beta)
    reordered = beta_binomial_upper_p(25, 100, alpha, beta)

    assert ordinary > 0.05
    assert reordered < 0.05
