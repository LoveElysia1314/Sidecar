"""Counterfactual composition evidence for the production MDL solver.

For a proposed N:1 or 1:N relation, encode the full multi-line block and its
leave-one-line-out ablations.  The composition diagnostic asks whether the
full block benefits the proposed counterpart more than it benefits unrelated
atomic lines on the same document side.

The diagnostic is converted to a finite Zipf rank code and used as a
normalized change of measure over the existing atomic distribution.  This
produces an additive bit correction without a score threshold or an arbitrary
numeric multiplier.  The pipeline compares two defensible codes and exposes
their path disagreements for review instead of hiding model uncertainty.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import numpy as np

from dualign.algorithms.mdl.cosine_observation import observed_cosine_matrix
from dualign.core.text import smart_join_lines as _smart_join_lines
from dualign.algorithms.mdl.mdl_aligner import (
    Operation,
    _elias_delta_length,
    _harmonic_number,
    _structure_counts,
)
from dualign.algorithms.mdl.runtime import check_atomic_alignment_deadline

Vertex = tuple[int, int]


@dataclass(frozen=True)
class ConditionalRankEvidence:
    diagnostic: np.ndarray
    ranks: np.ndarray
    correction_bits: np.ndarray


@dataclass(frozen=True)
class CandidateEdge:
    start: Vertex
    end: Vertex
    source: tuple[int, ...]
    target: tuple[int, ...]
    raw_score: float
    semantic_bits: float

    @property
    def complexity(self) -> int:
        if self.source and self.target:
            return max(len(self.source), len(self.target)) - 1
        return len(self.source) + len(self.target)


@dataclass(frozen=True)
class ExplicitMDLResult:
    all_ops: list[Operation]
    complexity: int
    semantic_bits: float
    structure_bits: float
    objective_bits: float
    candidate_edges: int
    frontier: tuple[tuple[int, float, float, float], ...]
    solver_stats: dict


@dataclass(frozen=True)
class CounterfactualCompositionResult:
    alignment: ExplicitMDLResult
    evidence_model: str
    encoded_texts: int
    semantic_candidates: int
    composition_candidates: int
    diagnostics: tuple[dict, ...]


@dataclass(frozen=True)
class _PreparedCompositionModels:
    n: int
    m: int
    posterior_edges: tuple[CandidateEdge, ...]
    dld_edges: tuple[CandidateEdge, ...]
    posterior_diagnostics: tuple[dict, ...]
    dld_diagnostics: tuple[dict, ...]
    encoded_texts: int
    semantic_candidates: int
    composition_candidates: int


def counterfactual_diagnostics(
    full_scores: np.ndarray,
    ablated_scores: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ordinal wins and full-vs-best-ablation gains per counterpart."""

    full = np.asarray(full_scores, dtype=np.float64)
    ablated = np.asarray(ablated_scores, dtype=np.float64)
    if full.ndim != 1 or ablated.ndim != 2 or ablated.shape[1] != full.size:
        raise ValueError("完整块与消融块分数形状不一致")
    if not ablated.shape[0]:
        raise ValueError("组合证据至少需要一个消融块")
    wins = np.sum(full[np.newaxis, :] > ablated, axis=0).astype(np.float64)
    gains = full - np.max(ablated, axis=0)
    return wins, gains


