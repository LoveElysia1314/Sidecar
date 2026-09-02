"""Content-complete, hash-bound review bundles for non-GUI reviewers."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dualign.models.action import RepairAction
from dualign.services.report_io import (
    load_report,
    repair_state_from_report,
    save_report,
)

REVIEW_BUNDLE_SCHEMA = "dualign-headless-review-bundle/v1"
REVIEW_DECISIONS_SCHEMA = "dualign-headless-review-decisions/v1"
_ALLOWED_KINDS = {"ok", "flag", "merge", "split", "edit", "delete"}


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_review_bundle(
    document_a_path: str | Path,
    document_b_path: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    report_path = Path(report_path)
    report = load_report(report_path)
    state = repair_state_from_report(report, document_a_path, document_b_path)
    snapshot = state.snapshot
    actions_by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for action in state.repair_log:
        payload = action.to_dict()
        for relation_id in action.relation_ids:
            actions_by_relation[relation_id].append(payload)
    anomaly_relations = report.get("anomaly_diagnostics", {}).get("relations", {})

    relations = []
    for ordinal, (source_indices, target_indices, score) in enumerate(
        snapshot.original_ops
    ):
        relation_id = snapshot.relation_id(ordinal)
        relations.append(
            {
                "ordinal": ordinal,
                "relation_id": relation_id,
                "alignment_type": f"{len(source_indices)}:{len(target_indices)}",
                "score": float(score),
                "source_indices": list(source_indices),
                "target_indices": list(target_indices),
                "source_lines": [snapshot.src_text(index) for index in source_indices],
                "target_lines": [snapshot.tgt_text(index) for index in target_indices],
                "anomalies": list(anomaly_relations.get(relation_id, ())),
                "repair_actions": actions_by_relation.get(relation_id, []),
            }
        )
    return {
        "schema": REVIEW_BUNDLE_SCHEMA,
        "report_path": str(report_path.resolve()),
        "report_sha256": file_sha256(report_path),
        "documents": {
            "a": {
                "path": str(Path(document_a_path).resolve()),
                "sha256": report["documents"]["a"]["sha256"],
            },
            "b": {
                "path": str(Path(document_b_path).resolve()),
                "sha256": report["documents"]["b"]["sha256"],
            },
        },
        "alignment": dict(report.get("alignment") or {}),
        "provenance": dict(report.get("provenance") or {}),
        "relations": relations,
    }


def _action_from_decision(
    decision: Mapping[str, Any], state, *, reviewer: str
) -> RepairAction:
    kind = str(decision.get("kind", ""))
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"unsupported headless review decision: {kind}")
    relation_ids = tuple(str(value) for value in decision.get("relation_ids", ()))
    if not relation_ids:
        raise ValueError("headless review decision has no relation_ids")
    ordinals = state.snapshot.operation_indices(relation_ids)
    if kind == "merge" and ordinals != tuple(range(ordinals[0], ordinals[-1] + 1)):
        raise ValueError("merge decisions must target consecutive relations")
    data = dict(decision.get("data") or {})
    data["review_agent"] = reviewer
    if kind == "flag" and not str(data.get("note", "")).strip():
        raise ValueError("flag decisions require data.note")
    if kind == "split" and not (data.get("new_src_lines") or data.get("new_tgt_lines")):
        raise ValueError("split decisions require new_src_lines or new_tgt_lines")
    return RepairAction(
        kind=kind,
        sub_count=int(decision.get("sub_count", 1)),
        source="ai",
        data=data,
        relation_ids=relation_ids,
    )


def apply_review_decisions(
    document_a_path: str | Path,
    document_b_path: str | Path,
    report_path: str | Path,
    decisions: Mapping[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    if decisions.get("schema") != REVIEW_DECISIONS_SCHEMA:
        raise ValueError("unrecognized headless review decisions schema")
    report_path = Path(report_path)
    before_sha256 = file_sha256(report_path)
    expected = str(decisions.get("report_sha256", ""))
    if expected != before_sha256:
        raise ValueError("review decisions do not match the current report SHA-256")
    report = load_report(report_path)
    state = repair_state_from_report(report, document_a_path, document_b_path)
    reviewer = str(decisions.get("reviewer", "")).strip()
    if not reviewer:
        raise ValueError("headless review decisions require reviewer")
    actions = [
        _action_from_decision(item, state, reviewer=reviewer)
        for item in decisions.get("decisions", ())
    ]
    reviewed_ids = {
        relation_id for action in actions for relation_id in action.relation_ids
    }
    state = state.apply_many(actions)
    result = {
        "valid": True,
        "applied": bool(apply),
        "report_path": str(report_path.resolve()),
        "report_sha256_before": before_sha256,
        "decision_count": len(actions),
        "reviewed_relation_count": len(reviewed_ids),
        "reviewer": reviewer,
    }
    if not apply:
        return result

    report["repair_log"] = [action.to_dict() for action in state.repair_log]
    report["ai_review"] = {
        "status": "complete",
        "reviewer": reviewer,
        "decision_count": len(actions),
        "reviewed_relation_count": len(reviewed_ids),
        "bundle_report_sha256": before_sha256,
        "note": str(decisions.get("note", "")),
    }
    save_report(report, report_path)
    result["report_sha256_after"] = file_sha256(report_path)
    return result


def write_review_bundle(bundle: Mapping[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path
