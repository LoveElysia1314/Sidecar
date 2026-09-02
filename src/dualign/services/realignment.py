"""Fresh alignment of an in-memory natural document pair."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from dualign.config import get_embedding_cache_path
from dualign.core import (
    AlignConfig,
    align,
    alignment_payload,
)
from dualign.core.calibration import resolve_alignment_calibration
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.embedding import _try_lazy_load_model
from dualign.services.embedding_cache import EmbeddingCache

Operation = tuple[tuple[int, ...], tuple[int, ...], float]


@dataclass(frozen=True)
class RebuiltAlignment:
    operations: tuple[Operation, ...]
    stats: dict
    quality: dict
    provenance: dict
    alignment: dict = field(default_factory=dict)


def rebuild_alignment(
    document_a: list[str],
    document_b: list[str],
    *,
    config: AlignConfig | None = None,
) -> RebuiltAlignment:
    """Run the production aligner over future document contents without I/O."""

    cfg = config or AlignConfig()
    model = _try_lazy_load_model()
    if model is None:
        raise RuntimeError("无法加载嵌入模型，不能重建固化后的对齐关系")

    resolved = resolve_alignment_calibration(model, calibration_id=cfg.calibration_id)
    if document_a and document_b:
        with EmbeddingCache(get_embedding_cache_path()) as cache:
            encoder = CachedEncoder(model, cache)
            result = align(
                document_a,
                document_b,
                encoder.encode(document_a),
                encoder.encode(document_b),
                cfg,
                encode_fn=encoder.encode,
                calibration=resolved.calibration if resolved is not None else None,
                silent=True,
            )
        operations = tuple(result.all_ops)
        stats = dict(result.stats or {})
    else:
        result = align(
            document_a,
            document_b,
            np.empty((len(document_a), 0)),
            np.empty((len(document_b), 0)),
            cfg,
        )
        operations = tuple(result.all_ops)
        stats = dict(result.stats or {})

    if result.status == "rejected":
        raise RuntimeError(f"新文本对齐被拒绝: {result.reason}")

    quality = {
        "level": "diagnostic_only",
        "rejections": [],
        "indicators": {"alignment_status": result.status},
    }
    from dualign.services.cli_pipeline import _provenance

    return RebuiltAlignment(
        operations=operations,
        stats=stats,
        quality=quality,
        provenance=_provenance(
            model, cfg, resolved.calibration_id if resolved is not None else ""
        ),
        alignment=alignment_payload(
            result,
            calibration_id=resolved.calibration_id if resolved is not None else "",
        ),
    )
