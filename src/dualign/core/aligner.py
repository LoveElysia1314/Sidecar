"""Public alignment API and algorithm selection.

``mdl-v1`` is the production algorithm.  The retired anchor implementation is
available only through the explicit ``legacy-anchor-v1`` selector; rejection
by MDL never falls back to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from dualign.version import __version__
from dualign.core.legacy_anchor_aligner import (
    LegacyAnchorConfig,
    _normalize,
    _smart_join_lines,
    bilateral_trust_margin,
    count_punct_info,
    find_bilateral_anchors,
    op_type_str,
    pair_score,
    select_monotonic_anchors_weighted,
)

Operation = Tuple[Tuple[int, ...], Tuple[int, ...], float]

ALGORITHM_MDL_V1 = "mdl-v1"
ALGORITHM_LEGACY_ANCHOR_V1 = "legacy-anchor-v1"
ALIGN_CORE_VERSION = __version__
ALIGN_CACHE_REVISION = "mdl-gated-composition.2"


@dataclass(frozen=True)
class AlignConfig:
    """Production alignment policy.

    The algorithm itself exposes no semantic thresholds.  ``calibration_id``
    selects a versioned empirical calibration tied to the embedding identity;
    an empty value asks the registry for the unique matching calibration.
    """

    algorithm: str = ALGORITHM_MDL_V1
    calibration_id: str = ""


@dataclass
class AlignmentResult:
    """Uniform result contract for accepted, review and abstention outcomes."""

    all_ops: List[Operation]
    anchors: List[Operation]
    anchor_op_indices: Dict[int, str]
    stats: dict
    sim_matrix: Optional[np.ndarray] = None
    status: str = "aligned"
    reason: str = ""
    gate: Optional[dict] = None
    uncertain_regions: tuple = ()
    alternative_ops: Optional[List[Operation]] = None
    algorithm: str = ALGORITHM_MDL_V1


def _adapt_legacy(result) -> AlignmentResult:
    return AlignmentResult(
        all_ops=list(result.all_ops),
        anchors=list(result.anchors),
        anchor_op_indices=dict(result.anchor_op_indices),
        stats=dict(result.stats),
        sim_matrix=result.sim_matrix,
        status="aligned",
        algorithm=ALGORITHM_LEGACY_ANCHOR_V1,
    )


def _gate_payload(gate) -> dict:
    order = gate.order
    return {
        "existence_score": float(gate.existence_score),
        "existence_p": float(gate.existence_p),
        "order_compatibility_p": float(gate.order_compatibility_p),
        "mutual_pairs": int(order.mutual_pairs),
        "out_of_chain_pairs": int(order.out_of_chain_pairs),
        "longest_chain_pairs": int(order.chain_length),
    }


def align(
    lines_a: List[str],
    lines_b: List[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    config: AlignConfig | LegacyAnchorConfig | None = None,
    encode_fn: Optional[Callable[[List[str]], np.ndarray]] = None,
    *,
    calibration=None,
    silent: bool = False,
) -> AlignmentResult:
    """Align a document pair using the selected algorithm.

    ``legacy-anchor-v1`` must be selected explicitly.  ``mdl-v1`` abstains
    when calibration is absent or the statistical applicability gate rejects
    the pair; it never manufactures a legacy result as a fallback.
    """

    cfg = config or AlignConfig()
    if isinstance(cfg, LegacyAnchorConfig):
        algorithm = ALGORITHM_LEGACY_ANCHOR_V1
    else:
        algorithm = cfg.algorithm

    if algorithm == ALGORITHM_LEGACY_ANCHOR_V1:
        from dualign.core.legacy_anchor_aligner import align as legacy_align

        legacy_cfg = (
            cfg if isinstance(cfg, LegacyAnchorConfig) else LegacyAnchorConfig()
        )
        return _adapt_legacy(
            legacy_align(
                lines_a,
                lines_b,
                embeddings_a,
                embeddings_b,
                legacy_cfg,
                encode_fn=encode_fn,
                silent=silent,
            )
        )
    if algorithm != ALGORITHM_MDL_V1:
        raise ValueError(f"未知对齐算法: {algorithm}")

    if not lines_a or not lines_b:
        return AlignmentResult(
            all_ops=[],
            anchors=[],
            anchor_op_indices={},
            stats={"n_source": len(lines_a), "n_target": len(lines_b), "n_ops": 0},
            status="rejected",
            reason="empty_document",
            algorithm=ALGORITHM_MDL_V1,
        )
    if calibration is None:
        return AlignmentResult(
            all_ops=[],
            anchors=[],
            anchor_op_indices={},
            stats={"n_source": len(lines_a), "n_target": len(lines_b), "n_ops": 0},
            status="rejected",
            reason="calibration_unavailable",
            algorithm=ALGORITHM_MDL_V1,
        )
    if encode_fn is None:
        raise ValueError("mdl-v1 需要 encode_fn 以验证组合候选")

    # Lazy import keeps the public facade lightweight and avoids a core cycle.
    from dualign.algorithms.mdl import align_mdl_pipeline

    candidate = align_mdl_pipeline(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        encode_fn,
        calibration,
    )
    gate = _gate_payload(candidate.gate)
    if candidate.status.startswith("rejected_"):
        return AlignmentResult(
            all_ops=[],
            anchors=[],
            anchor_op_indices={},
            stats={
                "n_source": len(lines_a),
                "n_target": len(lines_b),
                "n_ops": 0,
                **candidate.stats,
            },
            status="rejected",
            reason=candidate.status.removeprefix("rejected_"),
            gate=gate,
            algorithm=ALGORITHM_MDL_V1,
        )

    operations = list(candidate.all_ops)
    similarities = [score for source, target, score in operations if source and target]
    stats = {
        "n_source": len(lines_a),
        "n_target": len(lines_b),
        "n_ops": len(operations),
        "n_scaffold": len(candidate.scaffold),
        "avg_similarity": float(np.mean(similarities)) if similarities else 0.0,
        **candidate.stats,
    }
    return AlignmentResult(
        all_ops=operations,
        anchors=list(candidate.scaffold),
        anchor_op_indices={},
        stats=stats,
        status=candidate.status,
        gate=gate,
        uncertain_regions=candidate.uncertain_regions,
        alternative_ops=list(candidate.alternative_ops),
        algorithm=ALGORITHM_MDL_V1,
    )


def alignment_payload(result: AlignmentResult, *, calibration_id: str = "") -> dict:
    """Serialize the decision separately from diagnostic quality indicators."""

    payload = {
        "status": result.status,
        "reason": result.reason or None,
        "algorithm": result.algorithm,
        "gate": dict(result.gate or {}),
        "uncertain_regions": [
            {
                "start": {"source": start[0], "target": start[1]},
                "end": {"source": end[0], "target": end[1]},
            }
            for start, end in result.uncertain_regions
        ],
    }
    if calibration_id:
        payload["calibration_id"] = calibration_id
    if result.alternative_ops:
        payload["alternative_ops"] = [
            {"s": list(source), "t": list(target), "sc": round(float(score), 6)}
            for source, target, score in result.alternative_ops
        ]
    return payload
