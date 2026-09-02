import numpy as np

from dualign.algorithms.mdl import (
    align_centered_frontier_mdl,
    align_evidence_lattice_mdl,
)


def _relations(result):
    return [(source, target) for source, target, _score in result.all_ops]


def test_centered_frontier_cover_matches_full_mdl_on_wrong_scaffold():
    evidence = np.array(
        [
            [6.0, -3.0, -4.0],
            [-3.0, 5.0, -3.0],
            [-4.0, -3.0, 6.0],
        ]
    )
    scaffold = [((0,), (1,), 0.2), ((1,), (2,), 0.2)]

    centered = align_centered_frontier_mdl(evidence, evidence, scaffold)
    full = align_evidence_lattice_mdl(evidence)

    assert _relations(centered) == _relations(full)
    assert centered.window_stats["frontier_paths"] >= centered.window_stats["windows"]
    assert centered.semantic_candidates
    assert centered.composition_stats["algorithm"] == "sparse_cardinality_chain"
    assert all(
        source and target for source, target, _score in centered.semantic_candidates
    )
