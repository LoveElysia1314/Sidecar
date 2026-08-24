"""Gapless local MDL realignment after an explicit hard split.

The parent document has already passed applicability gates.  This decoder
therefore conditions on local correspondence and searches only monotone,
complete-coverage paths containing 1:1, N:1 and 1:N semantic relations.  Gaps
and N:M are absent from both the candidate graph and the enumerative structure
code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from dualign.core import _smart_join_lines

from dualign.algorithms.mdl.composition_mdl import (
    CandidateEdge,
    ExplicitMDLResult,
    align_counterfactual_composition_mdl,
)
from dualign.algorithms.mdl.mdl_aligner import (
    Operation,
    _elias_delta_length,
    mutual_rank_code_evidence,
    normalize_embeddings,
)


@dataclass(frozen=True)
class LocalRecursiveMDLResult:
    status: str
    all_ops: list[Operation]
    alternative_ops: list[Operation]
    atomic_ops: list[Operation]
    raw_composition_ops: list[Operation]
    dld: ExplicitMDLResult
    posterior: ExplicitMDLResult
    stats: dict


def select_path_conditioned_composition(
    result: LocalRecursiveMDLResult,
) -> LocalRecursiveMDLResult:
    """Use counterfactual models for complexity and full blocks for boundaries.

    Complete paths at one complexity contain the same number of relations, so
    their joined-block cosine sums are directly comparable.  DLD and posterior
    retain the job for which their bit units are needed: deciding how much
    merge structure the local script requires.  No evidence units are added or
    multiplied together.
    """

    if (
        result.dld.complexity != result.posterior.complexity
        or result.stats.get("raw_composition_optimal_paths", 1) != 1
    ):
        return LocalRecursiveMDLResult(
            status="needs_review",
            all_ops=result.all_ops,
            alternative_ops=result.alternative_ops,
            atomic_ops=result.atomic_ops,
            raw_composition_ops=result.raw_composition_ops,
            dld=result.dld,
            posterior=result.posterior,
            stats={**result.stats, "selection_policy": "path_conditioned"},
        )
    return LocalRecursiveMDLResult(
        status="aligned",
        all_ops=result.raw_composition_ops,
        alternative_ops=result.alternative_ops,
        atomic_ops=result.atomic_ops,
        raw_composition_ops=result.raw_composition_ops,
        dld=result.dld,
        posterior=result.posterior,
        stats={**result.stats, "selection_policy": "path_conditioned"},
    )


def _all_gapless_edges(scores: np.ndarray, evidence: np.ndarray) -> list[CandidateEdge]:
    """Enumerate every structurally live N:1/1:N edge in the local rectangle."""

    matrix = np.asarray(scores, dtype=np.float64)
    bits = np.asarray(evidence, dtype=np.float64)
    if matrix.ndim != 2 or bits.shape != matrix.shape:
        raise ValueError("局部评分与证据矩阵形状不一致")
    n, m = matrix.shape
    edges: list[CandidateEdge] = []

    def live(start, end) -> bool:
        prefix = start == (0, 0) or (start[0] > 0 and start[1] > 0)
        source_left, target_left = n - end[0], m - end[1]
        suffix = end == (n, m) or (source_left > 0 and target_left > 0)
        return prefix and suffix

    for source_start in range(n):
        for target_start in range(m):
            start = (source_start, target_start)
            for source_end in range(source_start + 1, n + 1):
                source = tuple(range(source_start, source_end))
                target = (target_start,)
                end = (source_end, target_start + 1)
                if live(start, end):
                    edges.append(
                        CandidateEdge(
                            start,
                            end,
                            source,
                            target,
                            float(matrix[source_start:source_end, target_start].mean()),
                            float(bits[source_start:source_end, target_start].sum()),
                        )
                    )
            for target_end in range(target_start + 2, m + 1):
                source = (source_start,)
                target = tuple(range(target_start, target_end))
                end = (source_start + 1, target_end)
                if live(start, end):
                    edges.append(
                        CandidateEdge(
                            start,
                            end,
                            source,
                            target,
                            float(matrix[source_start, target_start:target_end].mean()),
                            float(bits[source_start, target_start:target_end].sum()),
                        )
                    )
    return edges


def _gapless_structure_counts(
    n: int, m: int, edges: list[CandidateEdge]
) -> dict[int, int]:
    states: dict[tuple[int, int], dict[int, int]] = {(0, 0): {0: 1}}
    by_start: dict[tuple[int, int], list[CandidateEdge]] = {}
    for edge in edges:
        by_start.setdefault(edge.start, []).append(edge)
    for coordinate_sum in range(n + m + 1):
        for source in range(max(0, coordinate_sum - m), min(n, coordinate_sum) + 1):
            target = coordinate_sum - source
            current = states.get((source, target))
            if not current:
                continue
            for edge in by_start.get((source, target), ()):
                destination = states.setdefault(edge.end, {})
                for complexity, count in current.items():
                    end_complexity = complexity + edge.complexity
                    destination[end_complexity] = (
                        destination.get(end_complexity, 0) + count
                    )
    return states.get((n, m), {})


def align_gapless_evidence_mdl(
    n: int,
    m: int,
    semantic_edges: list[CandidateEdge],
    *,
    target_complexity: int | None = None,
    uniform_script_code: bool = False,
) -> ExplicitMDLResult:
    """Exact MDL over the gapless local grammar and its own structure universe."""

    if not n or not m:
        raise ValueError("无 gap 局部对齐要求两侧均非空")
    edges = list(semantic_edges)
    by_start: dict[tuple[int, int], list[tuple[int, CandidateEdge]]] = {}
    for edge_id, edge in enumerate(edges):
        source_size = edge.end[0] - edge.start[0]
        target_size = edge.end[1] - edge.start[1]
        if (
            source_size < 1
            or target_size < 1
            or (source_size > 1 and target_size > 1)
            or edge.complexity != source_size + target_size - 2
        ):
            raise ValueError("局部候选不属于无 gap N:1/1:N 语法")
        by_start.setdefault(edge.start, []).append((edge_id, edge))

    states: dict[tuple[int, int], dict[int, float]] = {(0, 0): {0: 0.0}}
    path_counts: dict[tuple[int, int], dict[int, int]] = {(0, 0): {0: 1}}
    backtrace: dict[tuple[int, int, int], tuple[int, int, int, int]] = {}
    for coordinate_sum in range(n + m + 1):
        for source in range(max(0, coordinate_sum - m), min(n, coordinate_sum) + 1):
            target = coordinate_sum - source
            current = states.get((source, target))
            if not current:
                continue
            for edge_id, edge in by_start.get((source, target), ()):
                destination = states.setdefault(edge.end, {})
                destination_counts = path_counts.setdefault(edge.end, {})
                for complexity, semantic in current.items():
                    end_complexity = complexity + edge.complexity
                    end_semantic = semantic + edge.semantic_bits
                    old = destination.get(end_complexity)
                    if old is None or end_semantic > old:
                        destination[end_complexity] = end_semantic
                        destination_counts[end_complexity] = path_counts[
                            (source, target)
                        ][complexity]
                        backtrace[(edge.end[0], edge.end[1], end_complexity)] = (
                            source,
                            target,
                            complexity,
                            edge_id,
                        )
                    elif end_semantic == old:
                        destination_counts[end_complexity] += path_counts[
                            (source, target)
                        ][complexity]

    terminal = dict(states.get((n, m), {}))
    if not terminal:
        raise RuntimeError("局部候选图没有完整无 gap 路径")
    if target_complexity is not None:
        if target_complexity not in terminal:
            raise ValueError("指定复杂度在局部无 gap 语法中不可达")
        terminal = {target_complexity: terminal[target_complexity]}
    strongest = float("-inf")
    for complexity in sorted(tuple(terminal)):
        if terminal[complexity] <= strongest:
            del terminal[complexity]
        else:
            strongest = terminal[complexity]
    counts = _gapless_structure_counts(n, m, edges)
    minimum = min(terminal)
    frontier = []
    if uniform_script_code:
        structure = math.log2(sum(counts.values()))
        frontier = [
            (complexity, semantic, structure, semantic - structure)
            for complexity, semantic in sorted(terminal.items())
        ]
    else:
        monotone_structure = 0.0
        for complexity, semantic in sorted(terminal.items()):
            raw_structure = math.log2(counts[complexity]) + (
                _elias_delta_length(complexity - minimum + 1) - 1
            )
            monotone_structure = max(monotone_structure, raw_structure)
            frontier.append(
                (
                    complexity,
                    semantic,
                    monotone_structure,
                    semantic - monotone_structure,
                )
            )
    chosen = max(frontier, key=lambda item: (item[3], -item[0]))

    operations = []
    source, target, complexity = n, m, chosen[0]
    while source or target:
        previous_source, previous_target, previous_complexity, edge_id = backtrace[
            (source, target, complexity)
        ]
        edge = edges[edge_id]
        operations.append((edge.source, edge.target, edge.raw_score))
        source, target, complexity = (
            previous_source,
            previous_target,
            previous_complexity,
        )
    operations.reverse()
    return ExplicitMDLResult(
        all_ops=operations,
        complexity=chosen[0],
        semantic_bits=chosen[1],
        structure_bits=chosen[2],
        objective_bits=chosen[3],
        candidate_edges=len(edges),
        frontier=tuple(frontier),
        solver_stats={
            "algorithm": "dense_local_gapless_mdl",
            "semantic_edges": len(edges),
            "lattice_vertices": len(states),
            "pareto_states": sum(len(item) for item in states.values()),
            "structure_universe": "gapless_1to1_n1_1n",
            "structure_code": (
                "uniform_complete_scripts"
                if uniform_script_code
                else "universal_complexity_then_script"
            ),
            "optimal_path_ties": path_counts[(n, m)][chosen[0]],
        },
    )


def _replace_semantics(
    operations: list[Operation],
    atomic_edges: list[CandidateEdge],
    diagnostics: tuple[dict, ...],
) -> list[CandidateEdge]:
    compound = {
        (tuple(item["source"]), tuple(item["target"])): float(item["semantic_bits"])
        for item in diagnostics
    }
    atomic = {(edge.source, edge.target): edge for edge in atomic_edges}
    result = []
    for source, target, _score in operations:
        edge = atomic[(tuple(source), tuple(target))]
        semantic = compound.get((edge.source, edge.target), edge.semantic_bits)
        result.append(
            CandidateEdge(
                edge.start,
                edge.end,
                edge.source,
                edge.target,
                edge.raw_score,
                semantic,
            )
        )
    return result


def _raw_composition_edges(
    lines_a: list[str],
    lines_b: list[str],
    source_vectors: np.ndarray,
    target_vectors: np.ndarray,
    atomic_edges: list[CandidateEdge],
    encode_fn: Callable[[list[str]], np.ndarray],
) -> list[CandidateEdge]:
    """Score complete joined blocks without mixing cosine units with MDL bits."""

    texts = []
    relation_text: dict[tuple[tuple[int, ...], tuple[int, ...]], str] = {}
    for edge in atomic_edges:
        if len(edge.source) > 1:
            text = _smart_join_lines([lines_a[index] for index in edge.source])
        elif len(edge.target) > 1:
            text = _smart_join_lines([lines_b[index] for index in edge.target])
        else:
            continue
        relation_text[(edge.source, edge.target)] = text
        texts.append(text)
    texts = list(dict.fromkeys(texts))
    encoded = normalize_embeddings(encode_fn(texts)) if texts else np.empty((0, 0))
    by_text = dict(zip(texts, encoded))
    result = []
    for edge in atomic_edges:
        if len(edge.source) > 1:
            semantic = float(
                by_text[relation_text[(edge.source, edge.target)]]
                @ target_vectors[edge.target[0]]
            )
        elif len(edge.target) > 1:
            semantic = float(
                source_vectors[edge.source[0]]
                @ by_text[relation_text[(edge.source, edge.target)]]
            )
        else:
            semantic = edge.raw_score
        result.append(
            CandidateEdge(
                edge.start,
                edge.end,
                edge.source,
                edge.target,
                semantic,
                semantic,
            )
        )
    return result


def align_local_recursive_mdl(
    lines_a: list[str],
    lines_b: list[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    encode_fn: Callable[[list[str]], np.ndarray],
) -> LocalRecursiveMDLResult:
    """Run atomic and dual-composition gapless local realignment."""

    source = normalize_embeddings(embeddings_a)
    target = normalize_embeddings(embeddings_b)
    if source.shape[0] != len(lines_a) or target.shape[0] != len(lines_b):
        raise ValueError("局部文本与嵌入行数不一致")
    scores = source @ target.T
    evidence = mutual_rank_code_evidence(scores)
    atomic_edges = _all_gapless_edges(scores, evidence)
    candidate_operations = [
        (edge.source, edge.target, edge.raw_score) for edge in atomic_edges
    ]
    atomic = align_gapless_evidence_mdl(
        len(lines_a),
        len(lines_b),
        atomic_edges,
        uniform_script_code=True,
    )

    encoded_cache: dict[str, np.ndarray] = {}

    def cached_encode(texts: list[str]) -> np.ndarray:
        missing = [text for text in texts if text not in encoded_cache]
        if missing:
            vectors = np.asarray(encode_fn(missing), dtype=np.float64)
            encoded_cache.update(zip(missing, vectors))
        return np.vstack([encoded_cache[text] for text in texts])

    posterior_raw = align_counterfactual_composition_mdl(
        lines_a,
        lines_b,
        source,
        target,
        scores,
        evidence,
        candidate_operations,
        cached_encode,
        evidence_model="posterior_reweight",
    )
    dld_raw = align_counterfactual_composition_mdl(
        lines_a,
        lines_b,
        source,
        target,
        scores,
        evidence,
        candidate_operations,
        cached_encode,
        evidence_model="counterfactual_dld",
    )
    dld_edges = _replace_semantics(
        candidate_operations, atomic_edges, dld_raw.diagnostics
    )
    posterior_edges = _replace_semantics(
        candidate_operations, atomic_edges, posterior_raw.diagnostics
    )
    dld = align_gapless_evidence_mdl(
        len(lines_a), len(lines_b), dld_edges, uniform_script_code=True
    )
    posterior = align_gapless_evidence_mdl(
        len(lines_a),
        len(lines_b),
        posterior_edges,
        uniform_script_code=True,
    )
    raw_edges = _raw_composition_edges(
        lines_a,
        lines_b,
        source,
        target,
        atomic_edges,
        cached_encode,
    )
    raw_target_complexity = (
        dld.complexity
        if dld.complexity == posterior.complexity
        else min(dld.complexity, posterior.complexity)
    )
    raw = align_gapless_evidence_mdl(
        len(lines_a),
        len(lines_b),
        raw_edges,
        target_complexity=raw_target_complexity,
        uniform_script_code=True,
    )

    def signature(path):
        return [(source, target) for source, target, _score in path]

    status = (
        "aligned"
        if dld.complexity == posterior.complexity
        and signature(dld.all_ops)
        == signature(posterior.all_ops)
        == signature(raw.all_ops)
        else "needs_review"
    )
    return LocalRecursiveMDLResult(
        status=status,
        all_ops=dld.all_ops,
        alternative_ops=posterior.all_ops,
        atomic_ops=atomic.all_ops,
        raw_composition_ops=raw.all_ops,
        dld=dld,
        posterior=posterior,
        stats={
            "source_lines": len(lines_a),
            "target_lines": len(lines_b),
            "candidate_edges": len(atomic_edges),
            "composition_encoded_texts": len(encoded_cache),
            "dld_complexity": dld.complexity,
            "posterior_complexity": posterior.complexity,
            "raw_composition_complexity": raw.complexity,
            "raw_composition_optimal_paths": raw.solver_stats["optimal_path_ties"],
        },
    )
