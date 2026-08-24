"""Durable JSON work reports for one pair of documents.

The report is the only persisted editing state.  Source documents stay
untouched until the user explicitly solidifies selected effects; paired reader
rows are materialized from the report only when a consumer asks for them.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from dualign.models.action import RepairAction, canonicalize_action_payload
from dualign.models.relation_identity import normalize_relation_ids
from dualign.models.state import AlignmentSnapshot
from dualign.models.score_cache import RelationScoreCache
from dualign.services.alignment_io import document_sha256
from dualign.services.repair import RepairService, RepairState

REPORT_FORMAT = "dualign-report/v1"


class ReportError(ValueError):
    """Raised when a work report is malformed or no longer matches its inputs."""


def _semantic_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Return only metadata that can change alignment relations.

    Tool releases and lifecycle labels are useful audit data, but must not
    invalidate an otherwise identical alignment.
    """

    return {
        "tool": provenance.get("tool", "dualign"),
        "algorithm": dict(provenance.get("algorithm") or {}),
        "embedding": dict(provenance.get("embedding") or {}),
    }


@dataclass(frozen=True)
class AlignmentKey:
    """Semantic identity of one reusable alignment result."""

    document_a_sha256: str
    document_b_sha256: str
    provenance_sha256: str

    @classmethod
    def from_values(
        cls,
        document_a_sha256: str,
        document_b_sha256: str,
        provenance: Mapping[str, Any],
    ) -> "AlignmentKey":
        return cls(
            document_a_sha256=document_a_sha256,
            document_b_sha256=document_b_sha256,
            provenance_sha256=_canonical_sha256(_semantic_provenance(provenance)),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "document_a_sha256": self.document_a_sha256,
            "document_b_sha256": self.document_b_sha256,
            "provenance_sha256": self.provenance_sha256,
        }


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def operations_payload(operations, relation_ids=()) -> list[dict[str, Any]]:
    operation_list = list(operations)
    normalized_ids = normalize_relation_ids(len(operation_list), relation_ids)
    return [
        {
            "id": relation_id,
            "s": list(source),
            "t": list(target),
            "sc": round(float(score), 6),
        }
        for relation_id, (source, target, score) in zip(normalized_ids, operation_list)
    ]


