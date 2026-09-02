from functools import lru_cache

import numpy as np

from dualign.algorithms.mdl.composition_mdl import CandidateEdge
from dualign.algorithms.mdl.local_recursive_mdl import (
    _all_gapless_edges,
    _gapless_structure_counts,
    align_gapless_evidence_mdl,
    align_local_recursive_mdl,
    select_path_conditioned_composition,
)


def _brute_gapless_scripts(n, m):
    """Independent grammar enumerator used to audit candidate pruning."""

    @lru_cache(maxsize=None)
    def visit(source, target):
        if (source, target) == (n, m):
            return ((),)
        scripts = []
        for source_size in range(1, n - source + 1):
            for target_size in range(1, m - target + 1):
                if source_size > 1 and target_size > 1:
                    continue
                edge = (source, target, source + source_size, target + target_size)
                scripts.extend((edge, *suffix) for suffix in visit(edge[2], edge[3]))
        return tuple(scripts)

    return visit(0, 0)


def test_three_by_two_gapless_universe_contains_the_two_legal_paths():
    scores = np.eye(3, 2)
    edges = _all_gapless_edges(scores, scores)

    assert _gapless_structure_counts(3, 2, edges) == {1: 2}

    tied_edges = _all_gapless_edges(np.zeros((3, 2)), np.zeros((3, 2)))
    tied = align_gapless_evidence_mdl(3, 2, tied_edges, uniform_script_code=True)
    assert tied.solver_stats["optimal_path_ties"] == 2


def test_live_edge_pruning_is_exact_for_small_rectangles():
    for n in range(1, 6):
        for m in range(1, 6):
            scores = np.zeros((n, m))
            actual = _all_gapless_edges(scores, scores)
            actual_keys = {
                (edge.start[0], edge.start[1], edge.end[0], edge.end[1])
                for edge in actual
            }
            scripts = _brute_gapless_scripts(n, m)
            expected_keys = {edge for script in scripts for edge in script}
            counts = {}
            for script in scripts:
                complexity = sum(
                    end_source - start_source + end_target - start_target - 2
                    for start_source, start_target, end_source, end_target in script
                )
                counts[complexity] = counts.get(complexity, 0) + 1

            assert actual_keys == expected_keys
            assert _gapless_structure_counts(n, m, actual) == counts


def test_gapless_solver_can_merge_the_untouched_side_after_split():
    edges = [
        CandidateEdge((0, 0), (2, 1), (0, 1), (0,), 0.9, 2.0),
        CandidateEdge((2, 1), (3, 2), (2,), (1,), 0.9, 2.0),
        CandidateEdge((0, 0), (1, 1), (0,), (0,), 0.2, 0.1),
        CandidateEdge((1, 1), (3, 2), (1, 2), (1,), 0.2, 0.1),
    ]

    result = align_gapless_evidence_mdl(3, 2, edges)

    assert [(source, target) for source, target, _score in result.all_ops] == [
        ((0, 1), (0,)),
        ((2,), (1,)),
    ]
    assert result.complexity == 1
    assert all(source and target for source, target, _score in result.all_ops)

    # Each relation becomes one displayed row.  A 3:2 local problem may
    # therefore legitimately flatten to two source/target rows (2:2).
    source_lines = ["s0", "s1", "s2"]
    target_lines = ["t0", "t1"]
    flattened = [
        (
            " ".join(source_lines[index] for index in source),
            " ".join(target_lines[index] for index in target),
        )
        for source, target, _score in result.all_ops
    ]
    assert flattened == [("s0 s1", "t0"), ("s2", "t1")]


def test_recursive_pipeline_returns_complete_gapless_path():
    lines_a = ["a one", "a two", "b"]
    lines_b = ["A", "B"]
    mapping = {
        "a one": (1.0, 0.0),
        "a two": (0.9, 0.1),
        "b": (0.0, 1.0),
        "A": (1.0, 0.0),
        "B": (0.0, 1.0),
        "a one a two": (1.0, 0.0),
        "a two b": (0.3, 0.7),
    }

    def encode(texts):
        return np.asarray([mapping.get(text, (0.5, 0.5)) for text in texts])

    embeddings_a = encode(lines_a)
    embeddings_b = encode(lines_b)
    result = align_local_recursive_mdl(
        lines_a, lines_b, embeddings_a, embeddings_b, encode
    )

    assert len(result.all_ops) == 2
    assert {index for op in result.all_ops for index in op[0]} == {0, 1, 2}
    assert {index for op in result.all_ops for index in op[1]} == {0, 1}
    assert all(source and target for source, target, _score in result.all_ops)
    assert all(
        source and target for source, target, _score in result.raw_composition_ops
    )


def test_conditional_uniform_code_can_select_cross_direction_merges():
    lines_a = ["topic a", "topic b first", "topic b second"]
    lines_b = ["topic a first", "topic a second", "topic b"]
    mapping = {
        "topic a": (1.0, 0.0, 0.0),
        "topic a first": (0.9, 0.1, 0.0),
        "topic a second": (0.8, 0.2, 0.0),
        "topic a first topic a second": (1.0, 0.0, 0.0),
        "topic b first": (0.0, 1.0, 0.0),
        "topic b second": (0.0, 0.9, 0.1),
        "topic b": (0.0, 1.0, 0.0),
        "topic b first topic b second": (0.0, 1.0, 0.0),
    }

    def encode(texts):
        return np.asarray([mapping.get(text, (0.33, 0.33, 0.34)) for text in texts])

    result = align_local_recursive_mdl(
        lines_a, lines_b, encode(lines_a), encode(lines_b), encode
    )

    expected = [((0,), (0, 1)), ((1, 2), (2,))]
    assert result.status == "aligned"
    assert [(source, target) for source, target, _ in result.all_ops] == expected
    assert result.dld.complexity == 2


def test_path_conditioned_policy_uses_full_blocks_after_complexity_agreement():
    lines_a = ["source one", "source two", "source three"]
    lines_b = ["target one", "target two"]
    mapping = {
        "source one": (1.0, 0.0),
        "source two": (0.9, 0.1),
        "source three": (0.0, 1.0),
        "target one": (1.0, 0.0),
        "target two": (0.0, 1.0),
        "source one source two": (1.0, 0.0),
        "source two source three": (0.2, 0.8),
    }

    def encode(texts):
        return np.asarray([mapping.get(text, (0.5, 0.5)) for text in texts])

    evidence = align_local_recursive_mdl(
        lines_a, lines_b, encode(lines_a), encode(lines_b), encode
    )
    selected = select_path_conditioned_composition(evidence)

    assert selected.status == "aligned"
    assert selected.all_ops == evidence.raw_composition_ops
    assert selected.stats["selection_policy"] == "path_conditioned"


def test_path_conditioned_policy_rejects_an_exact_full_block_tie():
    lines_a = ["same", "same", "same"]
    lines_b = ["same", "same"]

    def encode(texts):
        return np.ones((len(texts), 2), dtype=np.float64)

    evidence = align_local_recursive_mdl(
        lines_a, lines_b, encode(lines_a), encode(lines_b), encode
    )
    selected = select_path_conditioned_composition(evidence)

    assert evidence.stats["raw_composition_optimal_paths"] == 2
    assert selected.status == "needs_review"
