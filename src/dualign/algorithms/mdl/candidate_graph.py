"""Parameter-free sparse proposal graph for general-span MDL alignment."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from dualign.algorithms.mdl.composition_mdl import (
    CandidateEdge,
    align_explicit_evidence_mdl,
)
from dualign.algorithms.mdl.mdl_aligner import (
    Operation,
    align_evidence_lattice_mdl,
)

Vertex = tuple[int, int]


@dataclass(frozen=True)
class CenteredFrontierMDLResult:
    all_ops: list[Operation]
    semantic_candidates: tuple[Operation, ...]
    window_stats: dict
    composition_stats: dict


def _offset_operations(
    operations: list[Operation], source_offset: int, target_offset: int
) -> list[Operation]:
    return [
        (
            tuple(source_offset + index for index in source),
            tuple(target_offset + index for index in target),
            score,
        )
        for source, target, score in operations
    ]


def _scaffold_points(scaffold: list[Operation], n: int, m: int) -> list[Vertex]:
    points = [
        (0, 0),
        *(
            (source[0] + 1, target[0] + 1)
            for source, target, _score in scaffold
            if len(source) == 1 and len(target) == 1
        ),
        (n, m),
    ]
    points = list(dict.fromkeys(points))
    if points != sorted(points):
        raise ValueError("脚手架必须严格单调")
    return points


def _centered_windows(
    scaffold: list[Operation], n: int, m: int
) -> list[tuple[Vertex, Vertex]]:
    points = _scaffold_points(scaffold, n, m)
    if len(points) <= 2:
        return [((0, 0), (n, m))]
    return [
        (points[index - 1], points[index + 1]) for index in range(1, len(points) - 1)
    ]


def _semantic_edge(
    start: Vertex,
    operation: Operation,
    evidence: np.ndarray,
) -> CandidateEdge | None:
    source, target, raw_score = operation
    if not source or not target:
        return None
    if len(source) > 1 and len(target) > 1:
        raise ValueError("稀疏 MDL 不支持 N:M 候选")
    end = (start[0] + len(source), start[1] + len(target))
    semantic = float(evidence[np.ix_(source, target)].sum())
    return CandidateEdge(start, end, source, target, raw_score, semantic)


def align_centered_frontier_mdl(
    evidence: np.ndarray,
    scores: np.ndarray,
    scaffold: list[Operation],
) -> CenteredFrontierMDLResult:
    """Compose local Pareto support edges with the exact global gap quotient.

    Each internal scaffold point lies inside one window bounded by its two
    neighbours, so no anchor is mandatory.  Scaffold 1:1 edges are also kept
    as proposals.  Gap edges need not be proposed: the global solver has
    proved that every gap-only route is the same hypothesis and removes that
    grid exactly.
    """

    bits = np.asarray(evidence, dtype=np.float64)
    matrix = np.asarray(scores, dtype=np.float64)
    if bits.ndim != 2 or matrix.shape != bits.shape:
        raise ValueError("证据和评分必须是形状一致的二维矩阵")
    n, m = bits.shape
    _scaffold_points(scaffold, n, m)

    candidates: dict[tuple[tuple[int, ...], tuple[int, ...]], CandidateEdge] = {}
    for operation in scaffold:
        source, target, _score = operation
        if len(source) != 1 or len(target) != 1:
            continue
        edge = _semantic_edge((source[0], target[0]), operation, bits)
        if edge is not None:
            candidates[(edge.source, edge.target)] = edge

    windows = _centered_windows(scaffold, n, m)
    cells = 0
    maximum_cells = 0
    maximum_shape = (0, 0)
    frontier_paths = 0
    started = time.perf_counter()
    for start, end in windows:
        source_start, target_start = start
        source_end, target_end = end
        local_evidence = bits[source_start:source_end, target_start:target_end]
        local_scores = matrix[source_start:source_end, target_start:target_end]
        shape = local_evidence.shape
        window_cells = shape[0] * shape[1]
        cells += window_cells
        if window_cells > maximum_cells:
            maximum_cells = window_cells
            maximum_shape = shape

        local = align_evidence_lattice_mdl(
            local_evidence,
            scores_11=local_scores,
            return_frontier_paths=True,
        )
        for complexity, path in local.frontier_paths:
            frontier_paths += 1
            cursor = start
            for operation in _offset_operations(path, source_start, target_start):
                edge = _semantic_edge(cursor, operation, bits)
                if edge is not None:
                    candidates[(edge.source, edge.target)] = edge
                cursor = (
                    cursor[0] + len(operation[0]),
                    cursor[1] + len(operation[1]),
                )
            if cursor != end:
                raise RuntimeError(f"中心窗口路径未完整覆盖: {cursor} != {end}")

    alignment = align_explicit_evidence_mdl(n, m, list(candidates.values()))
    composition_stats = {
        "candidate_edges": alignment.candidate_edges,
        "frontier_states": len(alignment.frontier),
        "selected_complexity": alignment.complexity,
        "selected_semantic_bits": round(alignment.semantic_bits, 6),
        "selected_structure_bits": round(alignment.structure_bits, 6),
        "selected_objective_bits": round(alignment.objective_bits, 6),
        "structure_universe": "full_grammar",
        **alignment.solver_stats,
    }
    semantic_candidates = tuple(
        (edge.source, edge.target, edge.raw_score) for edge in candidates.values()
    )
    return CenteredFrontierMDLResult(
        all_ops=alignment.all_ops,
        semantic_candidates=semantic_candidates,
        window_stats={
            "windows": len(windows),
            "matrix_cells": cells,
            "maximum_window_cells": maximum_cells,
            "maximum_window_shape": maximum_shape,
            "frontier_paths": frontier_paths,
            "seconds": round(time.perf_counter() - started, 6),
        },
        composition_stats=composition_stats,
    )
