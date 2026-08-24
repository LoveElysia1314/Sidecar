import numpy as np

from dualign.algorithms.mdl import (
    CandidateEdge,
    align_counterfactual_composition_mdl,
    align_evidence_lattice_mdl,
    align_explicit_evidence_mdl,
    conditional_rank_evidence,
    counterfactual_diagnostics,
    decision_relevant_candidates,
)


def _relations(result):
    return [(source, target) for source, target, _score in result.all_ops]


def _additive_edges(evidence):
    n, m = evidence.shape
    edges = []
    for i in range(n):
        for j in range(m):
            for end in range(i + 1, n + 1):
                source = tuple(range(i, end))
                edges.append(
                    CandidateEdge(
                        (i, j),
                        (end, j + 1),
                        source,
                        (j,),
                        0.0,
                        float(evidence[i:end, j].sum()),
                    )
                )
            for end in range(j + 2, m + 1):
                target = tuple(range(j, end))
                edges.append(
                    CandidateEdge(
                        (i, j),
                        (i + 1, end),
                        (i,),
                        target,
                        0.0,
                        float(evidence[i, j:end].sum()),
                    )
                )
    return edges


def test_counterfactual_diagnostics_separate_order_and_gain():
    full = np.array([0.8, 0.5, 0.4])
    ablated = np.array([[0.7, 0.6, 0.3], [0.75, 0.4, 0.45]])

    wins, gains = counterfactual_diagnostics(full, ablated)

    np.testing.assert_array_equal(wins, [2.0, 1.0, 1.0])
    np.testing.assert_allclose(gains, [0.05, -0.1, -0.05])


def test_conditional_rank_correction_is_a_normalized_change_of_measure():
    atomic = np.array([3.0, 2.0, 1.0])
    result = conditional_rank_evidence(atomic, np.array([0.1, 0.9, -0.2]))
    probability = np.exp2(atomic - np.max(atomic))
    probability /= probability.sum()

    assert np.isclose(np.sum(probability * np.exp2(result.correction_bits)), 1.0)
    assert result.correction_bits[1] > result.correction_bits[2]


def test_explicit_edge_solver_matches_general_span_atomic_solver():
    evidence = np.array(
        [
            [4.0, -2.0],
            [3.0, -1.0],
            [-2.0, 5.0],
        ]
    )

    implicit = align_evidence_lattice_mdl(evidence)
    explicit = align_explicit_evidence_mdl(3, 2, _additive_edges(evidence))

    assert _relations(explicit) == _relations(implicit)
    assert explicit.complexity == implicit.complexity
    assert np.isclose(explicit.objective_bits, implicit.objective_bits)


def test_sparse_edge_solver_matches_full_lattice_on_random_small_matrices():
    rng = np.random.default_rng(20260823)
    for n in range(1, 5):
        for m in range(1, 5):
            for _trial in range(4):
                evidence = rng.normal(size=(n, m))
                implicit = align_evidence_lattice_mdl(evidence)
                explicit = align_explicit_evidence_mdl(
                    n, m, _additive_edges(evidence)
                )

                assert explicit.complexity == implicit.complexity
                assert np.isclose(explicit.semantic_bits, implicit.semantic_bits)
                assert np.isclose(explicit.objective_bits, implicit.objective_bits)


def test_decision_relevant_candidates_add_gap_boundary_counterfactuals():
    proposals = [
        ((0,), (0,), 0.9),
        ((1,), (1,), 0.8),
        ((2, 3), (2,), 0.7),
        ((4, 5), (3,), 0.6),
    ]
    atomic_path = [
        ((0,), (0,), 0.9),
        ((1,), (), 0.0),
        ((2,), (1,), 0.8),
        ((3, 4), (2,), 0.7),
        ((), (3,), 0.0),
        ((5,), (4,), 0.6),
    ]

    result = decision_relevant_candidates(proposals, atomic_path)
    relations = {(source, target) for source, target, _score in result}

    assert ((0, 1), (0,)) in relations
    assert ((1, 2), (1,)) in relations
    assert ((3, 4), (2,)) in relations
    assert ((3, 4), (2, 3)) not in relations
    assert ((5,), (3, 4)) in relations
    assert ((2, 3), (2,)) not in relations


def test_sparse_counterfactual_composition_encodes_only_compound_candidates():
    lines_a = ["first", "second"]
    lines_b = ["combined"]
    embeddings_a = np.array([[1.0, 0.0], [0.0, 1.0]])
    embeddings_b = np.array([[1.0, 1.0]])
    scores = np.array([[0.7], [0.7]])
    evidence = np.array([[2.0], [2.0]])
    candidates = [((0, 1), (0,), 0.7)]

    def encode(texts):
        mapping = {
            "first second": [1.0, 1.0],
            "first": [1.0, 0.0],
            "second": [0.0, 1.0],
        }
        return np.array([mapping[text] for text in texts], dtype=np.float64)

    result = align_counterfactual_composition_mdl(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        scores,
        evidence,
        candidates,
        encode,
    )

    assert result.encoded_texts == 3
    assert result.composition_candidates == 1
    assert result.diagnostics[0]["relation"] == "2:1"
    assert _relations(result.alignment) == [((0, 1), (0,))]
