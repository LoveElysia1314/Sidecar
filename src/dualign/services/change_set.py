"""Reviewable change sets between a formal pair baseline and GUI work state."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

from dualign.models.action import RepairAction
from dualign.models.pair_editing import PairEditingState
from dualign.services._text_diff import unified_text_diff
from dualign.services.pair_editing_adapter import apply_repair_log_to_pair_state

CONTENT_ACTION_KINDS = frozenset({"edit", "split"})
RELATION_ACTION_KINDS = frozenset({"ok", "delete"})
LEGACY_ONLY_ACTION_KINDS = frozenset(
    {"merge", "placeholder_src", "placeholder_tgt", "flag"}
)


@dataclass(frozen=True)
class PairChangeSet:
    """Computed work state plus the evidence required before solidification."""

    baseline: PairEditingState
    working: PairEditingState
    actions: tuple[RepairAction, ...]
    content_action_count: int
    relation_action_count: int
    legacy_only_action_count: int

    @property
    def document_a_changed(self) -> bool:
        return (
            self.baseline.document_a.render_text()
            != self.working.document_a.render_text()
        )

    @property
    def document_b_changed(self) -> bool:
        return (
            self.baseline.document_b.render_text()
            != self.working.document_b.render_text()
        )

    @property
    def has_content_changes(self) -> bool:
        return self.document_a_changed or self.document_b_changed

    @property
    def relation_changed(self) -> bool:
        return (
            self.baseline.to_alignment_pair().links
            != self.working.to_alignment_pair().links
        )

    @property
    def can_apply(self) -> bool:
        return self.has_content_changes

    @property
    def has_changes(self) -> bool:
        return self.has_content_changes or self.relation_changed

    def document_a_diff(self) -> str:
        return unified_text_diff(
            self.baseline.document_a.render_text(),
            self.working.document_a.render_text(),
            "文档 A（当前磁盘）",
            "文档 A（待应用）",
        )

    def document_b_diff(self) -> str:
        return unified_text_diff(
            self.baseline.document_b.render_text(),
            self.working.document_b.render_text(),
            "文档 B（当前磁盘）",
            "文档 B（待应用）",
        )

    def relation_diff(self) -> str:
        def describe(state: PairEditingState) -> str:
            links = [
                {
                    "id": link.id,
                    "document_a": list(link.document_a),
                    "document_b": list(link.document_b),
                    "state": link.state,
                    "confidence": link.confidence,
                }
                for link in state.to_alignment_pair().links
            ]
            return json.dumps(links, ensure_ascii=False, indent=2) + "\n"

        return unified_text_diff(
            describe(self.baseline),
            describe(self.working),
            "对齐关系（基线）",
            "对齐关系（待保存）",
        )


def build_pair_change_set(
    baseline: PairEditingState, repair_log: Iterable[RepairAction]
) -> PairChangeSet:
    """Replay recovery actions and derive the work-state change set.

    Pending AI proposals are not in ``repair_log`` and therefore correctly
    do not count as accepted changes.
    """

    actions = tuple(repair_log)
    content_count = relation_count = legacy_count = 0
    for action in actions:
        if action.kind in CONTENT_ACTION_KINDS:
            content_count += 1
        elif action.kind in RELATION_ACTION_KINDS:
            relation_count += 1
        elif action.kind in LEGACY_ONLY_ACTION_KINDS:
            legacy_count += 1

    working = apply_repair_log_to_pair_state(baseline, actions)
    return PairChangeSet(
        baseline=baseline,
        working=working,
        actions=actions,
        content_action_count=content_count,
        relation_action_count=relation_count,
        legacy_only_action_count=legacy_count,
    )
