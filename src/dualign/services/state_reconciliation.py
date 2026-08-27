"""Reconcile relation-owned work state across alignment snapshots.

Alignment cache identity answers whether the expensive alignment result can be
reused.  This module answers a deliberately separate question: which pieces of
human or derived work still describe exactly the same two-sided text relation?
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from dualign.models.action import canonicalize_action_payload
from dualign.models.relation_identity import rebase_relation_ids
from dualign.models.score_cache import RelationScoreCache

RELATION_FINGERPRINT_SCHEMA = "content-line-pair/v1"
RELATION_FINGERPRINT_DIGEST = "sha256-128"
RELATION_FINGERPRINT_ENCODING = "base64url"


def _relation_text(operation, lines_a: Sequence[str], lines_b: Sequence[str]):
    source, target, _score = operation
    try:
        return (
            tuple(lines_a[int(index)] for index in source),
            tuple(lines_b[int(index)] for index in target),
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("对齐关系引用了不存在的正文行") from exc


def relation_fingerprint(
    operation, lines_a: Sequence[str], lines_b: Sequence[str]
) -> str:
    """Return a compact identity for exact relation content.

    Position, alignment score, algorithm revision and report relation ID are
    intentionally excluded.  JSON supplies an unambiguous length-aware text
    encoding; the schema string domain-separates this use of SHA-256.
    """

    source_text, target_text = _relation_text(operation, lines_a, lines_b)
    payload = json.dumps(
        [RELATION_FINGERPRINT_SCHEMA, source_text, target_text],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()[:16]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def relation_fingerprints(
    operations: Iterable, lines_a: Sequence[str], lines_b: Sequence[str]
) -> tuple[str, ...]:
    return tuple(
        relation_fingerprint(operation, lines_a, lines_b) for operation in operations
    )


def relation_identity_payload(fingerprints: Iterable[str]) -> dict[str, Any]:
    return {
        "schema": RELATION_FINGERPRINT_SCHEMA,
        "digest": RELATION_FINGERPRINT_DIGEST,
        "encoding": RELATION_FINGERPRINT_ENCODING,
        "fingerprints": list(fingerprints),
    }


def relation_fingerprints_from_report(
    report: Mapping[str, Any], *, expected_count: int | None = None
) -> tuple[str, ...] | None:
    """Read persisted identities, returning ``None`` for legacy reports."""

    raw = report.get("relation_identity")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("报告中的关系内容指纹无效")
    if (
        raw.get("schema") != RELATION_FINGERPRINT_SCHEMA
        or raw.get("digest") != RELATION_FINGERPRINT_DIGEST
        or raw.get("encoding") != RELATION_FINGERPRINT_ENCODING
    ):
        raise ValueError("报告使用了无法识别的关系内容指纹格式")
    values = raw.get("fingerprints")
    if not isinstance(values, list) or any(
        not isinstance(value, str) or len(value) != 22 for value in values
    ):
        raise ValueError("报告中的关系内容指纹无效")
    if expected_count is not None and len(values) != expected_count:
        raise ValueError("关系内容指纹数量与对齐关系数量不一致")
    return tuple(values)


def map_relations(
    source_operations: Sequence,
    target_operations: Sequence,
    source_fingerprints: Sequence[str],
    target_fingerprints: Sequence[str],
    *,
    positional_identity: bool = False,
) -> tuple[int | None, ...]:
    """Map exact relations conservatively.

    When both documents are byte-identical, identical index topology is a
    stronger identity and safely disambiguates repeated text.  Otherwise only
    a fingerprint occurring exactly once on both sides is reused.
    """

    if len(source_operations) != len(source_fingerprints):
        raise ValueError("旧关系与内容指纹数量不一致")
    if len(target_operations) != len(target_fingerprints):
        raise ValueError("新关系与内容指纹数量不一致")

    result: list[int | None] = [None] * len(source_operations)
    used_targets: set[int] = set()
    if positional_identity:
        target_by_topology: dict[tuple[tuple[int, ...], tuple[int, ...]], list[int]] = (
            defaultdict(list)
        )
        for index, (source, target, _score) in enumerate(target_operations):
            target_by_topology[(tuple(source), tuple(target))].append(index)
        for old_index, (source, target, _score) in enumerate(source_operations):
            candidates = target_by_topology.get((tuple(source), tuple(target)), ())
            if (
                len(candidates) == 1
                and source_fingerprints[old_index] == target_fingerprints[candidates[0]]
            ):
                result[old_index] = candidates[0]
                used_targets.add(candidates[0])

    old_by_fingerprint: dict[str, list[int]] = defaultdict(list)
    new_by_fingerprint: dict[str, list[int]] = defaultdict(list)
    for index, fingerprint in enumerate(source_fingerprints):
        if result[index] is None:
            old_by_fingerprint[fingerprint].append(index)
    for index, fingerprint in enumerate(target_fingerprints):
        if index not in used_targets:
            new_by_fingerprint[fingerprint].append(index)
    for fingerprint, old_indices in old_by_fingerprint.items():
        new_indices = new_by_fingerprint.get(fingerprint, ())
        if len(old_indices) == 1 and len(new_indices) == 1:
            result[old_indices[0]] = new_indices[0]
    return tuple(result)


@dataclass(frozen=True)
class ReconciledRelationState:
    relation_ids: tuple[str, ...]
    relation_map: tuple[int | None, ...]
    repair_log: list[dict]
    ai_proposals: dict[str, list[dict]]
    scores: dict[str, dict[str, float]]
    audit: dict[str, int | str]


def _retained_action(
    raw_action: object,
    source_relation_ids: tuple[str, ...],
    retained_ids: set[str],
    invalidated_ids: frozenset[str],
) -> dict | None:
    if not isinstance(raw_action, Mapping):
        return None
    try:
        action = canonicalize_action_payload(dict(raw_action), source_relation_ids)
    except ValueError:
        return None
    target_ids = set(action.get("relation_ids") or ())
    if (
        not target_ids
        or not target_ids <= retained_ids
        or bool(target_ids & invalidated_ids)
    ):
        return None
    return action


def reconcile_relation_state(
    *,
    source_operations: Sequence,
    source_relation_ids: tuple[str, ...],
    source_fingerprints: Sequence[str],
    target_operations: Sequence,
    target_fingerprints: Sequence[str],
    repair_log: Iterable[object] = (),
    ai_proposals: object = None,
    scores: object = None,
    invalidated_relation_ids: Iterable[str] = (),
    positional_identity: bool = False,
    pending_ai_only: bool = False,
    review_required_target_indices: Iterable[int] | None = None,
    cause: str = "realignment",
) -> ReconciledRelationState:
    """Preserve only relation-owned state whose exact text identity survives."""

    mapping = map_relations(
        source_operations,
        target_operations,
        source_fingerprints,
        target_fingerprints,
        positional_identity=positional_identity,
    )
    final_ids = rebase_relation_ids(
        source_relation_ids, mapping, len(target_operations)
    )
    mapped_source_ids = {
        relation_id
        for relation_id, target_index in zip(source_relation_ids, mapping)
        if target_index is not None
    }
    invalidated = frozenset(str(value) for value in invalidated_relation_ids)
    retained_ids = mapped_source_ids
    retained_derived_ids = retained_ids - invalidated

    retained_actions: list[dict] = []
    for raw_action in repair_log:
        payload = raw_action.to_dict() if hasattr(raw_action, "to_dict") else raw_action
        action = _retained_action(
            payload, source_relation_ids, retained_ids, frozenset()
        )
        if action is not None:
            retained_actions.append(action)

    if review_required_target_indices is not None:
        review_required_ids = {
            final_ids[index]
            for index in review_required_target_indices
            if 0 <= index < len(final_ids)
        }
        retained_actions = [
            action
            for action in retained_actions
            if action.get("kind") != "ok"
            or bool(set(action.get("relation_ids") or ()) & review_required_ids)
        ]

    user_approved_ids = {
        relation_id
        for action in retained_actions
        if bool(action.get("data", {}).get("user_approved"))
        or (action.get("kind") == "ok" and action.get("source") == "user")
        for relation_id in action.get("relation_ids") or ()
    }

    retained_proposals: dict[str, list[dict]] = {}
    if isinstance(ai_proposals, Mapping):
        for proposals in ai_proposals.values():
            if not isinstance(proposals, list):
                continue
            for raw_proposal in proposals:
                if not isinstance(raw_proposal, Mapping):
                    continue
                if (
                    pending_ai_only
                    and raw_proposal.get("status", "pending") != "pending"
                ):
                    continue
                action = _retained_action(
                    raw_proposal.get("action"),
                    source_relation_ids,
                    retained_derived_ids,
                    invalidated,
                )
                if action is None:
                    continue
                if set(action.get("relation_ids") or ()) & user_approved_ids:
                    continue
                proposal = dict(raw_proposal)
                proposal["action"] = action
                key = action["relation_ids"][0]
                retained_proposals.setdefault(key, []).append(proposal)

    retained_scores = (
        RelationScoreCache.from_dict(scores, source_relation_ids)
        .retain(retained_derived_ids, excluding=invalidated)
        .to_dict()
    )
    mapped_count = sum(value is not None for value in mapping)
    audit: dict[str, int | str] = {
        "cause": cause,
        "source_relations": len(source_operations),
        "target_relations": len(target_operations),
        "preserved_relations": len(retained_ids),
        "invalidated_relations": len(source_operations) - len(retained_ids),
        "invalidated_derived_relations": len(retained_ids & invalidated),
        "new_relations": len(target_operations) - mapped_count,
        "preserved_actions": len(retained_actions),
        "preserved_proposals": sum(map(len, retained_proposals.values())),
        "preserved_scores": sum(map(len, retained_scores.values())),
    }
    return ReconciledRelationState(
        relation_ids=final_ids,
        relation_map=mapping,
        repair_log=retained_actions,
        ai_proposals=retained_proposals,
        scores=retained_scores,
        audit=audit,
    )
