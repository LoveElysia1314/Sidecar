"""Production pipeline for statistically gated sparse-MDL alignment."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from dualign.algorithms.mdl.composition_mdl import (
    CounterfactualCompositionResult,
    align_counterfactual_composition_models_mdl,
    decision_relevant_candidates,
)
from dualign.algorithms.mdl.cosine_observation import observed_cosine_matrix
from dualign.algorithms.mdl.candidate_graph import (
    CenteredFrontierMDLResult,
    align_centered_frontier_mdl,
)
from dualign.algorithms.mdl.mdl_aligner import (
    Operation,
    mutual_rank_code_evidence,
    normalize_embeddings,
)
from dualign.algorithms.mdl.robustness import (
    MonotoneEvidenceComparison,
    compare_monotone_evidence,
    conformal_upper_p,
    symmetric_nearest_score,
)
from dualign.core.punctuation import UniversalSplitter


@dataclass(frozen=True)
class AlignmentCalibration:
    """Two empirical reference sets and one declared error rate."""

    existence_null: np.ndarray
    acceptable_monotone_losses: np.ndarray
    alpha: float


@dataclass(frozen=True)
class AlignmentGateDecision:
    accepted: bool
    reason: str
    existence_score: float
    existence_p: float
    order: MonotoneEvidenceComparison | None
    order_compatibility_p: float | None


@dataclass(frozen=True)
class MDLPipelineResult:
    status: str
    gate: AlignmentGateDecision
    all_ops: list[Operation]
    alternative_ops: list[Operation]
    uncertain_regions: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
    atomic_ops: list[Operation]
    scaffold: list[Operation]
    centered: CenteredFrontierMDLResult | None
    composition: CounterfactualCompositionResult | None
    alternative_composition: CounterfactualCompositionResult | None
    stats: dict


def assess_alignment_applicability(
    scores: np.ndarray,
    calibration: AlignmentCalibration,
) -> AlignmentGateDecision:
    """Test correspondence, then loss under the monotone evidence model."""

    decision, _evidence = _assess_alignment_applicability(scores, calibration)
    return decision


def _assess_alignment_applicability(
    scores: np.ndarray,
    calibration: AlignmentCalibration,
) -> tuple[AlignmentGateDecision, np.ndarray | None]:
    """Return the gate decision and rank evidence only when correspondence exists."""

    if not 0.0 < calibration.alpha < 1.0:
        raise ValueError("显著性水平 alpha 必须位于 (0, 1)")
    existence_score = symmetric_nearest_score(scores)
    existence_p = conformal_upper_p(existence_score, calibration.existence_null)
    if existence_p > calibration.alpha:
        return (
            AlignmentGateDecision(
                accepted=False,
                reason="no_correspondence",
                existence_score=existence_score,
                existence_p=existence_p,
                order=None,
                order_compatibility_p=None,
            ),
            None,
        )

    evidence = mutual_rank_code_evidence(scores)
    order = compare_monotone_evidence(evidence)
    order_compatibility_p = conformal_upper_p(
        order.relative_loss,
        calibration.acceptable_monotone_losses,
    )
    accepted = order_compatibility_p > calibration.alpha
    return (
        AlignmentGateDecision(
            accepted=accepted,
            reason="" if accepted else "order_incompatible",
            existence_score=existence_score,
            existence_p=existence_p,
            order=order,
            order_compatibility_p=order_compatibility_p,
        ),
        evidence,
    )


def _uncertain_regions(
    first: list[Operation], second: list[Operation]
) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
    """Return maximal path intervals on which two complete paths disagree."""

    def indexed(path):
        cursor = (0, 0)
        edges = []
        vertices = {cursor}
        for source, target, _score in path:
            end = (cursor[0] + len(source), cursor[1] + len(target))
            edges.append((cursor, end, tuple(source), tuple(target)))
            vertices.add(end)
            cursor = end
        return cursor, vertices, edges

    first_end, first_vertices, first_edges = indexed(first)
    second_end, second_vertices, second_edges = indexed(second)
    if first_end != second_end:
        raise ValueError("待比较路径没有相同终点")
    shared = sorted(
        first_vertices & second_vertices,
        key=lambda item: (sum(item), item[0]),
    )

    def segmented_signatures(edges):
        signatures = []
        edge_index = 0
        for start, end in zip(shared, shared[1:]):
            signature = []
            cursor = start
            while cursor != end:
                if edge_index >= len(edges) or edges[edge_index][0] != cursor:
                    raise ValueError("路径边与共享顶点不连续")
                _edge_start, edge_end, source, target = edges[edge_index]
                signature.append((source, target))
                cursor = edge_end
                edge_index += 1
            signatures.append(tuple(signature))
        if edge_index != len(edges):
            raise ValueError("路径在共同终点之后仍有剩余边")
        return signatures

    first_signatures = segmented_signatures(first_edges)
    second_signatures = segmented_signatures(second_edges)
    regions = []
    region_start = None
    for index, (start, _end) in enumerate(zip(shared, shared[1:])):
        agrees = first_signatures[index] == second_signatures[index]
        if not agrees and region_start is None:
            region_start = start
        if agrees and region_start is not None:
            regions.append((region_start, start))
            region_start = None
    if region_start is not None:
        regions.append((region_start, shared[-1]))
    return tuple(regions)


def _reviewable_uncertain_regions(
    provisional: list[Operation],
    alternative: list[Operation],
) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
    """Return every disagreement between the two composition decisions.

    ``provisional`` is the conservative DLD path and remains the generated
    alignment; ``alternative`` is the broader posterior path.  The atomic path
    is deliberately absent: it remains useful diagnostic evidence, but cannot
    suppress or create a review decision.  Thus the rule is exactly ``D != P``
    and introduces no third-model exception or score threshold.
    """

    return _uncertain_regions(provisional, alternative)


def _path_segment(
    path: list[Operation],
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[Operation]:
    """Return the complete path segment between two path vertices."""

    cursor = (0, 0)
    segment: list[Operation] = []
    collecting = cursor == start
    for operation in path:
        source, target, _score = operation
        next_cursor = (cursor[0] + len(source), cursor[1] + len(target))
        if collecting:
            segment.append(operation)
            if next_cursor == end:
                return segment
            if next_cursor[0] > end[0] or next_cursor[1] > end[1]:
                break
        elif next_cursor == start:
            collecting = True
        cursor = next_cursor
    raise ValueError("分歧区域不是路径的完整片段")


def _hard_boundary_sum_gain(
    lines_a: list[str],
    lines_b: list[str],
    source_vectors: np.ndarray,
    target_vectors: np.ndarray,
    provisional_segment: list[Operation],
    alternative_segment: list[Operation],
    encode_fn: Callable[[list[str]], np.ndarray],
) -> float | None:
    """Return the best latent hard-boundary witness for a 2:1/1:2 merge.

    This is deliberately a one-way witness.  It is defined only when the
    conservative path is one gap plus one 1:1 relation and posterior proposes
    the corresponding two-line merge.  Failure is therefore absence of extra
    evidence, never evidence against the merge.
    """

    if len(provisional_segment) != 2 or len(alternative_segment) != 1:
        return None
    compound_source, compound_target, _score = alternative_segment[0]
    gap_count = sum(
        not source or not target for source, target, _ in provisional_segment
    )
    atomic_count = sum(
        len(source) == len(target) == 1 for source, target, _ in provisional_segment
    )
    if gap_count != 1 or atomic_count != 1:
        return None

    if len(compound_source) == 2 and len(compound_target) == 1:
        target_index = compound_target[0]
        whole = lines_b[target_index]
        points = [
            point
            for point in UniversalSplitter.find_hard_split_points(whole)
            if whole[:point].strip() and whole[point:].strip()
        ]
        if not points:
            return None
        fragments = [
            part
            for point in points
            for part in (whole[:point].strip(), whole[point:].strip())
        ]
        fragment_vectors = normalize_embeddings(encode_fn(fragments))
        baseline = observed_cosine_matrix(
            [lines_a[index] for index in compound_source],
            [whole],
            source_vectors[list(compound_source)],
            target_vectors[[target_index]],
        )[:, 0].astype(np.float64)
        split_scores = observed_cosine_matrix(
            [lines_a[index] for index in compound_source],
            fragments,
            source_vectors[list(compound_source)],
            fragment_vectors,
        ).astype(np.float64)
        return max(
            float(
                split_scores[0, 2 * point_index]
                + split_scores[1, 2 * point_index + 1]
                - baseline.sum()
            )
            for point_index in range(len(points))
        )

    if len(compound_source) == 1 and len(compound_target) == 2:
        source_index = compound_source[0]
        whole = lines_a[source_index]
        points = [
            point
            for point in UniversalSplitter.find_hard_split_points(whole)
            if whole[:point].strip() and whole[point:].strip()
        ]
        if not points:
            return None
        fragments = [
            part
            for point in points
            for part in (whole[:point].strip(), whole[point:].strip())
        ]
        fragment_vectors = normalize_embeddings(encode_fn(fragments))
        baseline = observed_cosine_matrix(
            [whole],
            [lines_b[index] for index in compound_target],
            source_vectors[[source_index]],
            target_vectors[list(compound_target)],
        )[0].astype(np.float64)
        split_scores = observed_cosine_matrix(
            fragments,
            [lines_b[index] for index in compound_target],
            fragment_vectors,
            target_vectors[list(compound_target)],
        ).astype(np.float64)
        return max(
            float(
                split_scores[2 * point_index, 0]
                + split_scores[2 * point_index + 1, 1]
                - baseline.sum()
            )
            for point_index in range(len(points))
        )
    return None


def _resolve_hard_boundary_witnesses(
    lines_a: list[str],
    lines_b: list[str],
    source_vectors: np.ndarray,
    target_vectors: np.ndarray,
    provisional: list[Operation],
    alternative: list[Operation],
    regions: tuple[tuple[tuple[int, int], tuple[int, int]], ...],
    encode_fn: Callable[[list[str]], np.ndarray],
) -> tuple[list[Operation], tuple[tuple[tuple[int, int], tuple[int, int]], ...]]:
    """Promote posterior only where a latent hard split has positive total gain."""

    resolved: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for start, end in regions:
        provisional_segment = _path_segment(provisional, start, end)
        alternative_segment = _path_segment(alternative, start, end)
        gain = _hard_boundary_sum_gain(
            lines_a,
            lines_b,
            source_vectors,
            target_vectors,
            provisional_segment,
            alternative_segment,
            encode_fn,
        )
        if gain is not None and gain > 0.0:
            resolved.add((start, end))

    if not resolved:
        return provisional, regions

    resolved_path: list[Operation] = []
    cursor = (0, 0)
    for region in regions:
        start, end = region
        if cursor != start:
            resolved_path.extend(_path_segment(provisional, cursor, start))
        selected = alternative if region in resolved else provisional
        resolved_path.extend(_path_segment(selected, start, end))
        cursor = end
    final_end = (
        sum(len(source) for source, _target, _score in provisional),
        sum(len(target) for _source, target, _score in provisional),
    )
    if cursor != final_end:
        resolved_path.extend(_path_segment(provisional, cursor, final_end))
    remaining = tuple(region for region in regions if region not in resolved)
    return resolved_path, remaining


def align_mdl_pipeline(
    lines_a: list[str],
    lines_b: list[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    encode_fn: Callable[[list[str]], np.ndarray],
    calibration: AlignmentCalibration,
) -> MDLPipelineResult:
    """Run the converged gate -> sparse atomic MDL -> composition audit.

    Rejected inputs deliberately return no alignment operations.  The
    algorithm abstains instead of manufacturing a path which downstream code
    might mistake for a usable alignment.  Accepted inputs are evaluated by
    both defensible composition codes.  The counterfactual-DLD path is the
    conservative provisional path; disagreement with posterior reweighting is
    surfaced as ``needs_review`` rather than hidden behind another threshold.
    """

    started = time.perf_counter()
    source_vectors = normalize_embeddings(embeddings_a)
    target_vectors = normalize_embeddings(embeddings_b)
    if source_vectors.shape[0] != len(lines_a) or target_vectors.shape[0] != len(
        lines_b
    ):
        raise ValueError("文本行数与嵌入行数不一致")
    if not lines_a or not lines_b:
        raise ValueError("统计门控研究管线要求两侧文档均非空")

    scores = observed_cosine_matrix(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
    )
    gate, evidence = _assess_alignment_applicability(scores, calibration)
    gate_seconds = time.perf_counter() - started
    if not gate.accepted:
        return MDLPipelineResult(
            status="rejected",
            gate=gate,
            all_ops=[],
            alternative_ops=[],
            uncertain_regions=(),
            atomic_ops=[],
            scaffold=[],
            centered=None,
            composition=None,
            alternative_composition=None,
            stats={"gate_seconds": round(gate_seconds, 6)},
        )

    if evidence is None or gate.order is None:
        raise RuntimeError("通过的统计门控缺少单调证据")
    scaffold = [
        ((source,), (target,), float(scores[source, target]))
        for source, target, _weight in gate.order.monotone_pairs
    ]
    centered_started = time.perf_counter()
    centered = align_centered_frontier_mdl(evidence, scores, scaffold)
    centered_seconds = time.perf_counter() - centered_started
    composition_started = time.perf_counter()
    composition_candidates = decision_relevant_candidates(
        centered.semantic_candidates,
        centered.all_ops,
        scores,
    )
    encoded_cache: dict[str, np.ndarray] = {}

    def cached_encode(texts: list[str]) -> np.ndarray:
        missing = [text for text in texts if text not in encoded_cache]
        if missing:
            vectors = np.asarray(encode_fn(missing), dtype=np.float64)
            if vectors.shape[0] != len(missing):
                raise ValueError("组合编码器返回的向量数与文本数不一致")
            encoded_cache.update(zip(missing, vectors))
        return np.vstack([encoded_cache[text] for text in texts])

    posterior, composition = align_counterfactual_composition_models_mdl(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        scores,
        evidence,
        composition_candidates,
        cached_encode,
    )
    composition_seconds = time.perf_counter() - composition_started
    model_disagreements = _reviewable_uncertain_regions(
        composition.alignment.all_ops,
        posterior.alignment.all_ops,
    )
    witness_started = time.perf_counter()
    provisional_ops, uncertain_regions = _resolve_hard_boundary_witnesses(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        composition.alignment.all_ops,
        posterior.alignment.all_ops,
        model_disagreements,
        cached_encode,
    )
    witness_seconds = time.perf_counter() - witness_started
    return MDLPipelineResult(
        status="needs_review" if uncertain_regions else "aligned",
        gate=gate,
        all_ops=provisional_ops,
        alternative_ops=posterior.alignment.all_ops,
        uncertain_regions=uncertain_regions,
        atomic_ops=centered.all_ops,
        scaffold=scaffold,
        centered=centered,
        composition=composition,
        alternative_composition=posterior,
        stats={
            "gate_seconds": round(gate_seconds, 6),
            "centered_seconds": round(centered_seconds, 6),
            "composition_seconds": round(composition_seconds, 6),
            "hard_boundary_witness_seconds": round(witness_seconds, 6),
            "composition_proposals_before_pruning": len(centered.semantic_candidates),
            "composition_proposals_after_pruning": len(composition_candidates),
            "composition_models": (
                "counterfactual_dld",
                "posterior_reweight",
            ),
            "composition_encoded_texts": len(encoded_cache),
            "uncertain_regions": len(uncertain_regions),
            # Kept as a zero-valued compatibility field for older reports.
            "suppressed_alternative_regions": 0,
            "composition_model_disagreement_regions": len(model_disagreements),
            "hard_boundary_witness_resolutions": len(model_disagreements)
            - len(uncertain_regions),
            "total_seconds": round(time.perf_counter() - started, 6),
        },
    )
