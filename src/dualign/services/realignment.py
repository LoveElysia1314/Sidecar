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
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.cancellation import CancellationToken
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
    cancellation_token: CancellationToken | None = None,
) -> RebuiltAlignment:
    """Run the production aligner over future document contents without I/O."""

    cfg = config or AlignConfig()
    token = cancellation_token
    if token is not None:
        token.raise_if_cancelled()
    model = _try_lazy_load_model()
    if model is None:
        raise RuntimeError("无法加载嵌入模型，不能重建固化后的对齐关系")

    if document_a and document_b:
        with EmbeddingCache(get_embedding_cache_path()) as cache:
            encoder = CachedEncoder(model, cache)
            try:
                source_embeddings = encoder.encode(
                    document_a,
                    stop_event=token.event if token is not None else None,
                )
            except Exception:
                if token is not None:
                    token.raise_if_cancelled()
                raise
            if token is not None:
                token.raise_if_cancelled()
            try:
                target_embeddings = encoder.encode(
                    document_b,
                    stop_event=token.event if token is not None else None,
                )
            except Exception:
                if token is not None:
                    token.raise_if_cancelled()
                raise
            if token is not None:
                token.raise_if_cancelled()
            result = align(
                document_a,
                document_b,
                source_embeddings,
                target_embeddings,
                cfg,
                encode_fn=encoder.encode,
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

    if token is not None:
        token.raise_if_cancelled()

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
        provenance=_provenance(model, cfg),
        alignment=alignment_payload(result),
    )
