"""Production pipeline for statistically gated sparse-MDL alignment."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from dualign.algorithms.mdl.composition_mdl import (
    CounterfactualCompositionResult,
    align_counterfactual_composition_mdl,
    decision_relevant_candidates,
)
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
    MonotoneOrderEvidence,
    beta_binomial_upper_p,
    conformal_upper_p,
    fit_beta_binomial_order_model,
    monotone_order_evidence,
    mutual_monotone_chain,
    symmetric_nearest_score,
)


@dataclass(frozen=True)
class AlignmentCalibration:
    """Two empirical reference sets and one declared error rate."""

    existence_null: np.ndarray
    parallel_order_counts: np.ndarray
    alpha: float


@dataclass(frozen=True)
class AlignmentGateDecision:
    status: str
    existence_score: float
    existence_p: float
    order: MonotoneOrderEvidence
    order_compatibility_p: float

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


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
    evidence: np.ndarray,
    calibration: AlignmentCalibration,
) -> AlignmentGateDecision:
    """Test correspondence, then compatibility with calibrated parallel order."""

    if not 0.0 < calibration.alpha < 1.0:
        raise ValueError("显著性水平 alpha 必须位于 (0, 1)")
    existence_score = symmetric_nearest_score(scores)
    existence_p = conformal_upper_p(existence_score, calibration.existence_null)
    order = monotone_order_evidence(scores, evidence)
    order_alpha, order_beta = fit_beta_binomial_order_model(
        calibration.parallel_order_counts
    )
    order_compatibility_p = (
        beta_binomial_upper_p(
            order.out_of_chain_pairs,
            order.mutual_pairs,
            order_alpha,
            order_beta,
        )
        if order.mutual_pairs
        else 0.0
    )
    if existence_p > calibration.alpha:
        status = "rejected_no_correspondence"
    elif not order.mutual_pairs:
        status = "rejected_order_unidentifiable"
    elif order_compatibility_p <= calibration.alpha:
        status = "rejected_order_incompatible"
    else:
        status = "accepted"
    return AlignmentGateDecision(
        status=status,
        existence_score=existence_score,
        existence_p=existence_p,
        order=order,
        order_compatibility_p=order_compatibility_p,
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
    regions = []
    region_start = None
    for start, end in zip(shared, shared[1:]):

        def signature(edges):
            return tuple(
                (source, target)
                for edge_start, edge_end, source, target in edges
                if edge_start[0] >= start[0]
                and edge_start[1] >= start[1]
                and edge_end[0] <= end[0]
                and edge_end[1] <= end[1]
            )

        agrees = signature(first_edges) == signature(second_edges)
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

    scores = np.dot(source_vectors, target_vectors.T)
    evidence = mutual_rank_code_evidence(scores)
    gate = assess_alignment_applicability(scores, evidence, calibration)
    gate_seconds = time.perf_counter() - started
    if not gate.accepted:
        return MDLPipelineResult(
            status=gate.status,
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

    chain = mutual_monotone_chain(scores, evidence)
    scaffold = [
        ((source,), (target,), float(scores[source, target]))
        for source, target, _weight in chain
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

    posterior = align_counterfactual_composition_mdl(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        scores,
        evidence,
        composition_candidates,
        cached_encode,
        evidence_model="posterior_reweight",
    )
    composition = align_counterfactual_composition_mdl(
        lines_a,
        lines_b,
        source_vectors,
        target_vectors,
        scores,
        evidence,
        composition_candidates,
        cached_encode,
        evidence_model="counterfactual_dld",
    )
    composition_seconds = time.perf_counter() - composition_started
    uncertain_regions = _reviewable_uncertain_regions(
        composition.alignment.all_ops,
        posterior.alignment.all_ops,
    )
    return MDLPipelineResult(
        status="needs_review" if uncertain_regions else "aligned",
        gate=gate,
        all_ops=composition.alignment.all_ops,
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
            "composition_model_disagreement_regions": len(uncertain_regions),
            "total_seconds": round(time.perf_counter() - started, 6),
        },
    )
