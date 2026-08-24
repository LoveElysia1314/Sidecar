"""Production adapter for gapless local realignment after a hard split."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from dualign.core import _smart_join_lines
from dualign.algorithms.mdl.local_recursive_mdl import (
    align_local_recursive_mdl,
    select_path_conditioned_composition,
)
from dualign.algorithms.mdl.mdl_aligner import Operation

LOCAL_REALIGN_ALIGNED = "aligned"
LOCAL_REALIGN_NEEDS_REVIEW = "needs_review"
LOCAL_REASON_COMPLEXITY_DISAGREEMENT = "complexity_disagreement"
LOCAL_REASON_COMPOSITION_TIE = "composition_tie"


@dataclass(frozen=True)
class LocalRealignmentResult:
    status: str
    reason: str
    operations: tuple[Operation, ...]
    stats: dict


def _validate_gapless_path(
    operations: list[Operation] | tuple[Operation, ...],
    source_count: int,
    target_count: int,
) -> None:
    source_cursor = 0
    target_cursor = 0
    for source, target, _score in operations:
        if not source or not target:
            raise RuntimeError("局部拆分路径不得包含 gap")
        if len(source) > 1 and len(target) > 1:
            raise RuntimeError("局部拆分路径不得包含一般 N:M")
        expected_source = tuple(range(source_cursor, source_cursor + len(source)))
        expected_target = tuple(range(target_cursor, target_cursor + len(target)))
        if tuple(source) != expected_source or tuple(target) != expected_target:
            raise RuntimeError("局部拆分路径不连续或不单调")
        source_cursor += len(source)
        target_cursor += len(target)
    if (source_cursor, target_cursor) != (source_count, target_count):
        raise RuntimeError("局部拆分路径没有完整覆盖输入")


def align_split_region(
    lines_a: list[str],
    lines_b: list[str],
    embeddings_a: np.ndarray,
    embeddings_b: np.ndarray,
    encode_fn: Callable[[list[str]], np.ndarray],
) -> LocalRealignmentResult:
    """Align one accepted parent relation under the gapless local grammar."""

    evidence = align_local_recursive_mdl(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        encode_fn,
    )
    selected = select_path_conditioned_composition(evidence)
    if selected.status != LOCAL_REALIGN_ALIGNED:
        reason = (
            LOCAL_REASON_COMPLEXITY_DISAGREEMENT
            if evidence.dld.complexity != evidence.posterior.complexity
            else LOCAL_REASON_COMPOSITION_TIE
        )
        return LocalRealignmentResult(
            LOCAL_REALIGN_NEEDS_REVIEW,
            reason,
            (),
            dict(selected.stats),
        )
    operations = tuple(selected.all_ops)
    _validate_gapless_path(operations, len(lines_a), len(lines_b))
    return LocalRealignmentResult(
        LOCAL_REALIGN_ALIGNED,
        "",
        operations,
        dict(selected.stats),
    )


def materialize_local_path(
    operations: list[Operation] | tuple[Operation, ...],
    lines_a: list[str],
    lines_b: list[str],
) -> tuple[list[str], list[str], list[float]]:
    """Flatten each semantic relation to one non-empty output row per side."""

    _validate_gapless_path(operations, len(lines_a), len(lines_b))
    output_a = []
    output_b = []
    scores = []
    for source, target, score in operations:
        output_a.append(_smart_join_lines([lines_a[index] for index in source]))
        output_b.append(_smart_join_lines([lines_b[index] for index in target]))
        scores.append(float(score))
    return output_a, output_b, scores
