import numpy as np

from dualign.algorithms.mdl import (
    align_evidence_lattice_mdl,
    align_similarity_lattices_mdl,
    mutual_rank_code_evidence,
)
from dualign.algorithms.mdl.mdl_aligner import (
    _semantic_frontier,
    _structure_counts,
)


def _relations(result):
    return [(source, target) for source, target, _score in result.all_ops]


def test_rank_evidence_is_invariant_under_monotone_score_transform():
    scores = np.array([[0.9, 0.4, 0.2], [0.3, 0.8, 0.1]])

    original = mutual_rank_code_evidence(scores)
    transformed = mutual_rank_code_evidence(np.exp(scores * 3.0))

    np.testing.assert_allclose(original, transformed)


def test_mutual_rank_requires_both_directions_to_be_distinctive():
    scores = np.array([[0.9, 0.8], [0.85, 0.1]])
    evidence = mutual_rank_code_evidence(scores)

    assert evidence[0, 0] > evidence[0, 1]
    assert evidence[0, 0] > evidence[1, 0]


def test_vectorized_rank_evidence_preserves_conservative_tie_ranks():
    scores = np.array(
        [
            [0.5, 0.5, 0.2, 0.1],
            [0.3, 0.8, 0.3, 0.8],
            [0.5, 0.4, 0.3, 0.1],
        ]
    )

    def reference_ranks(matrix, axis):
        values = matrix if axis == 1 else matrix.T
        result = np.empty(values.shape, dtype=np.int32)
        for index, row in enumerate(values):
            ordered = np.sort(row)
            result[index] = len(row) - np.searchsorted(ordered, row, side="left")
        return result if axis == 1 else result.T

    row_ranks = reference_ranks(scores, 1)
    column_ranks = reference_ranks(scores, 0)
    row_harmonic = sum(1.0 / value for value in range(1, scores.shape[1] + 1))
    column_harmonic = sum(1.0 / value for value in range(1, scores.shape[0] + 1))
    expected = np.minimum(
        np.log2(scores.shape[1] / (row_harmonic * row_ranks)),
        np.log2(scores.shape[0] / (column_harmonic * column_ranks)),
    )

    np.testing.assert_array_equal(mutual_rank_code_evidence(scores), expected)


def test_integrated_frontier_backtrace_preserves_coverage_and_semantics():
    random = np.random.default_rng(20260825)
    for n in range(1, 5):
        for m in range(1, 5):
            for evidence in (
                random.normal(size=(n, m)),
                random.integers(-2, 3, size=(n, m)).astype(float),
            ):
                scores = random.normal(size=(n, m))
                frontier = _semantic_frontier(evidence)
                complexities = tuple(frontier)
                integrated = align_evidence_lattice_mdl(
                    evidence,
                    scores_11=scores,
                    return_frontier_paths=True,
                )
                integrated_paths = dict(integrated.frontier_paths)

                for complexity in complexities:
                    path = integrated_paths[complexity]
                    assert tuple(
                        index for source, _target, _score in path for index in source
                    ) == tuple(range(n))
                    assert tuple(
                        index for _source, target, _score in path for index in target
                    ) == tuple(range(m))
                    assert (
                        sum(
                            (
                                len(source) + len(target) - 2
                                if source and target
                                else len(source) + len(target)
                            )
                            for source, target, _score in path
                        )
                        == complexity
                    )
                    semantic = sum(
                        float(evidence[np.ix_(source, target)].sum())
                        for source, target, _score in path
                        if source and target
                    )
                    assert np.isclose(
                        semantic,
                        frontier[complexity],
                    )


def test_integrated_frontier_backtrace_keeps_existing_tie_break():
    evidence = np.array([[1.0, 0.0], [-10.0, -10.0]])

    result = align_evidence_lattice_mdl(
        evidence,
        scores_11=evidence,
        return_frontier_paths=True,
    )

    assert dict(result.frontier_paths)[2] == (
        ((0,), (0,), 1.0),
        ((), (1,), 0.0),
        ((1,), (), 0.0),
    )


def test_mdl_prefers_two_clear_pairs_over_merge_plus_gap():
    evidence_11 = np.array([[6.0, -1.0], [-2.0, 5.0]])

    result = align_evidence_lattice_mdl(evidence_11)

    assert _relations(result) == [((0,), (0,)), ((1,), (1,))]
    assert result.complexity == 0


def test_true_merge_can_pay_its_universal_structure_code():
    evidence_11 = np.array([[4.0], [4.0]])

    result = align_evidence_lattice_mdl(evidence_11)

    assert _relations(result) == [((0, 1), (0,))]


def test_arbitrary_many_to_one_span_is_available_without_span_matrix():
    evidence = np.array([[4.0], [4.0], [4.0]])
    scores = np.array([[0.9], [0.6], [0.3]])

    result = align_evidence_lattice_mdl(evidence, scores_11=scores)

    assert _relations(result) == [((0, 1, 2), (0,))]
    assert result.all_ops[0][2] == 0.6
    assert result.complexity == 2