def conditional_rank_evidence(
    atomic_bits: np.ndarray,
    diagnostic: np.ndarray,
) -> ConditionalRankEvidence:
    """Turn a composition ordering into a normalized conditional bit code.

    Atomic bits define the current counterpart distribution ``q_A``.  The
    diagnostic receives a finite Zipf rank weight ``w``.  Reweighting and
    normalizing gives ``q_AC ∝ q_A w``; the returned correction is
    ``log2(q_AC / q_A)``.  Consequently ``sum(q_A * 2**correction) == 1`` and
    the correction can be added to an atomic edge without a tunable scale.
    Ties conservatively receive the worst rank in their tied group.
    """

    atomic = np.asarray(atomic_bits, dtype=np.float64)
    values = np.asarray(diagnostic, dtype=np.float64)
    if atomic.ndim != 1 or values.shape != atomic.shape or not atomic.size:
        raise ValueError("原子证据与组合统计量必须是同长度非空向量")

    shifted = atomic - float(np.max(atomic))
    atomic_weights = np.exp2(shifted)
    atomic_probability = atomic_weights / float(np.sum(atomic_weights))

    ordered = np.sort(values)
    ranks = values.size - np.searchsorted(ordered, values, side="left")
    zipf_weights = 1.0 / (ranks * _harmonic_number(values.size))
    normalizer = float(np.dot(atomic_probability, zipf_weights))
    correction = np.log2(zipf_weights / normalizer)
    return ConditionalRankEvidence(values, ranks.astype(np.int32), correction)


