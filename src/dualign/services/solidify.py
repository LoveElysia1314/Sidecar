"""Selective solidification of report-backed edits into natural documents.

Solidification is deliberately separate from saving a work report.  A policy
chooses which effects become the new document baseline; unselected effects are
rebased onto the rebuilt alignment snapshot and remain in ``repair_log``.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

from dualign.common import file_bytes_sha256
from dualign.core import _smart_join_lines
from dualign.models.action import RepairAction, project_action_to_relation_order
from dualign.models.pair_editing import PairEditingState
from dualign.services._text_diff import unified_text_diff
from dualign.services.alignment_io import create_alignment_pair
from dualign.services.pair_save import (
    PairSaveError,
    PairSaveResult,
    save_pair_transaction,
)
from dualign.services.repair import normalize_repair_log
from dualign.services.report_io import (
    ReportError,
    load_report,
    operations_from_report,
    relation_ids_from_report,
    report_matches_documents,
)

SOLIDIFY_TYPES = (
    "merge_a",
    "split_a",
    "edit_a",
    "merge_b",
    "split_b",
    "edit_b",
    "delete_pair",
)

SOLIDIFY_TYPE_LABELS = {
    "merge_a": "文档 A 合并",
    "split_a": "文档 A 拆分",
    "edit_a": "文档 A 校订",
    "merge_b": "文档 B 合并",
    "split_b": "文档 B 拆分",
    "edit_b": "文档 B 校订",
    "delete_pair": "删除文本对（双侧）",
}

SOLIDIFY_PRESETS = {
    "edits": frozenset({"edit_a", "edit_b"}),
    "line-aligned": frozenset(SOLIDIFY_TYPES),
    "document-a": frozenset({"merge_a", "split_a", "edit_a"}),
    "document-b": frozenset({"merge_b", "split_b", "edit_b"}),
    "none": frozenset(),
}

# 出厂默认：仅校订（双侧）+ 译文拆分。原文重组/删除等破坏性效果需用户显式启用。
DEFAULT_SOLIDIFY_TYPES = frozenset({"edit_a", "edit_b", "split_b"})


@dataclass(frozen=True)
class SolidifyPolicy:
    """The independently selectable effects that may change documents."""

    enabled: frozenset[str]

    def __post_init__(self) -> None:
        unknown = set(self.enabled) - set(SOLIDIFY_TYPES)
        if unknown:
            raise ValueError("未知固化类型: " + "、".join(sorted(unknown)))

    @classmethod
    def from_preset(cls, name: str) -> "SolidifyPolicy":
        try:
            return cls(SOLIDIFY_PRESETS[name])
        except KeyError as exc:
            raise ValueError(f"未知固化预设: {name}") from exc

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SolidifyPolicy":
        preset = str(value.get("preset") or "none")
        enabled = set(cls.from_preset(preset).enabled)
        include = value.get("include", ())
        exclude = value.get("exclude", ())
        if isinstance(include, str) or isinstance(exclude, str):
            raise ValueError("include/exclude 必须是字符串数组")
        enabled.update(str(item) for item in include or ())
        enabled.difference_update(str(item) for item in exclude or ())
        return cls(frozenset(enabled))

    def includes(self, effect: str) -> bool:
        return effect in self.enabled

    def to_dict(self) -> dict[str, list[str]]:
        return {"include": [key for key in SOLIDIFY_TYPES if key in self.enabled]}


def load_solidify_policy(path: str | Path) -> SolidifyPolicy:
    """Load a JSON or TOML policy file."""

    source = Path(path)
    if source.suffix.lower() == ".toml":
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    elif source.suffix.lower() == ".json":
        data = json.loads(source.read_text(encoding="utf-8"))
    else:
        raise ValueError("固化配置仅支持 .toml 或 .json")
    if not isinstance(data, dict):
        raise ValueError("固化配置必须是对象/表")
    if isinstance(data.get("solidify"), dict):
        data = data["solidify"]
    return SolidifyPolicy.from_mapping(data)


def _action_copy(
    action: RepairAction,
    *,
    ordinal: int,
    data: Mapping[str, object] | None = None,
    operation_indices: tuple[int, ...] | None = None,
    relation_ids: tuple[str, ...] | None = None,
) -> RepairAction:
    return RepairAction(
        kind=action.kind,
        sub_count=action.sub_count,
        source=action.source,
        data=dict(action.data if data is None else data),
        timestamp=action.timestamp,
        relation_ids=action.relation_ids if relation_ids is None else relation_ids,
        operation_indices=(
            (ordinal,) if operation_indices is None else operation_indices
        ),
    )


def _action_operations(action: RepairAction) -> tuple[int, ...]:
    return action.operation_indices


def _ordered_block_ids(state: PairEditingState, link_ids: Iterable[str], side: str):
    selected_links = {link_id for link_id in link_ids}
    values = {
        block_id
        for link in state.links
        if link.id in selected_links
        for block_id in (link.document_a if side == "a" else link.document_b)
    }
    document = state.document_a if side == "a" else state.document_b
    return tuple(block_id for block_id in document.block_ids if block_id in values)


def _block_texts(state: PairEditingState, block_ids: Iterable[str], side: str):
    document = state.document_a if side == "a" else state.document_b
    by_id = dict(zip(document.block_ids, document.blocks))
    return [by_id[block_id] for block_id in block_ids]


def _replacement_count(values: object) -> int:
    """Count non-empty physical blocks using EditableDocument semantics."""

    if not isinstance(values, (list, tuple)):
        return 0
    return sum(
        1
        for value in values
        if isinstance(value, str)
        for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    )


@dataclass(frozen=True)
class SolidificationPlan:
    baseline: PairEditingState
    solidified: PairEditingState
    policy: SolidifyPolicy
    original_actions: tuple[RepairAction, ...]
    remaining_actions: tuple[RepairAction, ...]
    applied: tuple[dict, ...]
    changed_relation_ids: frozenset[str]

    @property
    def document_a_changed(self) -> bool:
        return (
            self.baseline.document_a.render_text()
            != self.solidified.document_a.render_text()
        )

    @property
    def document_b_changed(self) -> bool:
        return (
            self.baseline.document_b.render_text()
            != self.solidified.document_b.render_text()
        )

    @property
    def has_changes(self) -> bool:
        return self.document_a_changed or self.document_b_changed

    def document_a_diff(self) -> str:
        return unified_text_diff(
            self.baseline.document_a.render_text(),
            self.solidified.document_a.render_text(),
            "文档 A（当前）",
            "文档 A（固化后）",
        )

    def document_b_diff(self) -> str:
        return unified_text_diff(
            self.baseline.document_b.render_text(),
            self.solidified.document_b.render_text(),
            "文档 B（当前）",
            "文档 B（固化后）",
        )


@dataclass(frozen=True)
class SolidifyTarget:
    """One document pair addressable by GUI integrations and the batch CLI."""

    label: str
    document_a_path: str
    document_b_path: str
    report_path: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SolidifyTarget":
        if not isinstance(value, Mapping):
            raise ValueError("批量固化清单中的条目必须是对象")
        path_a = str(value.get("document_a_path") or "")
        path_b = str(value.get("document_b_path") or "")
        report = str(value.get("report_path") or value.get("alignment_path") or "")
        if not path_a or not path_b or not report:
            raise ValueError(
                "批量固化条目缺少 document_a_path/document_b_path/report_path"
            )
        return cls(
            label=str(value.get("label") or Path(path_a).name),
            document_a_path=path_a,
            document_b_path=path_b,
            report_path=report,
        )


@dataclass(frozen=True)
class BatchSolidificationItem:
    target: SolidifyTarget
    plan: SolidificationPlan
    report: dict
    report_sha256: str


@dataclass(frozen=True)
class BatchSolidificationIssue:
    target: SolidifyTarget
    reason: str
    error: bool = False


@dataclass(frozen=True)
class BatchSolidificationPlan:
    policy: SolidifyPolicy
    ready: tuple[BatchSolidificationItem, ...]
    skipped: tuple[BatchSolidificationIssue, ...]

    @property
    def action_count(self) -> int:
        return sum(len(item.plan.applied) for item in self.ready)

    @property
    def document_a_count(self) -> int:
        return sum(item.plan.document_a_changed for item in self.ready)

    @property
    def document_b_count(self) -> int:
        return sum(item.plan.document_b_changed for item in self.ready)

    @property
    def effect_counts(self) -> dict[str, int]:
        counts = {key: 0 for key in SOLIDIFY_TYPES}
        for item in self.ready:
            for applied in item.plan.applied:
                for effect in applied.get("effects", ()):
                    if effect in counts:
                        counts[effect] += 1
        return counts


@dataclass(frozen=True)
class BatchSolidificationResult:
    succeeded: tuple[SolidifyTarget, ...]
    failed: tuple[BatchSolidificationIssue, ...]
    skipped: tuple[BatchSolidificationIssue, ...]


@dataclass(frozen=True)
class _PendingAction:
    action: RepairAction
    link_ids: tuple[str, ...]


def build_solidification_plan(
    baseline: PairEditingState,
    repair_log: Iterable[RepairAction],
    policy: SolidifyPolicy,
) -> SolidificationPlan:
    """Apply selected effects and re-anchor everything that remains."""

    state = baseline

    def bind_action(action: RepairAction) -> RepairAction:
        return project_action_to_relation_order(
            action, tuple(link.id for link in baseline.links)
        )

    actions = tuple(normalize_repair_log(bind_action(action) for action in repair_log))
    old_to_link = {index: link.id for index, link in enumerate(state.links)}
    pending: list[_PendingAction] = []
    applied: list[dict] = []

    def links_for(action: RepairAction) -> tuple[str, ...]:
        result: list[str] = []
        for operation in _action_operations(action):
            link_id = old_to_link.get(operation)
            if link_id and link_id not in result:
                result.append(link_id)
        return tuple(result)

    def merge_links(link_ids: tuple[str, ...], operations: tuple[int, ...]) -> str:
        nonlocal state
        available = {link.id for link in state.links}
        existing = tuple(link_id for link_id in link_ids if link_id in available)
        if not existing:
            raise ValueError("固化操作引用的对齐关系已不存在")
        anchor = existing[0]
        if len(existing) > 1:
            state = state.merge_links(existing)
        for operation in operations:
            old_to_link[operation] = anchor
        return anchor

    for action in actions:
        operations = _action_operations(action)
        link_ids = links_for(action)
        if not link_ids:
            continue

        if action.kind == "merge":
            ids_a = _ordered_block_ids(state, link_ids, "a")
            ids_b = _ordered_block_ids(state, link_ids, "b")
            effects = {
                side: f"merge_{side}"
                for side, ids in (("a", ids_a), ("b", ids_b))
                if len(ids) > 1
            }
            selected = {
                side for side, effect in effects.items() if policy.includes(effect)
            }
            # An N:M structural merge is one semantic decision.  Applying only
            # one side would silently turn it into a different operation.
            if set(effects) == {"a", "b"} and selected != {"a", "b"}:
                pending.append(_PendingAction(action, link_ids))
                continue
            if not selected:
                pending.append(_PendingAction(action, link_ids))
                continue
            anchor = merge_links(link_ids, operations)
            kwargs = {}
            if "a" in selected:
                kwargs["document_a"] = [
                    _smart_join_lines(_block_texts(state, ids_a, "a"))
                ]
            if "b" in selected:
                kwargs["document_b"] = [
                    _smart_join_lines(_block_texts(state, ids_b, "b"))
                ]
            state = state.edit_link_content(anchor, **kwargs)
            applied.append(
                {
                    "action": action.to_dict(),
                    "effects": sorted(effects[s] for s in selected),
                }
            )
            remaining_sides = set(effects) - selected
            if remaining_sides:
                residual = _action_copy(action, ordinal=0, data={})
                pending.append(_PendingAction(residual, (anchor,)))
            continue

        if action.kind == "split":
            raw_side = str(action.data.get("side") or "")
            ids_by_side = {
                "a": _ordered_block_ids(state, link_ids, "a"),
                "b": _ordered_block_ids(state, link_ids, "b"),
            }
            keys = {"a": "new_src_lines", "b": "new_tgt_lines"}
            affected = {
                side
                for side in ("a", "b")
                if _replacement_count(action.data.get(keys[side]))
                > len(ids_by_side[side])
            }
            if not affected:
                affected = {"a" if raw_side in {"a", "src", "source"} else "b"}
            selected = {side for side in affected if policy.includes(f"split_{side}")}
            # As with merge, a two-sided structural split must be committed as
            # a unit or remain completely represented by the repair action.
            if selected != affected:
                pending.append(_PendingAction(action, link_ids))
                continue
            anchor = merge_links(link_ids, operations)
            kwargs = {
                "document_a" if side == "a" else "document_b": list(
                    action.data.get(keys[side]) or ()
                )
                for side in affected
            }
            state = state.edit_link_content(anchor, **kwargs)
            applied.append(
                {
                    "action": action.to_dict(),
                    "effects": sorted(f"split_{side}" for side in affected),
                }
            )
            continue

        if action.kind == "edit":
            candidates = {
                "a": ("edit_a", "new_src_lines", "document_a"),
                "b": ("edit_b", "new_tgt_lines", "document_b"),
            }
            present = {
                side
                for side, (_effect, key, _argument) in candidates.items()
                if action.data.get(key)
            }
            selected = {
                side for side in present if policy.includes(candidates[side][0])
            }
            if not selected:
                pending.append(_PendingAction(action, link_ids))
                continue
            anchor = merge_links(link_ids, operations)
            kwargs = {
                candidates[side][2]: list(action.data.get(candidates[side][1]) or ())
                for side in selected
            }
            state = state.edit_link_content(anchor, **kwargs)
            applied.append(
                {
                    "action": action.to_dict(),
                    "effects": sorted(candidates[s][0] for s in selected),
                }
            )
            remaining_sides = present - selected
            if remaining_sides:
                data = {
                    key: value
                    for key, value in action.data.items()
                    if key not in {"new_src_lines", "new_tgt_lines"}
                }
                for side in remaining_sides:
                    key = candidates[side][1]
                    data[key] = action.data[key]
                pending.append(
                    _PendingAction(
                        _action_copy(action, ordinal=0, data=data), (anchor,)
                    )
                )
            continue

        if action.kind == "delete":
            if not policy.includes("delete_pair"):
                pending.append(_PendingAction(action, link_ids))
                continue
            anchor = merge_links(link_ids, operations)
            state = state.delete_link_content(anchor)
            applied.append({"action": action.to_dict(), "effects": ["delete_pair"]})
            continue

        pending.append(_PendingAction(action, link_ids))

    final_positions = {link.id: index for index, link in enumerate(state.links)}
    remaining: list[RepairAction] = []
    for item in pending:
        positions: list[int] = []
        for link_id in item.link_ids:
            position = final_positions.get(link_id)
            if position is not None and position not in positions:
                positions.append(position)
        if not positions:
            continue
        surviving_ids = tuple(
            link_id for link_id in item.link_ids if link_id in final_positions
        )
        remaining.append(
            _action_copy(
                item.action,
                ordinal=positions[0],
                operation_indices=tuple(positions),
                relation_ids=surviving_ids,
            )
        )

    changed_relation_ids = frozenset(
        relation_id
        for item in applied
        for relation_id in RepairAction.from_dict(item["action"]).relation_ids
    )

    return SolidificationPlan(
        baseline=baseline,
        solidified=state,
        policy=policy,
        original_actions=actions,
        remaining_actions=tuple(remaining),
        applied=tuple(applied),
        changed_relation_ids=changed_relation_ids,
    )


def plan_report_solidification(
    document_a_path: str | Path,
    document_b_path: str | Path,
    report_path: str | Path,
    policy: SolidifyPolicy,
) -> tuple[SolidificationPlan, dict]:
    """Load a report and create a checked, non-mutating solidification plan."""

    path_a = Path(document_a_path)
    path_b = Path(document_b_path)
    report_target = Path(report_path)
    report = load_report(report_target)
    if not report_matches_documents(report, path_a, path_b):
        raise ReportError("源文档已变化，不能固化基于旧快照的修复")
    pair = create_alignment_pair(
        pair_id=str(report.get("chapter_id") or path_a.stem),
        document_a_path=path_a,
        document_b_path=path_b,
        report_path=report_target,
        operations=operations_from_report(report),
        relation_ids=relation_ids_from_report(report),
        provenance=dict(report.get("provenance") or {}),
    )
    baseline = PairEditingState.from_alignment_pair(
        pair,
        path_a.read_text(encoding="utf-8-sig"),
        path_b.read_text(encoding="utf-8-sig"),
    )
    actions = [RepairAction.from_dict(item) for item in report.get("repair_log", ())]
    return build_solidification_plan(baseline, actions, policy), report


def solidify_report(
    document_a_path: str | Path,
    document_b_path: str | Path,
    report_path: str | Path,
    policy: SolidifyPolicy,
) -> tuple[SolidificationPlan, PairSaveResult | None]:
    """Plan and atomically apply selected effects to a document pair."""

    report_target = Path(report_path)
    expected_report_sha256 = file_bytes_sha256(report_target)
    plan, report = plan_report_solidification(
        document_a_path, document_b_path, report_path, policy
    )
    if not plan.has_changes:
        return plan, None
    result = save_pair_transaction(
        plan.solidified,
        document_a_path=document_a_path,
        document_b_path=document_b_path,
        report_path=report_path,
        report=report,
        expected_report_sha256=expected_report_sha256,
        expected_report_exists=True,
        remaining_repair_log=plan.remaining_actions,
        solidification_policy=policy.to_dict(),
        applied_repairs=plan.applied,
        changed_relation_ids=plan.changed_relation_ids,
    )
    return plan, result


def plan_batch_solidification(
    targets: Iterable[SolidifyTarget], policy: SolidifyPolicy
) -> BatchSolidificationPlan:
    """Build an immutable, exact batch preview without modifying any file."""

    ready: list[BatchSolidificationItem] = []
    skipped: list[BatchSolidificationIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for target in targets:
        identity = tuple(
            os.path.normcase(str(Path(path).resolve()))
            for path in (
                target.document_a_path,
                target.document_b_path,
                target.report_path,
            )
        )
        if identity in seen:
            skipped.append(BatchSolidificationIssue(target, "重复文件对"))
            continue
        seen.add(identity)
        try:
            plan, report = plan_report_solidification(
                target.document_a_path,
                target.document_b_path,
                target.report_path,
                policy,
            )
            if not plan.has_changes:
                skipped.append(
                    BatchSolidificationIssue(target, "没有符合当前范围的待固化修改")
                )
                continue
            ready.append(
                BatchSolidificationItem(
                    target,
                    plan,
                    report,
                    file_bytes_sha256(target.report_path),
                )
            )
        except (OSError, ValueError) as exc:
            skipped.append(BatchSolidificationIssue(target, str(exc), error=True))
    return BatchSolidificationPlan(policy, tuple(ready), tuple(skipped))


def apply_batch_solidification(
    batch: BatchSolidificationPlan,
) -> BatchSolidificationResult:
    """Commit exactly the plans shown in a batch preview, one transaction each."""

    succeeded: list[SolidifyTarget] = []
    failed: list[BatchSolidificationIssue] = []
    for item in batch.ready:
        plan = item.plan
        target = item.target
        try:
            save_pair_transaction(
                plan.solidified,
                document_a_path=target.document_a_path,
                document_b_path=target.document_b_path,
                report_path=target.report_path,
                report=item.report,
                expected_report_sha256=item.report_sha256,
                expected_report_exists=True,
                remaining_repair_log=plan.remaining_actions,
                solidification_policy=batch.policy.to_dict(),
                applied_repairs=plan.applied,
                changed_relation_ids=plan.changed_relation_ids,
            )
            succeeded.append(target)
        except (OSError, ValueError, PairSaveError) as exc:
            failed.append(BatchSolidificationIssue(target, str(exc), error=True))
    return BatchSolidificationResult(tuple(succeeded), tuple(failed), batch.skipped)
