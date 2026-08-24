"""Recoverable save for two source documents and their work report."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from dualign.common import file_bytes_sha256, file_identity_changed
from dualign.config import get_cache_root
from dualign.models.action import canonicalize_action_payload
from dualign.models.pair_editing import PairEditingState
from dualign.models.relation_identity import rebase_relation_ids
from dualign.models.score_cache import RelationScoreCache
from dualign.models.state import MISSING
from dualign.services.alignment_io import document_sha256, document_sha256_from_text
from dualign.services.report_io import (
    build_report,
    relation_ids_from_report,
)
from dualign.services.realignment import RebuiltAlignment, rebuild_alignment


class PairSaveError(RuntimeError):
    """Base error for a failed multi-file save."""


class PairSaveConflictError(PairSaveError):
    """Raised when a file changed outside Dualign after it was opened."""


class PairSavePlaceholderError(PairSaveError):
    """Raised when a ⟢MISSING⟣ placeholder would be written into a document.

    The placeholder only exists in the review state (a missing-side marker),
    it must never reach the natural documents.  If it would, that is a data
    bug that should be surfaced instead of silently written or filtered.
    """


def _guard_no_missing_placeholder(text_a: str, text_b: str) -> None:
    """拒绝把独立 ⟢MISSING⟣ 占位符行写入正文文档。

    占位符只属于校订状态（表示「译文缺失」），不应出现在正文中。
    检测独立的占位符行（strip 后完全等于 MISSING 常量）——这是
    最明确的残留信号；内嵌于正文文本中的符号不作处理（可能是引用）。
    """
    for label, text in (("文档 A", text_a), ("文档 B", text_b)):
        for line in text.split("\n"):
            if line.strip() == MISSING:
                raise PairSavePlaceholderError(
                    f"检测到 {label} 将写入 ⟢MISSING⟣ 占位符行，已拒绝保存。"
                    "该符号只表示校订阶段的『译文缺失』，不应写入正文文档；"
                    "请先在人工/AI 校订中补译对应行，再重新固化。"
                )


@dataclass(frozen=True)
class PairSaveResult:
    document_a_path: Path
    document_b_path: Path
    report_path: Path
    document_a_sha256: str
    document_b_sha256: str
    report_sha256: str


def _write_temp(target: Path, payload: str, transaction_id: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{target.name}.{transaction_id}.",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    ) as handle:
        path = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _write_journal(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _install_prepared(temp_path: Path, target_path: Path) -> None:
    """Install one prepared file; isolated so rollback behavior is testable."""

    os.replace(temp_path, target_path)


def _rollback(journal: dict) -> list[str]:
    errors: list[str] = []
    for item in reversed(journal.get("targets", [])):
        target = Path(item["path"])
        backup = Path(item["backup"])
        temporary = Path(item["temporary"])
        try:
            if backup.exists():
                if target.exists():
                    target.unlink()
                os.replace(backup, target)
            elif not item.get("existed", False) and target.exists():
                expected_new = item.get("new_sha256", "")
                if not expected_new or file_bytes_sha256(target) == expected_new:
                    target.unlink()
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    return errors


def recover_pending_pair_saves(transaction_dir: str | Path | None = None) -> list[str]:
    """Conservatively roll back interrupted saves and return recovery messages."""

    root = Path(transaction_dir or Path(get_cache_root()) / "transactions")
    if not root.is_dir():
        return []
    messages: list[str] = []
    for journal_path in sorted(root.glob("pair-save-*.json")):
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            errors = _rollback(journal)
            if errors:
                messages.append(
                    f"事务 {journal.get('id', journal_path.stem)} 恢复不完整: "
                    + "; ".join(errors)
                )
                continue
            journal_path.unlink(missing_ok=True)
            messages.append(f"已回滚未完成保存: {journal.get('id', journal_path.stem)}")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            messages.append(f"无法恢复事务 {journal_path}: {exc}")
    return messages


def _reanchor_proposal_action(
    raw_action: object,
    source_relation_ids: tuple[str, ...],
    final_relation_ids: tuple[str, ...],
    changed_relation_ids: frozenset[str],
) -> dict | None:
    if not isinstance(raw_action, dict):
        return None
    try:
        action = canonicalize_action_payload(raw_action, source_relation_ids)
    except ValueError:
        return None
    target_ids = tuple(action["relation_ids"])
    if not target_ids or set(target_ids) & changed_relation_ids:
        return None
    final_ids = set(final_relation_ids)
    for relation_id in target_ids:
        if relation_id not in final_ids:
            return None
    return action


def _rebase_pending_ai_proposals(
    raw_store: object,
    source_relation_ids: tuple[str, ...],
    final_relation_ids: tuple[str, ...],
    changed_relation_ids: frozenset[str],
) -> dict:
    """Keep only still-actionable pending proposals after solidification."""

    if not isinstance(raw_store, dict):
        return {}
    rebased: dict[str, list[dict]] = {}
    for proposals in raw_store.values():
        if not isinstance(proposals, list):
            continue
        for raw_proposal in proposals:
            if (
                not isinstance(raw_proposal, dict)
                or raw_proposal.get("status", "pending") != "pending"
            ):
                continue
            action = _reanchor_proposal_action(
                raw_proposal.get("action"),
                source_relation_ids,
                final_relation_ids,
                changed_relation_ids,
            )
            if action is None:
                continue
            proposal = dict(raw_proposal)
            proposal["action"] = action
            target_ids = action.get("relation_ids") or ()
            key = str(target_ids[0])
            rebased.setdefault(key, []).append(proposal)
    return rebased


def _operation_fingerprint(operation, lines_a, lines_b):
    source, target, _score = operation
    return (
        tuple(lines_a[index] for index in source),
        tuple(lines_b[index] for index in target),
    )


def _exact_relation_map(old_operations, new_operations, lines_a, lines_b):
    """Map only relations whose exact two-sided content is uniquely preserved."""

    old_by_fingerprint: dict[tuple, list[int]] = {}
    new_by_fingerprint: dict[tuple, list[int]] = {}
    for index, operation in enumerate(old_operations):
        old_by_fingerprint.setdefault(
            _operation_fingerprint(operation, lines_a, lines_b), []
        ).append(index)
    for index, operation in enumerate(new_operations):
        new_by_fingerprint.setdefault(
            _operation_fingerprint(operation, lines_a, lines_b), []
        ).append(index)

    result: list[int | None] = [None] * len(old_operations)
    for fingerprint, old_indices in old_by_fingerprint.items():
        new_indices = new_by_fingerprint.get(fingerprint, ())
        if len(old_indices) == 1 and len(new_indices) == 1:
            result[old_indices[0]] = new_indices[0]
    return tuple(result)


def _rebase_repair_log(raw_actions, source_relation_ids, final_relation_ids):
    result = []
    for raw_action in raw_actions:
        action = raw_action.to_dict() if hasattr(raw_action, "to_dict") else raw_action
        rebased = _reanchor_proposal_action(
            action,
            source_relation_ids,
            final_relation_ids,
            frozenset(),
        )
        if rebased is not None:
            result.append(rebased)
    return result


def save_pair_transaction(
    state: PairEditingState,
    *,
    document_a_path: str | Path,
    document_b_path: str | Path,
    report_path: str | Path,
    report: dict,
    expected_report_sha256: str = "",
    expected_report_exists: bool | None = None,
    transaction_dir: str | Path | None = None,
    remaining_repair_log=(),
    solidification_policy: dict | None = None,
    applied_repairs=(),
    changed_relation_ids=(),
    alignment_runner=None,
) -> PairSaveResult:
    """Save two documents and their rebased report as one transaction.

    Selective solidification first aligns the future natural documents from
    scratch.  Derived state is migrated only through exact, unique two-sided
    relation identities; positional indices are never treated as identity.
    """

    path_a = Path(document_a_path).resolve()
    path_b = Path(document_b_path).resolve()
    report_target = Path(report_path).resolve()
    if (
        len({os.path.normcase(str(path)) for path in (path_a, path_b, report_target)})
        != 3
    ):
        raise PairSaveError("两份正文和工作报告必须使用三个不同路径")

    expected_a = state.document_a_ref.sha256
    expected_b = state.document_b_ref.sha256
    conflicts: list[str] = []
    if not path_a.is_file() or (expected_a and document_sha256(path_a) != expected_a):
        conflicts.append("文档 A")
    if not path_b.is_file() or (expected_b and document_sha256(path_b) != expected_b):
        conflicts.append("文档 B")
    if file_identity_changed(
        report_target,
        expected_exists=expected_report_exists,
        expected_sha256=expected_report_sha256,
    ):
        conflicts.append("工作报告")
    if conflicts:
        raise PairSaveConflictError(
            "以下文件在打开后被外部修改或删除，已拒绝覆盖：" + "、".join(conflicts)
        )

    text_a = state.document_a.render_text()
    text_b = state.document_b.render_text()
    _guard_no_missing_placeholder(text_a, text_b)
    hash_a = document_sha256_from_text(text_a)
    hash_b = document_sha256_from_text(text_b)
    changed = frozenset(str(value) for value in changed_relation_ids)
    pair = state.to_alignment_pair()
    intermediate_operations = [
        (
            tuple(index - 1 for index in link.document_a),
            tuple(index - 1 for index in link.document_b),
            float(link.confidence or 0.0),
        )
        for link in pair.links
        if link.state != "rejected"
    ]
    intermediate_relation_ids = tuple(
        link.id for link in pair.links if link.state != "rejected"
    )
    relation_map: tuple[int | None, ...] | None = None
    rebuilt: RebuiltAlignment | None = None
    if solidification_policy is not None:
        runner = alignment_runner or rebuild_alignment
        try:
            rebuilt = runner(
                list(state.document_a.blocks), list(state.document_b.blocks)
            )
            operations = list(rebuilt.operations)
            relation_map = _exact_relation_map(
                intermediate_operations,
                operations,
                state.document_a.blocks,
                state.document_b.blocks,
            )
            relation_ids = rebase_relation_ids(
                intermediate_relation_ids, relation_map, len(operations)
            )
        except Exception as exc:
            raise PairSaveError(f"固化后的文本重新对齐失败: {exc}") from exc
    else:
        operations = intermediate_operations
        relation_ids = intermediate_relation_ids
    from datetime import datetime

    previous = dict(report)
    history = list(previous.get("history", []))
    history.append(
        {
            "type": (
                "selective-solidification"
                if solidification_policy is not None
                else "source-overwrite"
            ),
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "repair_log": list(previous.get("repair_log", [])),
            "policy": dict(solidification_policy or {}),
            "applied_repairs": list(applied_repairs),
        }
    )
    previous["history"] = history
    # Resolved suggestions are historical, while pending suggestions and scores
    # remain useful only when their text survived unchanged.  Re-anchor those
    # views to the rebuilt operation list; invalidate everything derived from a
    # relation that was actually solidified.
    if solidification_policy is not None and relation_map is not None:
        original_relation_ids = relation_ids_from_report(previous)
        previous["ai_proposals"] = _rebase_pending_ai_proposals(
            previous.get("ai_proposals"),
            original_relation_ids,
            relation_ids,
            changed,
        )
        previous["scores"] = (
            RelationScoreCache.from_dict(previous.get("scores"), original_relation_ids)
            .retain(set(relation_ids), excluding=changed)
            .to_dict()
        )
        remaining_repair_log = _rebase_repair_log(
            remaining_repair_log,
            intermediate_relation_ids,
            relation_ids,
        )
    else:
        previous["ai_proposals"] = {}
        previous["scores"] = {}
    previous["ai_review"] = {}
    stats = dict(rebuilt.stats if rebuilt is not None else previous.get("stats") or {})
    stats.update(
        {
            "n_source": len(state.document_a.blocks),
            "n_target": len(state.document_b.blocks),
            "n_ops": len(operations),
            "alignment_origin": (
                "selective-solidification"
                if solidification_policy is not None
                else "source-overwrite"
            ),
            "preserved_relation_states": (
                sum(index is not None for index in relation_map)
                if relation_map is not None
                else 0
            ),
            "invalidated_relation_states": (
                sum(index is None for index in relation_map)
                if relation_map is not None
                else 0
            ),
        }
    )
    rebased_report = build_report(
        chapter_id=str(previous.get("chapter_id") or path_a.stem.split(".")[0]),
        document_a_path=path_a,
        document_b_path=path_b,
        operations=operations,
        relation_ids=relation_ids,
        stats=stats,
        quality=(
            dict(rebuilt.quality)
            if rebuilt is not None
            else dict(previous.get("quality") or {})
        ),
        provenance=(
            dict(rebuilt.provenance)
            if rebuilt is not None
            else dict(previous.get("provenance") or {})
        ),
        alignment=(
            dict(rebuilt.alignment)
            if rebuilt is not None
            else dict(previous.get("alignment") or {"status": "aligned"})
        ),
        repair_log=remaining_repair_log,
        previous=previous,
        document_a_sha256_value=hash_a,
        document_b_sha256_value=hash_b,
    )
    report_text = json.dumps(rebased_report, ensure_ascii=False, indent=2) + "\n"

    transaction_id = uuid.uuid4().hex
    root = Path(transaction_dir or Path(get_cache_root()) / "transactions")
    journal_path = root / f"pair-save-{transaction_id}.json"
    payloads = ((path_a, text_a), (path_b, text_b), (report_target, report_text))
    targets: list[dict] = []
    try:
        for target, payload in payloads:
            temporary = _write_temp(target, payload, transaction_id)
            backup = target.parent / f".{target.name}.{transaction_id}.rollback"
            targets.append(
                {
                    "path": str(target),
                    "temporary": str(temporary),
                    "backup": str(backup),
                    "existed": target.exists(),
                    "original_sha256": (
                        file_bytes_sha256(target) if target.exists() else ""
                    ),
                    "new_sha256": file_bytes_sha256(temporary),
                    "installed": False,
                }
            )
        journal = {"version": 1, "id": transaction_id, "targets": targets}
        _write_journal(journal_path, journal)

        for item in targets:
            target = Path(item["path"])
            temporary = Path(item["temporary"])
            backup = Path(item["backup"])
            if target.exists():
                os.replace(target, backup)
            _install_prepared(temporary, target)
            item["installed"] = True
            _write_journal(journal_path, journal)

        for item in targets:
            Path(item["backup"]).unlink(missing_ok=True)
        journal_path.unlink(missing_ok=True)
    except Exception as exc:
        journal = {"version": 1, "id": transaction_id, "targets": targets}
        rollback_errors = _rollback(journal)
        if not rollback_errors:
            journal_path.unlink(missing_ok=True)
        detail = f"三文件保存失败: {exc}"
        if rollback_errors:
            detail += "；自动回滚不完整: " + "; ".join(rollback_errors)
        raise PairSaveError(detail) from exc

    return PairSaveResult(
        document_a_path=path_a,
        document_b_path=path_b,
        report_path=report_target,
        document_a_sha256=hash_a,
        document_b_sha256=hash_b,
        report_sha256=file_bytes_sha256(report_target),
    )