def _uniform_rank_savings(diagnostic: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Code savings against an exchangeable counterpart null."""

    values = np.asarray(diagnostic, dtype=np.float64)
    ordered = np.sort(values)
    ranks = values.size - np.searchsorted(ordered, values, side="left")
    savings = np.log2(values.size / (ranks * _harmonic_number(values.size)))
    return ranks.astype(np.int32), savings


def _normalized(vectors: np.ndarray) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float64)
    if not matrix.size:
        return matrix
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def _block_variants(lines: list[str], indices: tuple[int, ...]) -> list[str]:
    block = [lines[index] for index in indices]
    return [
        _smart_join_lines(block),
        *(
            _smart_join_lines(block[:dropped] + block[dropped + 1 :])
            for dropped in range(len(block))
        ),
    ]


def decision_relevant_candidates(
    candidates: list[Operation] | tuple[Operation, ...],
    atomic_path: list[Operation],
    scores: np.ndarray | None = None,
) -> tuple[Operation, ...]:
    """Keep only compounds which can test or reverse the current decision.

    Joined-block evidence is useful for two local questions: whether a
    compound edge already selected by the atomic solver should instead be a
    sub-block plus a gap, and whether one boundary line currently assigned to
    a gap should instead be absorbed by its neighbouring semantic edge.  All
    1:1 proposal edges are retained because they require no joined encoding
    and provide the alternatives used by the final sparse MDL pass.

    The boundary closure is a structural, parameter-free proposal rule.  It
    starts with one-line moves around selected gaps, then materializes the
    recursive prefix/suffix sub-blocks needed by H_subblock+gap.  It
    deliberately does not retain every compound edge which merely occurred
    on an unrelated local Pareto path.
    """

    matrix = None if scores is None else np.asarray(scores, dtype=np.float64)

    def relation_score(source: tuple[int, ...], target: tuple[int, ...], fallback):
        if matrix is None:
            return fallback
        return float(matrix[np.ix_(source, target)].mean())

    selected: dict[tuple[tuple[int, ...], tuple[int, ...]], Operation] = {
        (tuple(source), tuple(target)): (tuple(source), tuple(target), score)
        for source, target, score in candidates
        if len(source) == 1 and len(target) == 1
    }
    for source, target, score in atomic_path:
        if source and target and (len(source) > 1 or len(target) > 1):
            selected[(tuple(source), tuple(target))] = (
                tuple(source),
                tuple(target),
                score,
            )

    for index, (gap_source, gap_target, _gap_score) in enumerate(atomic_path):
        if bool(gap_source) == bool(gap_target):
            continue
        neighbours = []
        if index:
            neighbours.append(("previous", atomic_path[index - 1]))
        if index + 1 < len(atomic_path):
            neighbours.append(("next", atomic_path[index + 1]))
        for side, (source, target, score) in neighbours:
            if not source or not target:
                continue
            if gap_source and len(target) == 1:
                boundary = gap_source[0] if side == "previous" else gap_source[-1]
                merged_source = (
                    tuple(source) + (boundary,)
                    if side == "previous"
                    else (boundary,) + tuple(source)
                )
                relation = (merged_source, tuple(target))
            elif gap_target and len(source) == 1:
                boundary = gap_target[0] if side == "previous" else gap_target[-1]
                merged_target = (
                    tuple(target) + (boundary,)
                    if side == "previous"
                    else (boundary,) + tuple(target)
                )
                relation = (tuple(source), merged_target)
            else:
                continue
            selected[relation] = (relation[0], relation[1], score)

    # A counterfactual must be an actual path alternative, not merely a
    # number subtracted from the merge edge.  Recursively add the two direct
    # contiguous sub-blocks of every compound proposal.  The closure contains
    # exactly the prefix/suffix hypotheses reachable by moving a semantic
    # boundary; no span limit or semantic threshold is involved.
    queue = [
        relation
        for relation in selected
        if len(relation[0]) > 1 or len(relation[1]) > 1
    ]
    visited = set()
    while queue:
        source, target = queue.pop()
        if (source, target) in visited:
            continue
        visited.add((source, target))
        if len(source) > 1:
            subblocks = ((source[:-1], target), (source[1:], target))
        elif len(target) > 1:
            subblocks = ((source, target[:-1]), (source, target[1:]))
        else:
            continue
        fallback = selected[(source, target)][2]
        for sub_source, sub_target in subblocks:
            relation = (tuple(sub_source), tuple(sub_target))
            if relation not in selected:
                selected[relation] = (
                    relation[0],
                    relation[1],
                    relation_score(relation[0], relation[1], fallback),
                )
            if len(relation[0]) > 1 or len(relation[1]) > 1:
                queue.append(relation)
    return tuple(selected.values())


def _prepare_counterfactual_composition_models(
    lines_a: list[str],
    lines_b: list[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    scores: np.ndarray,
    evidence: np.ndarray,
    candidates: list[Operation] | tuple[Operation, ...],
    encode_fn: Callable[[list[str]], np.ndarray],
) -> _PreparedCompositionModels:
    """Compute the shared block diagnostics for both composition codes once.

    Atomic rank-code evidence defines the base counterpart distribution.  For
    every N:1/1:N candidate, the joined block is compared with every
    leave-one-line-out ablation against all atomic lines on the other side.
    The selected gain rank becomes a normalized conditional bit correction;
    there is no cosine threshold or free multiplier.
    """

    matrix = np.asarray(scores, dtype=np.float64)
    bits = np.asarray(evidence, dtype=np.float64)
    source_vectors = _normalized(embeddings_a)
    target_vectors = _normalized(embeddings_b)
    n, m = matrix.shape
    if (
        bits.shape != matrix.shape
        or source_vectors.shape[0] != n
        or target_vectors.shape[0] != m
    ):
        raise ValueError("组合证据输入的行数或矩阵形状不一致")

    relations = {
        (tuple(source), tuple(target))
        for source, target, _score in candidates
        if source
        and target
        and (len(source) == 1 or len(target) == 1)
        and not (len(source) > 1 and len(target) > 1)
    }
    variants = {
        relation: (
            _block_variants(lines_a, relation[0])
            if len(relation[0]) > 1
            else _block_variants(lines_b, relation[1])
        )
        for relation in relations
        if len(relation[0]) > 1 or len(relation[1]) > 1
    }
    texts = list(
        dict.fromkeys(
            text
            for relation_variants in variants.values()
            for text in relation_variants
        )
    )
    encoded = _normalized(encode_fn(texts)) if texts else np.empty((0, 0))
    by_text = dict(zip(texts, encoded))

    posterior_edges = []
    dld_edges = []
    posterior_diagnostics = []
    dld_diagnostics = []
    for source, target in sorted(relations):
        start = (source[0], target[0])
        end = (source[-1] + 1, target[-1] + 1)
        if len(source) == 1 and len(target) == 1:
            selected_source, selected_target = source[0], target[0]
            semantic = float(bits[selected_source, selected_target])
            raw_score = float(matrix[selected_source, selected_target])
            posterior_semantic = dld_semantic = semantic
        elif len(source) > 1:
            variant_texts = variants[(source, target)]
            block_vectors = np.vstack([by_text[text] for text in variant_texts])
            variant_scores = observed_cosine_matrix(
                variant_texts,
                lines_b,
                block_vectors,
                target_vectors,
            )
            full_scores = variant_scores[0]
            ablated_scores = variant_scores[1:]
            _wins, gains = counterfactual_diagnostics(full_scores, ablated_scores)
            atomic_by_target = bits[np.array(source), :].sum(axis=0)
            correction = conditional_rank_evidence(atomic_by_target, gains)
            selected = target[0]
            posterior_semantic = float(
                atomic_by_target[selected] + correction.correction_bits[selected]
            )
            direct_ablations = ablated_scores[[0, -1], :]
            _direct_wins, direct_gains = counterfactual_diagnostics(
                full_scores, direct_ablations
            )
            necessity_ranks, necessity_bits = _uniform_rank_savings(direct_gains)
            direct_atomic = np.maximum(
                bits[np.array(source[:-1]), :].sum(axis=0),
                bits[np.array(source[1:]), :].sum(axis=0),
            )
            dld_semantic = float(direct_atomic[selected] + necessity_bits[selected])
            raw_score = float(matrix[np.array(source), selected].mean())
            common = {
                "source": source,
                "target": target,
                "relation": f"{len(source)}:1",
                "gain": float(gains[selected]),
                "gain_rank": int(correction.ranks[selected]),
                "correction_bits": float(correction.correction_bits[selected]),
                "atomic_bits": float(atomic_by_target[selected]),
                "posterior_semantic_bits": posterior_semantic,
            }
            posterior_diagnostics.append(
                {
                    **common,
                    "necessity_rank": int(correction.ranks[selected]),
                    "necessity_bits": float(correction.correction_bits[selected]),
                    "direct_subblock_bits": float(atomic_by_target[selected]),
                    "dld_semantic_bits": posterior_semantic,
                    "semantic_bits": posterior_semantic,
                }
            )
            dld_diagnostics.append(
                {
                    **common,
                    "necessity_rank": int(necessity_ranks[selected]),
                    "necessity_bits": float(necessity_bits[selected]),
                    "direct_subblock_bits": float(direct_atomic[selected]),
                    "dld_semantic_bits": dld_semantic,
                    "semantic_bits": dld_semantic,
                }
            )
        else:
            variant_texts = variants[(source, target)]
            block_vectors = np.vstack([by_text[text] for text in variant_texts])
            variant_scores = observed_cosine_matrix(
                lines_a,
                variant_texts,
                source_vectors,
                block_vectors,
            )
            full_scores = variant_scores[:, 0]
            ablated_scores = variant_scores[:, 1:].T
            _wins, gains = counterfactual_diagnostics(full_scores, ablated_scores)
            atomic_by_source = bits[:, np.array(target)].sum(axis=1)
            correction = conditional_rank_evidence(atomic_by_source, gains)
            selected = source[0]
            posterior_semantic = float(
                atomic_by_source[selected] + correction.correction_bits[selected]
            )
            direct_ablations = ablated_scores[[0, -1], :]
            _direct_wins, direct_gains = counterfactual_diagnostics(
                full_scores, direct_ablations
            )
            necessity_ranks, necessity_bits = _uniform_rank_savings(direct_gains)
            direct_atomic = np.maximum(
                bits[:, np.array(target[:-1])].sum(axis=1),
                bits[:, np.array(target[1:])].sum(axis=1),
            )
            dld_semantic = float(direct_atomic[selected] + necessity_bits[selected])
            raw_score = float(matrix[selected, np.array(target)].mean())
            common = {
                "source": source,
                "target": target,
                "relation": f"1:{len(target)}",
                "gain": float(gains[selected]),
                "gain_rank": int(correction.ranks[selected]),
                "correction_bits": float(correction.correction_bits[selected]),
                "atomic_bits": float(atomic_by_source[selected]),
                "posterior_semantic_bits": posterior_semantic,
            }
            posterior_diagnostics.append(
                {
                    **common,
                    "necessity_rank": int(correction.ranks[selected]),
                    "necessity_bits": float(correction.correction_bits[selected]),
                    "direct_subblock_bits": float(atomic_by_source[selected]),
                    "dld_semantic_bits": posterior_semantic,
                    "semantic_bits": posterior_semantic,
                }
            )
            dld_diagnostics.append(
                {
                    **common,
                    "necessity_rank": int(necessity_ranks[selected]),
                    "necessity_bits": float(necessity_bits[selected]),
                    "direct_subblock_bits": float(direct_atomic[selected]),
                    "dld_semantic_bits": dld_semantic,
                    "semantic_bits": dld_semantic,
                }
            )
        posterior_edges.append(
            CandidateEdge(start, end, source, target, raw_score, posterior_semantic)
        )
        dld_edges.append(
            CandidateEdge(start, end, source, target, raw_score, dld_semantic)
        )

    return _PreparedCompositionModels(
        n=n,
        m=m,
        posterior_edges=tuple(posterior_edges),
        dld_edges=tuple(dld_edges),
        posterior_diagnostics=tuple(posterior_diagnostics),
        dld_diagnostics=tuple(dld_diagnostics),
        encoded_texts=len(texts),
        semantic_candidates=len(posterior_edges),
        composition_candidates=len(dld_diagnostics),
    )


def _solve_prepared_composition_model(
    prepared: _PreparedCompositionModels,
    evidence_model: str,
) -> CounterfactualCompositionResult:
    if evidence_model == "posterior_reweight":
        edges = prepared.posterior_edges
        diagnostics = prepared.posterior_diagnostics
    elif evidence_model == "counterfactual_dld":
        edges = prepared.dld_edges
        diagnostics = prepared.dld_diagnostics
    else:
        raise ValueError(f"未知组合证据模型: {evidence_model}")
    return CounterfactualCompositionResult(
        alignment=align_explicit_evidence_mdl(prepared.n, prepared.m, list(edges)),
        evidence_model=evidence_model,
        encoded_texts=prepared.encoded_texts,
        semantic_candidates=prepared.semantic_candidates,
        composition_candidates=prepared.composition_candidates,
        diagnostics=diagnostics,
    )


def align_counterfactual_composition_models_mdl(
    lines_a: list[str],
    lines_b: list[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    scores: np.ndarray,
    evidence: np.ndarray,
    candidates: list[Operation] | tuple[Operation, ...],
    encode_fn: Callable[[list[str]], np.ndarray],
) -> tuple[CounterfactualCompositionResult, CounterfactualCompositionResult]:
    """Solve posterior and DLD codes from one shared composition audit."""

    prepared = _prepare_counterfactual_composition_models(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        scores,
        evidence,
        candidates,
        encode_fn,
    )
    return (
        _solve_prepared_composition_model(prepared, "posterior_reweight"),
        _solve_prepared_composition_model(prepared, "counterfactual_dld"),
    )


def align_counterfactual_composition_mdl(
    lines_a: list[str],
    lines_b: list[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    scores: np.ndarray,
    evidence: np.ndarray,
    candidates: list[Operation] | tuple[Operation, ...],
    encode_fn: Callable[[list[str]], np.ndarray],
    *,
    evidence_model: str = "posterior_reweight",
) -> CounterfactualCompositionResult:
    """Solve one composition code while preserving the public research API."""

    prepared = _prepare_counterfactual_composition_models(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        scores,
        evidence,
        candidates,
        encode_fn,
    )
    return _solve_prepared_composition_model(prepared, evidence_model)


def _prune(states: dict[int, float]) -> None:
    strongest = float("-inf")
    for complexity in sorted(tuple(states)):
        semantic = states[complexity]
        if semantic <= strongest:
            del states[complexity]
        else:
            strongest = semantic


def _collapse_gaps(operations: list[Operation]) -> list[Operation]:
    collapsed: list[Operation] = []
    for source, target, score in operations:
        if collapsed and source and not target and not collapsed[-1][1]:
            old_source, _, _ = collapsed[-1]
            collapsed[-1] = (old_source + source, (), 0.0)
        elif collapsed and target and not source and not collapsed[-1][0]:
            _, old_target, _ = collapsed[-1]
            collapsed[-1] = ((), old_target + target, 0.0)
        else:
            collapsed.append((source, target, score))
    return collapsed


def align_explicit_evidence_mdl(
    n: int,
    m: int,
    semantic_edges: list[CandidateEdge],
) -> ExplicitMDLResult:
    """Run exact full-grammar MDL on a sparse semantic-edge antichain.

    A path with ``r`` semantic operations has complexity ``n + m - 2r``:
    every legal N:1/1:N edge consumes ``a+b`` lines at cost ``a+b-2``, while
    every uncovered line costs one gap bit.  Gap-only grid vertices therefore
    carry no independent decision.  We remove them exactly and solve the
    remaining maximum-weight, fixed-cardinality monotone edge-chain problem.

    A source-coordinate sweep and a Fenwick prefix maximum over target
    coordinates answer all predecessor dominance queries.  This replaces the
    old O(n*m) gap lattice with work tied to the sparse proposal graph, without
    changing the objective or imposing a corridor width/score threshold.
    """

    edges = list(semantic_edges)
    for edge in edges:
        source_size = edge.end[0] - edge.start[0]
        target_size = edge.end[1] - edge.start[1]
        if (
            edge.start[0] < 0
            or edge.start[1] < 0
            or edge.end[0] > n
            or edge.end[1] > m
            or source_size < 1
            or target_size < 1
            or (source_size > 1 and target_size > 1)
            or edge.complexity != source_size + target_size - 2
        ):
            raise ValueError(f"候选边不属于 N:1/1:N 语法: {edge.start} -> {edge.end}")

    edge_count = len(edges)
    edge_states: list[dict[int, float]] = [{} for _edge in edges]
    predecessors: dict[tuple[int, int], int] = {}
    tree: list[dict[int, tuple[float, int]]] = [{} for _target in range(m + 2)]
    unchecked_frontier_work = 0

    def prune_frontier(frontier: dict[int, tuple[float, int]]) -> None:
        strongest = float("-inf")
        for relations in sorted(tuple(frontier), reverse=True):
            semantic = frontier[relations][0]
            if semantic <= strongest:
                del frontier[relations]
            else:
                strongest = semantic

    def merge_frontier(
        destination: dict[int, tuple[float, int]],
        candidate: dict[int, tuple[float, int]],
    ) -> None:
        nonlocal unchecked_frontier_work
        unchecked_frontier_work += len(candidate)
        if unchecked_frontier_work >= 4096:
            check_atomic_alignment_deadline("global_solver")
            unchecked_frontier_work = 0
        for relations, state in candidate.items():
            current = destination.get(relations)
            if current is None or state[0] > current[0]:
                destination[relations] = state
        prune_frontier(destination)

    def tree_update(
        target_end: int,
        candidate: dict[int, tuple[float, int]],
    ) -> None:
        position = target_end + 1
        while position < len(tree):
            merge_frontier(tree[position], candidate)
            position += position & -position

    def tree_query(target_start: int) -> dict[int, tuple[float, int]]:
        best: dict[int, tuple[float, int]] = {}
        position = target_start + 1
        while position:
            merge_frontier(best, tree[position])
            position -= position & -position
        return best

    tree_update(0, {0: (0.0, -1)})

    by_start: dict[int, list[int]] = defaultdict(list)
    for edge_id, edge in enumerate(edges):
        by_start[edge.start[0]].append(edge_id)
    pending = sorted(range(edge_count), key=lambda item: edges[item].end[0])
    pending_index = 0
    for source_start in range(n + 1):
        check_atomic_alignment_deadline("global_solver")
        while (
            pending_index < edge_count
            and edges[pending[pending_index]].end[0] <= source_start
        ):
            edge_id = pending[pending_index]
            tree_update(
                edges[edge_id].end[1],
                {
                    relations: (semantic, edge_id)
                    for relations, semantic in edge_states[edge_id].items()
                },
            )
            pending_index += 1
        for edge_id in by_start.get(source_start, ()):
            edge = edges[edge_id]
            best = tree_query(edge.start[1])
            for relations, (semantic, previous_edge) in best.items():
                end_relations = relations + 1
                edge_states[edge_id][end_relations] = semantic + edge.semantic_bits
                predecessors[(edge_id, end_relations)] = previous_edge

    while pending_index < edge_count:
        check_atomic_alignment_deadline("global_solver")
        edge_id = pending[pending_index]
        tree_update(
            edges[edge_id].end[1],
            {
                relations: (semantic, edge_id)
                for relations, semantic in edge_states[edge_id].items()
            },
        )
        pending_index += 1
    terminal_frontier = tree_query(m)
    terminal = {
        n + m - 2 * relations: float(semantic)
        for relations, (semantic, _edge_id) in terminal_frontier.items()
    }
    _prune(terminal)
    counts = _structure_counts(n, m, max(terminal))
    minimum_complexity = min(terminal)
    frontier = []
    monotone_structure = 0.0
    for complexity, semantic in sorted(terminal.items()):
        raw_structure = math.log2(counts[complexity]) + (
            _elias_delta_length(complexity - minimum_complexity + 1) - 1
        )
        monotone_structure = max(monotone_structure, raw_structure)
        frontier.append(
            (complexity, semantic, monotone_structure, semantic - monotone_structure)
        )
    chosen = max(frontier, key=lambda item: (item[3], -item[0]))

    relation_count = (n + m - chosen[0]) // 2
    selected_edges = []
    edge_id = int(terminal_frontier[relation_count][1])
    remaining = relation_count
    while remaining:
        if edge_id < 0:
            raise RuntimeError("稀疏显式 MDL 路径缺少语义边回溯")
        selected_edges.append(edges[edge_id])
        edge_id = int(predecessors[(edge_id, remaining)])
        remaining -= 1
    selected_edges.reverse()

    operations: list[Operation] = []
    cursor = (0, 0)
    for edge in selected_edges:
        if cursor[0] < edge.start[0]:
            operations.append((tuple(range(cursor[0], edge.start[0])), (), 0.0))
        if cursor[1] < edge.start[1]:
            operations.append(((), tuple(range(cursor[1], edge.start[1])), 0.0))
        operations.append((edge.source, edge.target, edge.raw_score))
        cursor = edge.end
    if cursor[0] < n:
        operations.append((tuple(range(cursor[0], n)), (), 0.0))
    if cursor[1] < m:
        operations.append(((), tuple(range(cursor[1], m)), 0.0))
    return ExplicitMDLResult(
        all_ops=_collapse_gaps(operations),
        complexity=chosen[0],
        semantic_bits=chosen[1],
        structure_bits=chosen[2],
        objective_bits=chosen[3],
        candidate_edges=len(semantic_edges),
        frontier=tuple(frontier),
        solver_stats={
            "algorithm": "sparse_cardinality_chain",
            "semantic_edges": edge_count,
            "pareto_states": sum(len(states) for states in edge_states),
            "maximum_edge_frontier": max(
                (len(states) for states in edge_states), default=0
            ),
            "fenwick_states": sum(len(states) for states in tree),
            "dense_grid_cells_avoided": int((n + 1) * (m + 1)),
        },
    )