def operations_from_report(report: Mapping[str, Any]) -> list[tuple]:
    try:
        return [
            (tuple(item["s"]), tuple(item["t"]), float(item["sc"]))
            for item in report["ops"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportError("报告中的对齐关系无效") from exc


def relation_ids_from_report(report: Mapping[str, Any]) -> tuple[str, ...]:
    """Read the stable relation IDs required by the current report format."""

    try:
        items = list(report["ops"])
        values = tuple(
            str(item.get("id") or "").strip()
            for item in items
            if isinstance(item, dict)
        )
        if len(values) != len(items):
            raise ValueError("对齐关系必须是对象")
        if any(not value for value in values):
            raise ValueError("当前报告格式要求每条关系都有稳定 ID")
        return normalize_relation_ids(len(items), values)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportError("报告中的关系 ID 无效") from exc


def _repair_action_payload(action: Any, relation_ids: tuple[str, ...]) -> dict:
    payload = action.to_dict() if isinstance(action, RepairAction) else dict(action)
    try:
        return canonicalize_action_payload(payload, relation_ids)
    except ValueError as exc:
        raise ReportError(str(exc)) from exc


def _canonical_ai_proposals(
    raw_store: object, relation_ids: tuple[str, ...]
) -> dict[str, list[dict]]:
    if not isinstance(raw_store, Mapping):
        return {}
    result: dict[str, list[dict]] = {}
    for proposals in raw_store.values():
        if not isinstance(proposals, list):
            continue
        for raw_proposal in proposals:
            if not isinstance(raw_proposal, Mapping):
                continue
            proposal = dict(raw_proposal)
            proposal["action"] = _repair_action_payload(
                proposal.get("action") or {}, relation_ids
            )
            target_ids = proposal["action"]["relation_ids"]
            result.setdefault(target_ids[0], []).append(proposal)
    return result


def _canonicalize_relation_state(data: dict[str, Any]) -> None:
    """Normalize every relation-owned payload at the report boundary."""

    relation_ids = relation_ids_from_report(data)
    data["repair_log"] = [
        _repair_action_payload(action, relation_ids)
        for action in data.get("repair_log", ())
    ]
    data["ai_proposals"] = _canonical_ai_proposals(
        data.get("ai_proposals"), relation_ids
    )
    data["scores"] = RelationScoreCache.from_dict(
        data.get("scores"), relation_ids
    ).to_dict()


def build_report(
    *,
    chapter_id: str,
    document_a_path: str | Path,
    document_b_path: str | Path,
    operations,
    relation_ids=(),
    stats: Mapping[str, Any],
    quality: Mapping[str, Any],
    provenance: Mapping[str, Any],
    alignment: Mapping[str, Any] | None = None,
    repair_log=(),
    previous: Mapping[str, Any] | None = None,
    document_a_sha256_value: str = "",
    document_b_sha256_value: str = "",
) -> dict[str, Any]:
    """Build a complete report while retaining review data from a valid report."""

    path_a = Path(document_a_path)
    path_b = Path(document_b_path)
    ops = operations_payload(operations, relation_ids)
    normalized_relation_ids = tuple(item["id"] for item in ops)
    documents = {
        "a": {
            "path": path_a.name,
            "sha256": document_a_sha256_value or document_sha256(path_a),
        },
        "b": {
            "path": path_b.name,
            "sha256": document_b_sha256_value or document_sha256(path_b),
        },
    }
    fingerprint = _canonical_sha256(
        {
            "documents": documents,
            "ops": ops,
            "segmentation": "content-line",
            "provenance": provenance,
        }
    )
    old = dict(previous or {})
    alignment_key = AlignmentKey.from_values(
        documents["a"]["sha256"], documents["b"]["sha256"], provenance
    )
    created_at = old.get("created_at") or _now()
    report: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "chapter_id": chapter_id,
        "created_at": created_at,
        "updated_at": _now(),
        "documents": documents,
        # Kept at top level because repair replay and manager aggregation scan
        # these fields frequently.
        "src_hash": documents["a"]["sha256"],
        "tgt_hash": documents["b"]["sha256"],
        "segmentation": "content-line",
        "ops": ops,
        "snapshot_fingerprint": fingerprint,
        "alignment_key": alignment_key.to_dict(),
        "provenance": dict(provenance),
        "stats": dict(stats),
        "alignment": dict(alignment or {"status": "aligned"}),
        "quality": dict(quality),
        "repair_log": [
            _repair_action_payload(action, normalized_relation_ids)
            for action in repair_log
        ],
        "ai_proposals": old.get("ai_proposals", {}),
        "ai_review": old.get("ai_review", {}),
        "scores": old.get("scores", {}),
        "history": list(old.get("history", [])),
    }
    return report


def save_report(report: Mapping[str, Any], path: str | Path) -> Path:
    """Validate and atomically replace a report."""

    data = deepcopy(dict(report))
    if data.get("format") != REPORT_FORMAT:
        raise ReportError("拒绝写入无法识别的 Dualign 报告")
    if not isinstance(data.get("alignment"), Mapping):
        raise ReportError("拒绝写入缺少对齐决策的 Dualign 报告")
    operations_from_report(data)
    _canonicalize_relation_state(data)
    data["updated_at"] = _now()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def load_report(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"无法读取报告: {path}") from exc
    if not isinstance(data, dict) or data.get("format") != REPORT_FORMAT:
        raise ReportError("报告格式已过时，请重新对齐文档")
    operations_from_report(data)
    _canonicalize_relation_state(data)
    if not isinstance(data.get("alignment"), Mapping):
        raise ReportError("报告缺少当前格式要求的对齐决策，请重新对齐文档")
    return data


def report_matches_documents(
    report: Mapping[str, Any], document_a_path: str | Path, document_b_path: str | Path
) -> bool:
    documents = report.get("documents") or {}
    try:
        return documents["a"]["sha256"] == document_sha256(
            document_a_path
        ) and documents["b"]["sha256"] == document_sha256(document_b_path)
    except (KeyError, OSError, TypeError):
        return False


def report_alignment_key(report: Mapping[str, Any]) -> AlignmentKey | None:
    documents = report.get("documents") or {}
    try:
        computed = AlignmentKey.from_values(
            str(documents["a"]["sha256"]),
            str(documents["b"]["sha256"]),
            report.get("provenance") or {},
        )
        stored = report.get("alignment_key")
        if stored is not None and stored != computed.to_dict():
            return None
        return computed
    except (KeyError, TypeError):
        return None


def expected_alignment_key(
    document_a_path: str | Path,
    document_b_path: str | Path,
    provenance: Mapping[str, Any],
) -> AlignmentKey:
    return AlignmentKey.from_values(
        document_sha256(document_a_path),
        document_sha256(document_b_path),
        provenance,
    )


def report_matches_alignment(
    report: Mapping[str, Any],
    document_a_path: str | Path,
    document_b_path: str | Path,
    provenance: Mapping[str, Any],
) -> bool:
    """Check the single semantic cache identity used by every front end."""

    actual = report_alignment_key(report)
    if actual is None:
        return False
    try:
        expected = expected_alignment_key(document_a_path, document_b_path, provenance)
    except OSError:
        return False
    return actual == expected


def repair_state_from_report(
    report: Mapping[str, Any], document_a_path: str | Path, document_b_path: str | Path
) -> RepairState:
    if not report_matches_documents(report, document_a_path, document_b_path):
        raise ReportError("源文档已变化，报告中的行索引不再安全")
    from dualign.common import load_text_lines

    snapshot = AlignmentSnapshot.from_alignment(
        operations_from_report(report),
        load_text_lines(str(document_a_path)),
        load_text_lines(str(document_b_path)),
        relation_ids_from_report(report),
    )
    actions = [RepairAction.from_dict(item) for item in report.get("repair_log", [])]
    return RepairState(snapshot, actions)


def materialize_reader_rows(
    report_path: str | Path,
    document_a_path: str | Path,
    document_b_path: str | Path,
) -> tuple[list[str], list[str]]:
    """Replay a report into equal-row text solely for reader/build consumers."""

    report = load_report(report_path)
    return RepairService.render_rows(
        repair_state_from_report(report, document_a_path, document_b_path)
    )


def update_report(
    path: str | Path, mutator: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    report = load_report(path)
    mutator(report)
    save_report(report, path)
    return report


def set_ai_review(path: str | Path, status: str, note: str = "") -> dict[str, Any]:
    def mutate(report: dict[str, Any]) -> None:
        report["ai_review"] = {"status": status, "note": note, "updated_at": _now()}

    return update_report(path, mutate)
