"""Frozen quality diagnostics for the archived anchor aligner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityGateConfig:
    """Thresholds retained only for explicit legacy reports and benchmarks."""

    anchor_density_min: float = 0.60
    gap_row_ratio_max: float = 0.10
    zscore_k: float = 3.0
    zscore_min_score: float = 0.6


QUALITY_OK = "ok"
QUALITY_UNRELIABLE = "unreliable"
QUALITY_GAP_DOMINATED = "gap_dominated"

REJECTION_LOW_ANCHOR_DENSITY = "low_anchor_density"
REJECTION_GAP_DOMINATED = "gap_dominated"
REJECTION_MERGE_OVERFLOW = "merge_overflow"


def _gap_row_ratio(all_ops, n_src: int, n_tgt: int) -> float:
    """Return the fraction of source and target rows assigned to gaps."""

    n_orphan = sum(len(source) for source, target, _ in all_ops if not target) + sum(
        len(target) for source, target, _ in all_ops if not source
    )
    denominator = n_src + n_tgt
    return n_orphan / denominator if denominator > 0 else 0.0


def assess_alignment_quality(
    stats: dict,
    n_src: int,
    n_tgt: int,
    gap_row_ratio: float,
    n_overflow_rows: int = 0,
    config: QualityGateConfig | None = None,
) -> dict:
    """Reproduce the archived G1/G2/G3 report classification."""

    cfg = config or QualityGateConfig()
    anchor_density = stats.get("anchor_density")
    if anchor_density is None:
        n_true = stats.get("n_true_anchors", 0)
        n_total = n_src + n_tgt
        anchor_density = 2 * n_true / n_total if n_total > 0 else 0.0

    indicators = {
        "anchor_density": round(anchor_density, 4),
        "gap_row_ratio": round(gap_row_ratio, 4),
        "n_overflow_rows": n_overflow_rows,
        "n_src": n_src,
        "n_tgt": n_tgt,
    }
    rejections = []
    if anchor_density < cfg.anchor_density_min:
        rejections.append(REJECTION_LOW_ANCHOR_DENSITY)
    if gap_row_ratio >= cfg.gap_row_ratio_max:
        rejections.append(REJECTION_GAP_DOMINATED)
    if n_overflow_rows > 0:
        rejections.append(REJECTION_MERGE_OVERFLOW)

    if REJECTION_LOW_ANCHOR_DENSITY in rejections:
        quality = QUALITY_UNRELIABLE
    elif REJECTION_GAP_DOMINATED in rejections:
        quality = QUALITY_GAP_DOMINATED
    else:
        quality = QUALITY_OK
    return {
        "quality": quality,
        "rejections": rejections,
        "indicators": indicators,
    }


def automatic_repair_blockers(assessment: dict | None) -> list[str]:
    """Return archived structural risks that block automatic repair."""

    if not assessment:
        return []
    known = {
        REJECTION_LOW_ANCHOR_DENSITY,
        REJECTION_GAP_DOMINATED,
        REJECTION_MERGE_OVERFLOW,
    }
    return [reason for reason in assessment.get("rejections", []) if reason in known]
