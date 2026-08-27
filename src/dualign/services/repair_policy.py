"""Deterministic repair policy shared by auto-repair, AI review, and the GUI."""

from __future__ import annotations

from dataclasses import dataclass

VALID_REPAIR_STRATEGIES = frozenset({"minimal", "src", "tgt"})


@dataclass(frozen=True)
class AutoRepairPlan:
    kind: str
    side: str = ""

    @property
    def may_require_model(self) -> bool:
        """Whether boundary expansion may need semantic path selection."""

        return self.kind == "split"


def strategy_for_ai_review(strategy: str) -> str:
    """Validate and preserve the repair policy selected for AI review."""
    if strategy not in VALID_REPAIR_STRATEGIES:
        raise ValueError(f"未知对齐策略: {strategy}")
    return strategy


def choose_auto_repair(n_src: int, n_tgt: int, strategy: str) -> AutoRepairPlan | None:
    """Return the strategy-matrix normalization plan for one original relation.

    ``None`` means preserve the native relation. In particular, N:M has no
    deterministic normalization: choosing a side there requires semantic review.
    A split plan expresses the preferred side for boundary expansion; applying it
    may naturally produce a merge when no new boundary exists and the complete
    gapless path is unique.
    """
    if strategy not in VALID_REPAIR_STRATEGIES:
        raise ValueError(f"未知对齐策略: {strategy}")
    if n_src == 1 and n_tgt == 1:
        return None
    if n_src > 1 and n_tgt == 1:
        return (
            AutoRepairPlan("split", "tgt")
            if strategy == "src"
            else AutoRepairPlan("merge")
        )
    if n_src == 1 and n_tgt > 1:
        return (
            AutoRepairPlan("split", "src")
            if strategy == "tgt"
            else AutoRepairPlan("merge")
        )
    if n_src > 0 and n_tgt == 0:
        return (
            AutoRepairPlan("placeholder_tgt")
            if strategy in {"src", "minimal"}
            else AutoRepairPlan("delete")
        )
    if n_src == 0 and n_tgt > 0:
        return (
            AutoRepairPlan("placeholder_src")
            if strategy in {"tgt", "minimal"}
            else AutoRepairPlan("delete")
        )
    return None
