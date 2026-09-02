"""Public API for the production MDL alignment algorithm."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import numpy as np

Operation = Tuple[Tuple[int, ...], Tuple[int, ...], float]

ALGORITHM_MDL_V1 = "mdl-v1"
ALIGN_CACHE_REVISION = "mdl-time-bounded-composition.9"
# Kept under the historical public name, but this is a semantic algorithm
# revision rather than the package release. Patch releases must not invalidate
# reusable alignments when their relations are unchanged.
ALIGN_CORE_VERSION = ALIGN_CACHE_REVISION


@dataclass(frozen=True)
class AlignConfig:
    """Stable marker for the parameter-free production alignment policy."""


MAXIMUM_SIMILARITY_MATRIX_CELLS = 10_000_000


@dataclass
class AlignmentResult:
    """Uniform result contract for accepted, review and abstention outcomes."""

    all_ops: List[Operation]
    stats: dict
    status: str = "aligned"
    reason: str = ""
    timing: Optional[dict] = None
    uncertain_regions: tuple = ()
    alternative_ops: Optional[List[Operation]] = None
    algorithm: str = ALGORITHM_MDL_V1


def align(
    lines_a: List[str],
    lines_b: List[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    config: AlignConfig | None = None,
    encode_fn: Optional[Callable[[List[str]], np.ndarray]] = None,
    *,
    silent: bool = False,
) -> AlignmentResult:
    """Align a document pair under the fixed production safety limits."""

    cfg = config or AlignConfig()
    if not isinstance(cfg, AlignConfig):
        raise TypeError("正式对齐 API 只接受 AlignConfig")

    if not lines_a or not lines_b:
        return AlignmentResult(
            all_ops=[],
            stats={"n_source": len(lines_a), "n_target": len(lines_b), "n_ops": 0},
            status="rejected",
            reason="empty_document",
            algorithm=ALGORITHM_MDL_V1,
        )
    if encode_fn is None:
        raise ValueError("mdl-v1 需要 encode_fn 以验证组合候选")
    matrix_cells = len(lines_a) * len(lines_b)
    if matrix_cells > MAXIMUM_SIMILARITY_MATRIX_CELLS:
        return AlignmentResult(
            all_ops=[],
            stats={
                "n_source": len(lines_a),
                "n_target": len(lines_b),
                "n_ops": 0,
                "matrix_cells": matrix_cells,
                "maximum_matrix_cells": MAXIMUM_SIMILARITY_MATRIX_CELLS,
            },
            status="rejected",
            reason="input_too_large",
            algorithm=ALGORITHM_MDL_V1,
        )

    # Lazy import keeps the public facade lightweight and avoids a core cycle.
    from dualign.algorithms.mdl import align_mdl_pipeline

    candidate = align_mdl_pipeline(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        encode_fn,
    )
    if candidate.status == "rejected":
        return AlignmentResult(
            all_ops=[],
            stats={
                "n_source": len(lines_a),
                "n_target": len(lines_b),
                "n_ops": 0,
                **candidate.stats,
            },
            status="rejected",
            reason=candidate.reason,
            timing={
                key: value
                for key, value in candidate.stats.items()
                if key.endswith("_seconds") or key == "timeout_phase"
            },
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
        stats=stats,
        status=candidate.status,
        timing={
            key: value
            for key, value in candidate.stats.items()
            if key.endswith("_seconds")
        },
        uncertain_regions=candidate.uncertain_regions,
        alternative_ops=list(candidate.alternative_ops),
        algorithm=ALGORITHM_MDL_V1,
    )


def alignment_payload(result: AlignmentResult) -> dict:
    """Serialize the decision separately from diagnostic quality indicators."""

    payload = {
        "status": result.status,
        "reason": result.reason or None,
        "algorithm": result.algorithm,
        "timing": dict(result.timing or {}),
        "uncertain_regions": [
            {
                "start": {"source": start[0], "target": start[1]},
                "end": {"source": end[0], "target": end[1]},
            }
            for start, end in result.uncertain_regions
        ],
    }
    if result.alternative_ops:
        payload["alternative_ops"] = [
            {"s": list(source), "t": list(target), "sc": round(float(score), 6)}
            for source, target, score in result.alternative_ops
        ]
    return payload
