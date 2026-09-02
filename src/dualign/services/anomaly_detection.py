"""Post-alignment anomaly diagnostics; never an alignment applicability gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class AnomalyDetectionConfig:
    zscore_k: float = 3.0
    zscore_min_score: float = 0.6


def is_statistical_low_score(
    score: float,
    scores_1to1: list,
    k: float = 3.0,
    min_score: float = 0.6,
) -> bool:
    """Flag a low tail observation, subject to an absolute diagnostic floor."""

    if len(scores_1to1) < 3 or score >= min_score:
        return False
    import numpy as np

    mu = float(np.mean(scores_1to1))
    sigma = float(np.std(scores_1to1, ddof=1))
    if sigma < 1e-8:
        return False
    return (mu - score) / sigma > k


def baseline_anomaly_types(
    operations: Iterable,
    target_lines: Sequence[str],
    config: AnomalyDetectionConfig | None = None,
) -> tuple[frozenset[str], ...]:
    """Freeze post-alignment diagnostics for one immutable report baseline."""

    from dualign.core import detect_language_mix

    cfg = config or AnomalyDetectionConfig()
    operation_list = list(operations)
    scores_1to1 = [
        float(score)
        for source, target, score in operation_list
        if len(source) == len(target) == 1
    ]
    result: list[frozenset[str]] = []
    for source, target, score in operation_list:
        labels: set[str] = set()
        if len(source) != 1 or len(target) != 1:
            labels.add("NON_1TO1")
        target_text = "\n".join(target_lines[index] for index in target)
        if target_text.strip() and detect_language_mix(target_text):
            labels.add("MIX")
        if len(source) == len(target) == 1 and is_statistical_low_score(
            float(score),
            scores_1to1,
            k=cfg.zscore_k,
            min_score=cfg.zscore_min_score,
        ):
            labels.add("LOW_SCORE")
        result.append(frozenset(labels))
    return tuple(result)
