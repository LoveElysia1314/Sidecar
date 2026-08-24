"""Post-alignment anomaly diagnostics; never an alignment applicability gate."""

from __future__ import annotations

from dataclasses import dataclass


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