def test_arbitrary_one_to_many_span_is_available_without_span_matrix():
    evidence = np.array([[4.0, 4.0, 4.0]])

    result = align_evidence_lattice_mdl(evidence)

    assert _relations(result) == [((0,), (0, 1, 2))]
    assert result.complexity == 2


def test_general_span_structure_counts_match_brute_force():
    def brute_force(n, m, i=0, j=0, complexity=0, result=None):
        result = {} if result is None else result
        if i == n and j == m:
            result[complexity] = result.get(complexity, 0) + 1
            return result
        if i < n:
            brute_force(n, m, i + 1, j, complexity + 1, result)
        if j < m:
            brute_force(n, m, i, j + 1, complexity + 1, result)
        if i < n and j < m:
            for span in range(1, n - i + 1):
                brute_force(n, m, i + span, j + 1, complexity + span - 1, result)
            for span in range(2, m - j + 1):
                brute_force(n, m, i + 1, j + span, complexity + span - 1, result)
        return result

    expected = brute_force(3, 3)

    assert _structure_counts(3, 3, max(expected)) == expected


def test_combinatorial_structure_counts_match_brute_force_for_small_rectangles():
    def brute_force(n, m, i=0, j=0, complexity=0, result=None):
        result = {} if result is None else result
        if i == n and j == m:
            result[complexity] = result.get(complexity, 0) + 1
            return result
        if i < n:
            brute_force(n, m, i + 1, j, complexity + 1, result)
        if j < m:
            brute_force(n, m, i, j + 1, complexity + 1, result)
        if i < n and j < m:
            for span in range(1, n - i + 1):
                brute_force(n, m, i + span, j + 1, complexity + span - 1, result)
            for span in range(2, m - j + 1):
                brute_force(n, m, i + 1, j + span, complexity + span - 1, result)
        return result

    for n in range(1, 5):
        for m in range(1, 5):
            expected = brute_force(n, m)
            assert _structure_counts(n, m, n + m) == expected


def test_prefix_optimal_semantic_frontier_matches_brute_force():
    evidence = np.array(
        [
            [2.0, -1.0, 0.5],
            [1.5, 3.0, -2.0],
            [-1.0, 2.0, 4.0],
        ]
    )
    exact = {}

    def visit(i, j, complexity, semantic):
        if i == 3 and j == 3:
            exact[complexity] = max(exact.get(complexity, float("-inf")), semantic)
            return
        if i < 3:
            visit(i + 1, j, complexity + 1, semantic)
        if j < 3:
            visit(i, j + 1, complexity + 1, semantic)
        if i < 3 and j < 3:
            accumulated = 0.0
            for span in range(1, 4 - i):
                accumulated += evidence[i + span - 1, j]
                visit(i + span, j + 1, complexity + span - 1, semantic + accumulated)
            accumulated = evidence[i, j]
            for span in range(2, 4 - j):
                accumulated += evidence[i, j + span - 1]
                visit(i + 1, j + span, complexity + span - 1, semantic + accumulated)

    visit(0, 0, 0, 0.0)
    strongest = float("-inf")
    expected = {}
    for complexity, semantic in sorted(exact.items()):
        if semantic > strongest:
            expected[complexity] = semantic
            strongest = semantic

    assert _semantic_frontier(evidence) == expected


def test_unavoidable_gap_position_is_chosen_by_global_semantics():
    evidence_11 = np.array([[5.0, -2.0], [-3.0, -3.0], [-2.0, 5.0]])

    result = align_evidence_lattice_mdl(evidence_11)

    assert _relations(result) == [
        ((0,), (0,)),
        ((1,), ()),
        ((2,), (1,)),
    ]


def test_raw_similarity_entry_point_has_no_numeric_policy_configuration():
    scores = np.array([[0.9, 0.1], [0.2, 0.8]])

    result = align_similarity_lattices_mdl(scores)

    assert _relations(result) == [((0,), (0,)), ((1,), (1,))]
    assert result.objective_bits == max(item[3] for item in result.frontier)


def test_atomic_coverage_does_not_absorb_an_unrelated_note_into_a_match():
    scores = np.array([[0.10, 0.15], [0.90, 0.20], [0.20, 0.90]])

    result = align_similarity_lattices_mdl(scores)

    assert _relations(result) == [
        ((0,), ()),
        ((1,), (0,)),
        ((2,), (1,)),
    ]


def test_atomic_coverage_can_select_a_true_two_to_one_relation():
    scores = np.full((10, 9), 0.10)
    scores[0, 0] = 0.90
    scores[1, 0] = 0.85
    for source in range(2, 10):
        scores[source, source - 1] = 0.90

    result = align_similarity_lattices_mdl(scores)

    assert _relations(result)[0] == ((0, 1), (0,))
    assert all(
        relation == ((source,), (source - 1,))
        for source, relation in enumerate(_relations(result)[1:], start=2)
    )


def test_dominated_complexity_states_are_absent_from_the_final_frontier():
    evidence = np.array([[5.0, -5.0], [-5.0, 5.0]])

    result = align_evidence_lattice_mdl(evidence)

    assert result.frontier == ((0, 10.0, 0.0, 10.0),)
