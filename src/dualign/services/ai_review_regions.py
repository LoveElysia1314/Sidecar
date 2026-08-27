"""Region-oriented review model and atomic Agent tools.

The aligner and repair engine remain relation/action based internally.  This
module exposes a smaller semantic surface to an LLM: inspect one coherent
region, accept an exact candidate preview, edit the whole region, or defer
it.  Candidate application compiles back to ordinary ``RepairAction`` values,
so reports and the GUI keep their existing storage format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable

from dualign.models.action import CONTENT_ACTION_KINDS, RepairAction
from dualign.models.marker import is_edit, is_split
from dualign.models.relation_status import RelationStatus, project_relation_statuses
from dualign.models.state import MISSING
from dualign.core.text import smart_join_lines
from dualign.services.repair import RepairState

_CONTENT_KINDS = CONTENT_ACTION_KINDS
_REGION_TOOL_NAMES = frozenset(
    {
        "inspect_region",
        "accept_candidate",
        "edit_region",
        "delete_region",
        # Non-advertised compatibility alias for early region-tool scripts.
        "replace_region",
        "defer_region",
        "finish_review",
    }
)

_ANOMALY_LABELS = {
    "NON_1TO1": "非1:1",
    "MIX": "语言杂糅",
    "LOW_SCORE": "低分",
    "FLAGGED": "标记待审",
}

_FLAG_EVIDENCE_FIELDS = frozenset(
    {
        "note",
        "reason",
        "uncertain_region",
        "current_structure",
        "alternative_structure",
    }
)


def region_tool_names() -> frozenset[str]:
    return _REGION_TOOL_NAMES


@dataclass(frozen=True)
class ReviewUnit:
    """One complete N:M bilingual unit at the Agent boundary."""

    src: tuple[str, ...]
    tgt: tuple[str, ...]

    @classmethod
    def from_tool_payload(cls, payload: object, *, path: str) -> ReviewUnit:
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must be an object")
        unexpected = set(payload) - {"src", "tgt"}
        if unexpected:
            fields = ", ".join(sorted(str(value) for value in unexpected))
            raise ValueError(f"{path} has unknown fields: {fields}")

        def parse_side(side: str) -> tuple[str, ...]:
            raw = payload.get(side)
            if not isinstance(raw, list) or not raw:
                raise ValueError(f"{path}.{side} must be a non-empty string array")
            values: list[str] = []
            for index, value in enumerate(raw):
                if not isinstance(value, str):
                    raise ValueError(f"{path}.{side}[{index}] must be a string")
                text = value.strip()
                if not text:
                    raise ValueError(f"{path}.{side}[{index}] must not be empty")
                if MISSING in text:
                    raise ValueError(f"{path}.{side}[{index}] contains {MISSING}")
                values.append(text)
            return tuple(values)

        return cls(src=parse_side("src"), tgt=parse_side("tgt"))

    def to_payload(self) -> dict:
        return {"src": list(self.src), "tgt": list(self.tgt)}

    def compiled_pair(self) -> tuple[str, str]:
        return smart_join_lines(self.src), smart_join_lines(self.tgt)


def _copy_action(action: RepairAction, *, reviewed_by: str = "") -> RepairAction:
    return (
        action.with_reviewer(reviewed_by)
        if reviewed_by
        else RepairAction.from_dict(action.to_dict())
    )


def _action_identity(action: RepairAction) -> str:
    payload = action.to_dict()
    payload.pop("timestamp", None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _origin(actions: Iterable[RepairAction]) -> str:
    origins = list(dict.fromkeys(action.source for action in actions))
    if not origins:
        return "original"
    return origins[0] if len(origins) == 1 else "mixed"


def _relation_state_payload(ordinal: int, status: RelationStatus) -> dict:
    """Expose provenance and detector state as independent evidence."""

    current = [
        _ANOMALY_LABELS.get(value, value) for value in status.current_anomaly_types
    ]
    if status.has_missing:
        current.append("缺失待补")
    return {
        "relation": ordinal,
        "source": status.effective_source,
        "current": current,
        "initial": [
            _ANOMALY_LABELS.get(value, value) for value in status.initial_anomaly_types
        ],
    }


def _rows_for_ordinals(state: RepairState, ordinals: Iterable[int]) -> tuple[dict, ...]:
    rows: list[dict] = []
    for ordinal in sorted(set(ordinals)):
        group = state.current.group(ordinal)
        if group is None:
            continue
        rows.append(
            {
                "relation": ordinal,
                "src": [item.src_text for item in group.rows if item.src_text],
                "tgt": [item.tgt_text for item in group.rows if item.tgt_text],
            }
        )
    return tuple(rows)


def _pairwise_view_for_ordinals(
    state: RepairState, ordinals: Iterable[int]
) -> tuple[dict, ...]:
    groups: list[dict] = []
    for ordinal in sorted(set(ordinals)):
        group = state.current.group(ordinal)
        if group is None:
            continue
        groups.append(
            {
                "relation": ordinal,
                "type": group.rows[0].cur_type if group.rows else "0:0",
                "rows": [
                    {"src": row.src_text, "tgt": row.tgt_text} for row in group.rows
                ],
            }
        )
    return tuple(groups)


def _candidate_validation_issues(rows: Iterable[dict]) -> tuple[str, ...]:
    """Return hard structural blockers, never heuristic text judgments."""

    rows = tuple(rows)
    issues: list[str] = []
    if any(
        MISSING in str(value)
        for row in rows
        for side in ("src", "tgt")
        for value in row.get(side, [])
    ):
        issues.append("contains_missing_placeholder")
    if any(not row.get("src") or not row.get("tgt") for row in rows):
        issues.append("contains_empty_side")
    return tuple(issues)


def _side_structure(rows: Iterable[dict], side: str) -> tuple[int, ...]:
    return tuple(len(row.get(side, [])) for row in rows if row.get(side))


@dataclass(frozen=True)
class ReviewCandidate:
    candidate_id: str
    label: str
    origin: str
    actions: tuple[RepairAction, ...]
    after_rows: tuple[dict, ...]
    after_view: tuple[dict, ...]
    strategy_fit: str = "neutral"
    validation_issues: tuple[str, ...] = ()

    def to_payload(self) -> dict:
        operations = [action.kind for action in self.actions]
        pairwise = any(kind in {"split", "edit"} for kind in operations)
        if pairwise:
            after = [
                {
                    "relation": group["relation"],
                    "units": [
                        {
                            "src": [row["src"]] if row["src"] else [],
                            "tgt": [row["tgt"]] if row["tgt"] else [],
                        }
                        for row in group["rows"]
                    ],
                }
                for group in self.after_view
            ]
        else:
            after = [
                {
                    "relation": row["relation"],
                    "units": [{"src": row["src"], "tgt": row["tgt"]}],
                }
                for row in self.after_rows
            ]
        payload = {
            "candidate_id": self.candidate_id,
            "label": self.label,
            "origin": self.origin,
            "operations": operations,
            "after": after,
        }
        return payload


@dataclass(frozen=True)
class ReviewRegion:
    region_id: str
    ordinals: tuple[int, ...]
    trigger_ordinals: tuple[int, ...]
    flagged_ordinals: tuple[int, ...]
    evidence: dict
    initial_rows: tuple[dict, ...]
    current_rows: tuple[dict, ...]
    relation_states: tuple[dict, ...]
    open_flags: tuple[dict, ...]
    candidates: tuple[ReviewCandidate, ...]

    def to_payload(self) -> dict:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        return {
            "region_id": self.region_id,
            "trigger_relations": list(self.trigger_ordinals),
            "relations": list(self.ordinals),
            "open_flag_relations": list(self.flagged_ordinals),
            "evidence": self.evidence,
            "initial_rows": list(self.initial_rows),
            "current_rows": list(self.current_rows),
            "relation_states": list(self.relation_states),
            "open_flags": list(self.open_flags),
            "candidate_ids": candidate_ids,
            "candidates": [candidate.to_payload() for candidate in self.candidates],
        }


def _indexed_operations(state: RepairState):
    cursor = (0, 0)
    indexed = []
    for ordinal, operation in enumerate(state.snapshot.original_ops):
        source, target, _score = operation
        end = (cursor[0] + len(source), cursor[1] + len(target))
        indexed.append((ordinal, cursor, end))
        cursor = end
    return indexed


def _ordinals_in_lattice_region(state: RepairState, region: dict) -> tuple[int, ...]:
    start = region.get("start", {})
    end = region.get("end", {})
    try:
        lower = (int(start["source"]), int(start["target"]))
        upper = (int(end["source"]), int(end["target"]))
    except (KeyError, TypeError, ValueError):
        return ()
    return tuple(
        ordinal
        for ordinal, op_start, op_end in _indexed_operations(state)
        if lower[0] <= op_start[0]
        and lower[1] <= op_start[1]
        and op_end[0] <= upper[0]
        and op_end[1] <= upper[1]
        and op_start != op_end
    )


def _flag_for_ordinal(state: RepairState, ordinal: int) -> RepairAction | None:
    return state.flag_for_relation(state.snapshot.relation_id(ordinal))


def _flag_evidence(flag: RepairAction | None) -> dict:
    """Expose review evidence without leaking internal action metadata."""

    if flag is None:
        return {}
    return {
        key: value for key, value in flag.data.items() if key in _FLAG_EVIDENCE_FIELDS
    }


def _flags_for_ordinals(
    state: RepairState, ordinals: Iterable[int]
) -> tuple[RepairAction, ...]:
    flags: list[RepairAction] = []
    seen: set[str] = set()
    for ordinal in ordinals:
        flag = _flag_for_ordinal(state, ordinal)
        if flag is None:
            continue
        identity = _action_identity(flag)
        if identity not in seen:
            flags.append(flag)
            seen.add(identity)
    return tuple(flags)


def _resolve_flags_action(
    state: RepairState, region: ReviewRegion
) -> RepairAction | None:
    flags = _flags_for_ordinals(state, region.flagged_ordinals)
    if not flags:
        return None
    relation_ids = tuple(
        state.snapshot.relation_id(value) for value in region.flagged_ordinals
    )
    return RepairAction.make_ok(
        relation_ids,
        source="ai",
        resolved_flag_actions=[flag.to_dict() for flag in flags],
    )


def _with_resolved_flags(
    action: RepairAction, state: RepairState, region: ReviewRegion
) -> RepairAction:
    """Make flag resolution an atomic side effect of a content decision."""

    flags = _flags_for_ordinals(state, region.flagged_ordinals)
    if not flags:
        return action
    resolved = _copy_action(action)
    resolved.data["resolved_flag_actions"] = [flag.to_dict() for flag in flags]
    return resolved


def _should_resolve_flags(args: dict) -> bool:
    """Interpret the keep-oriented contract and legacy recorded tool calls."""
    if "keep_flags" in args:
        return not bool(args["keep_flags"])
    return bool(args.get("resolve_flags", False))


def _content_actions_for_region(
    state: RepairState, relation_ids: set[str]
) -> tuple[RepairAction, ...]:
    actions: list[RepairAction] = []
    seen: set[str] = set()
    for action in state.repair_log:
        if action.kind not in _CONTENT_KINDS:
            continue
        if not relation_ids.intersection(action.relation_ids):
            continue
        identity = _action_identity(action)
        if identity in seen:
            continue
        seen.add(identity)
        actions.append(_copy_action(action))
    return tuple(actions)


def _candidate(
    candidate_id: str,
    label: str,
    actions: tuple[RepairAction, ...],
    after_state: RepairState,
    ordinals: tuple[int, ...],
    *,
    strategy: str,
    initial_rows: tuple[dict, ...],
    requires_action: bool = False,
) -> ReviewCandidate:
    rows = _rows_for_ordinals(after_state, ordinals)
    view = _pairwise_view_for_ordinals(after_state, ordinals)
    validation_issues = list(_candidate_validation_issues(rows))
    if not actions and any(
        len(after_state.snapshot.original_ops[ordinal][0]) != 1
        or len(after_state.snapshot.original_ops[ordinal][1]) != 1
        for ordinal in ordinals
    ):
        validation_issues.append("unchanged_non_1to1_structure")
    if requires_action and not actions:
        validation_issues.append("unresolved_user_flag")
    if strategy == "src":
        strategy_fit = (
            "preserves_document_a_structure"
            if _side_structure(rows, "src") == _side_structure(initial_rows, "src")
            else "changes_document_a_structure"
        )
    elif strategy == "tgt":
        strategy_fit = (
            "preserves_document_b_structure"
            if _side_structure(rows, "tgt") == _side_structure(initial_rows, "tgt")
            else "changes_document_b_structure"
        )
    else:
        changed_sides = sum(
            _side_structure(rows, side) != _side_structure(initial_rows, side)
            for side in ("src", "tgt")
        )
        strategy_fit = f"changed_structure_sides:{changed_sides}"
    return ReviewCandidate(
        candidate_id=candidate_id,
        label=label,
        origin=_origin(actions),
        actions=actions,
        after_rows=rows,
        after_view=view,
        strategy_fit=strategy_fit,
        validation_issues=tuple(validation_issues),
    )


def _alternative_merge_candidate(
    state: RepairState,
    ordinals: tuple[int, ...],
    evidence: dict,
    *,
    strategy: str,
    initial_rows: tuple[dict, ...],
) -> ReviewCandidate | None:
    alternative = str(evidence.get("alternative_structure", ""))
    current = str(evidence.get("current_structure", ""))
    if not alternative or "+" in alternative or alternative == current:
        return None
    try:
        source_count, target_count = (int(value) for value in alternative.split(":"))
    except (TypeError, ValueError):
        return None
    lattice = evidence.get("uncertain_region", {})
    start = lattice.get("start", {})
    end = lattice.get("end", {})
    try:
        expected = (
            int(end["source"]) - int(start["source"]),
            int(end["target"]) - int(start["target"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (source_count, target_count) != expected or len(ordinals) < 2:
        return None
    relation_ids = tuple(state.snapshot.relation_id(value) for value in ordinals)
    action = RepairAction.make_merge(
        relation_ids,
        sub_count=max(source_count, target_count, 1),
        source="auto",
        candidate_origin="alignment_alternative",
        review_region=evidence.get("uncertain_region", {}),
    )
    after_state = state.apply(action)
    return _candidate(
        "alignment-alternative",
        f"采用备选路径 {alternative}",
        (action,),
        after_state,
        ordinals,
        strategy=strategy,
        initial_rows=initial_rows,
    )


def _region_id(ordinals: tuple[int, ...], evidence: dict) -> str:
    seed = json.dumps(
        {"ordinals": ordinals, "evidence": evidence},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"R{ordinals[0]}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:8]}"


def build_review_regions(
    state: RepairState, reviewable_ids: Iterable[int], strategy: str = "src"
) -> tuple[ReviewRegion, ...]:
    """Build disjoint semantic review regions from relation triggers and flags."""

    valid = sorted(
        {
            int(value)
            for value in reviewable_ids
            if 0 <= int(value) < len(state.snapshot.original_ops)
        }
    )
    relation_statuses = project_relation_statuses(state)
    grouped: dict[str, dict] = {}
    for ordinal in valid:
        flag = _flag_for_ordinal(state, ordinal)
        data = _flag_evidence(flag)
        lattice = (
            data.get("uncertain_region")
            if data.get("reason") == "composition_disagreement"
            else None
        )
        key = (
            "composition:" + json.dumps(lattice, ensure_ascii=False, sort_keys=True)
            if isinstance(lattice, dict)
            else f"relation:{ordinal}"
        )
        entry = grouped.setdefault(key, {"triggers": [], "evidence": data})
        entry["triggers"].append(ordinal)

    regions: list[ReviewRegion] = []
    for entry in grouped.values():
        triggers = tuple(sorted(set(entry["triggers"])))
        evidence = dict(entry["evidence"])
        ordinals = (
            _ordinals_in_lattice_region(state, evidence["uncertain_region"])
            if evidence.get("uncertain_region")
            else triggers
        )
        if not ordinals:
            ordinals = triggers

        # An existing multi-relation action defines a wider coherent scope than
        # a single trigger. Expand once so candidate application stays atomic.
        expanded = set(ordinals)
        region_ids = {state.snapshot.relation_id(value) for value in expanded}
        for action in state.repair_log:
            if action.kind in _CONTENT_KINDS and region_ids.intersection(
                action.relation_ids
            ):
                expanded.update(state.snapshot.operation_indices(action.relation_ids))
        ordinals = tuple(sorted(expanded))
        relation_ids = {state.snapshot.relation_id(value) for value in ordinals}
        open_flag_actions = tuple(
            (ordinal, flag)
            for ordinal in ordinals
            if (flag := _flag_for_ordinal(state, ordinal)) is not None
        )
        flagged_ordinals = tuple(ordinal for ordinal, _flag in open_flag_actions)
        open_flags = tuple(
            {
                "relation": ordinal,
                "source": flag.source or "unknown",
                "note": str(flag.data.get("note", "") or ""),
            }
            for ordinal, flag in open_flag_actions
        )
        current_actions = _content_actions_for_region(state, relation_ids)
        candidates: list[ReviewCandidate] = []
        initial_rows = _rows_for_ordinals(RepairState(state.snapshot), ordinals)
        user_flag_requires_action = any(
            flag.source == "user" and str(flag.data.get("note", "") or "").strip()
            for _ordinal, flag in open_flag_actions
        )

        current = _candidate(
            "current",
            "保留当前拟修复" if current_actions else "确认当前原始关系",
            current_actions,
            state,
            ordinals,
            strategy=strategy,
            initial_rows=initial_rows,
            requires_action=user_flag_requires_action,
        )
        if not current.validation_issues:
            candidates.append(current)

        alternative = _alternative_merge_candidate(
            state,
            ordinals,
            evidence,
            strategy=strategy,
            initial_rows=initial_rows,
        )
        strategy_conflict = alternative is not None and alternative.strategy_fit in {
            "changes_document_a_structure",
            "changes_document_b_structure",
        }
        if (
            alternative is not None
            and not alternative.validation_issues
            and alternative.after_rows != current.after_rows
            and not strategy_conflict
        ):
            candidates.append(alternative)

        regions.append(
            ReviewRegion(
                region_id=_region_id(ordinals, evidence),
                ordinals=ordinals,
                trigger_ordinals=triggers,
                flagged_ordinals=flagged_ordinals,
                evidence=evidence,
                initial_rows=initial_rows,
                current_rows=_rows_for_ordinals(state, ordinals),
                relation_states=tuple(
                    _relation_state_payload(ordinal, relation_statuses[ordinal])
                    for ordinal in ordinals
                ),
                open_flags=open_flags,
                candidates=tuple(candidates),
            )
        )
    return tuple(sorted(regions, key=lambda region: region.ordinals))


@dataclass
class RegionReviewExecutor:
    """Atomic executor used by the production Agent tool loop."""

    state: RepairState
    reviewable_ids: tuple[int, ...]
    strategy: str = "src"
    regions: tuple[ReviewRegion, ...] = field(init=False)
    reviewed_ids: set[int] = field(default_factory=set, init=False)
    touched_ids: set[int] = field(default_factory=set, init=False)
    actions: list[RepairAction] = field(default_factory=list, init=False)
    resolved_regions: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self.regions = build_review_regions(
            self.state, self.reviewable_ids, strategy=self.strategy
        )
        self._by_id = {region.region_id: region for region in self.regions}

    @property
    def pending_region_ids(self) -> tuple[str, ...]:
        return tuple(
            region.region_id
            for region in self.regions
            if region.region_id not in self.resolved_regions
        )

    def initial_payload(self, context_window: int = 3) -> dict:
        context_by_relation: dict[int, dict] = {}
        region_payloads: list[dict] = []
        for region in self.regions:
            context_relations: list[int] = []
            for row in self._context_rows(region, context_window, context_window):
                ordinal = int(row["relation"])
                if ordinal in region.ordinals:
                    continue
                context_by_relation.setdefault(ordinal, row)
                context_relations.append(ordinal)
            region_payloads.append(
                {
                    **region.to_payload(),
                    "context_relations": context_relations,
                }
            )
        return {
            "review_regions": region_payloads,
            "context_rows": [
                context_by_relation[ordinal] for ordinal in sorted(context_by_relation)
            ],
        }

    def _context_rows(
        self, region: ReviewRegion, before: int, after: int
    ) -> list[dict]:
        start = max(0, min(region.ordinals) - max(0, before))
        end = min(
            len(self.state.snapshot.original_ops) - 1,
            max(region.ordinals) + max(0, after),
        )
        return list(_rows_for_ordinals(self.state, range(start, end + 1)))

    def _region(self, args: dict) -> ReviewRegion | None:
        return self._by_id.get(str(args.get("region_id", "")))

    def _edit_scope(self, region: ReviewRegion, args: dict) -> tuple[int, ...] | str:
        """Validate an optional contiguous expansion into visible context."""

        raw = args.get("relations")
        if raw is None:
            return region.ordinals
        if not isinstance(raw, list) or not raw:
            return "relations must be a non-empty integer array"
        if any(not isinstance(value, int) or isinstance(value, bool) for value in raw):
            return "relations must be a non-empty integer array"
        requested = tuple(raw)
        if requested != tuple(sorted(set(requested))):
            return "relations must be unique and ordered"
        if requested != tuple(range(requested[0], requested[-1] + 1)):
            return "relations must form one contiguous range"
        if not set(region.ordinals).issubset(requested):
            return "relations must include the complete review region"
        if requested[0] < 0 or requested[-1] >= len(self.state.snapshot.original_ops):
            return "relations contain an unknown relation"
        if (
            requested[0] < min(region.ordinals) - 10
            or requested[-1] > max(region.ordinals) + 10
        ):
            return "relations may expand by at most 10 neighbors on either side"
        for other in self.regions:
            if other.region_id == region.region_id:
                continue
            if set(requested).intersection(other.ordinals):
                return "relations overlap another review region"
        return requested

    def _progress(self) -> dict:
        return {
            "resolved_regions": len(self.resolved_regions),
            "total_regions": len(self.regions),
            "remaining_regions": list(self.pending_region_ids),
            "touched_relations": sorted(self.touched_ids),
        }

    def execute(self, name: str, args: dict) -> str:
        handler = getattr(self, f"_handle_{name}", None)
        if handler is None:
            return json.dumps(
                {"error": f"unknown region tool: {name}"}, ensure_ascii=False
            )
        try:
            return handler(args)
        except Exception as exc:  # noqa: BLE001 - tool boundary
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def _handle_inspect_region(self, args: dict) -> str:
        region = self._region(args)
        if region is None:
            return "❌ unknown region_id"
        before = min(max(int(args.get("before", 3)), 0), 10)
        after = min(max(int(args.get("after", 3)), 0), 10)
        payload = region.to_payload()
        payload["context"] = self._context_rows(region, before, after)
        payload["resolved"] = region.region_id in self.resolved_regions
        return json.dumps(payload, ensure_ascii=False)

    def _handle_accept_candidate(self, args: dict) -> str:
        region = self._region(args)
        if region is None:
            return "❌ unknown region_id"
        if region.region_id in self.resolved_regions:
            return "❌ region already resolved"
        candidate_id = str(args.get("candidate_id", ""))
        candidate = next(
            (item for item in region.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            return "❌ unknown candidate_id"
        if candidate.validation_issues:
            return "❌ candidate is not publishable: " + ", ".join(
                candidate.validation_issues
            )
        accepted = tuple(
            _copy_action(action, reviewed_by="ai") for action in candidate.actions
        )
        resolve_flags = _should_resolve_flags(args)
        decisions = list(accepted)
        if resolve_flags and region.flagged_ordinals:
            if decisions:
                decisions[0] = _with_resolved_flags(decisions[0], self.state, region)
            else:
                resolution = _resolve_flags_action(self.state, region)
                if resolution is not None:
                    decisions.append(resolution)
        elif not accepted and region.flagged_ordinals:
            decisions.extend(
                _copy_action(action, reviewed_by="ai")
                for action in _flags_for_ordinals(self.state, region.flagged_ordinals)
            )
        elif not accepted:
            relation_ids = tuple(
                self.state.snapshot.relation_id(value)
                for value in region.trigger_ordinals
            )
            decisions.append(RepairAction.make_ok(relation_ids, source="ai"))
        self.actions.extend(decisions)
        self.resolved_regions.add(region.region_id)
        self.reviewed_ids.update(region.trigger_ordinals)
        self.touched_ids.update(region.ordinals)
        payload = {
            "status": "applied",
            "region_id": region.region_id,
            "candidate_id": candidate.candidate_id,
            "origin_preserved": candidate.origin,
            "flags_resolved": resolve_flags and bool(region.flagged_ordinals),
            "final_rows": list(candidate.after_rows),
            **self._progress(),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _handle_edit_region(self, args: dict) -> str:
        region = self._region(args)
        if region is None:
            return "❌ unknown region_id"
        if region.region_id in self.resolved_regions:
            return "❌ region already resolved"
        edit_scope = self._edit_scope(region, args)
        if isinstance(edit_scope, str):
            return f"❌ {edit_scope}"
        raw_units = args.get("units")
        if not isinstance(raw_units, list) or not raw_units:
            return "❌ units must be a non-empty array"
        try:
            final_units = [
                ReviewUnit.from_tool_payload(item, path=f"units[{index}]")
                for index, item in enumerate(raw_units)
            ]
        except ValueError as exc:
            return f"❌ {exc}"

        # Keep exact unchanged edge relations out of the compiled edit.  The
        # LLM edits one semantic region atomically, while provenance and GUI
        # markers should still describe only the relations it actually changed.
        changed_ordinals = list(edit_scope)

        def current_units(ordinal: int) -> list[ReviewUnit] | None:
            group = self.state.current.group(ordinal)
            if group is None:
                return None
            rows = tuple(group.rows)
            if not rows:
                return None
            if any(
                row.cur_type != "1:1" or not row.src_text or not row.tgt_text
                for row in rows
            ):
                # Keeping the same words can still be a real edit when it
                # normalizes an unresolved N:M/empty-side layout into complete
                # publishable units. Do not trim that structural change away.
                return None
            marker = rows[0].marker
            try:
                if is_edit(marker) or is_split(marker):
                    return [
                        ReviewUnit.from_tool_payload(
                            {"src": [row.src_text], "tgt": [row.tgt_text]},
                            path=f"current[{ordinal}][{index}]",
                        )
                        for index, row in enumerate(rows)
                    ]
                return [
                    ReviewUnit.from_tool_payload(
                        {
                            "src": [row.src_text for row in rows if row.src_text],
                            "tgt": [row.tgt_text for row in rows if row.tgt_text],
                        },
                        path=f"current[{ordinal}]",
                    )
                ]
            except ValueError:
                return None

        while changed_ordinals:
            units = current_units(changed_ordinals[0])
            if not units or final_units[: len(units)] != units:
                break
            del final_units[: len(units)]
            changed_ordinals.pop(0)
        while changed_ordinals:
            units = current_units(changed_ordinals[-1])
            if not units or final_units[-len(units) :] != units:
                break
            del final_units[-len(units) :]
            changed_ordinals.pop()
        if not changed_ordinals or not final_units:
            return (
                "❌ submitted units do not define a non-empty edit; use delete_region"
            )

        final_pairs = [unit.compiled_pair() for unit in final_units]
        source = [src for src, _tgt in final_pairs]
        target = [tgt for _src, tgt in final_pairs]
        relation_ids = tuple(
            self.state.snapshot.relation_id(value) for value in changed_ordinals
        )
        action = RepairAction.make_edit(
            relation_ids,
            source="ai",
            new_src_lines=source,
            new_tgt_lines=target,
            review_region=region.region_id,
            reason=str(args.get("reason", "")),
        )
        resolve_flags = _should_resolve_flags(args)
        if resolve_flags and region.flagged_ordinals:
            action = _with_resolved_flags(action, self.state, region)
        self.actions.append(action)
        self.resolved_regions.add(region.region_id)
        self.reviewed_ids.update(region.trigger_ordinals)
        self.touched_ids.update(changed_ordinals)
        return json.dumps(
            {
                "status": "applied",
                "region_id": region.region_id,
                "origin": "ai",
                "flags_resolved": resolve_flags and bool(region.flagged_ordinals),
                "final_units": [unit.to_payload() for unit in final_units],
                **self._progress(),
            },
            ensure_ascii=False,
        )

    def _handle_delete_region(self, args: dict) -> str:
        region = self._region(args)
        if region is None:
            return "❌ unknown region_id"
        if region.region_id in self.resolved_regions:
            return "❌ region already resolved"
        relation_ids = tuple(
            self.state.snapshot.relation_id(value) for value in region.ordinals
        )
        action = RepairAction.make_delete(
            relation_ids,
            source="ai",
            review_region=region.region_id,
            reason=str(args.get("reason", "")),
        )
        resolve_flags = _should_resolve_flags(args)
        if resolve_flags and region.flagged_ordinals:
            action = _with_resolved_flags(action, self.state, region)
        self.actions.append(action)
        self.resolved_regions.add(region.region_id)
        self.reviewed_ids.update(region.trigger_ordinals)
        self.touched_ids.update(region.ordinals)
        return json.dumps(
            {
                "status": "deleted",
                "region_id": region.region_id,
                "origin": "ai",
                "flags_resolved": resolve_flags and bool(region.flagged_ordinals),
                "final_rows": [],
                **self._progress(),
            },
            ensure_ascii=False,
        )

    def _handle_replace_region(self, args: dict) -> str:
        """Compatibility alias; production advertises ``edit_region``."""
        if "units" not in args and isinstance(args.get("rows"), list):
            args = {
                **args,
                "units": [
                    (
                        {
                            "src": [row.get("src", "")],
                            "tgt": [row.get("tgt", "")],
                        }
                        if isinstance(row, dict)
                        else row
                    )
                    for row in args["rows"]
                ],
            }
        return self._handle_edit_region(args)

    def _handle_defer_region(self, args: dict) -> str:
        region = self._region(args)
        if region is None:
            return "❌ unknown region_id"
        if region.region_id in self.resolved_regions:
            return "❌ region already resolved"
        reason = str(args.get("reason", ""))
        existing_flags = _flags_for_ordinals(self.state, region.flagged_ordinals)
        if existing_flags:
            for flag in existing_flags:
                preserved = _copy_action(flag, reviewed_by="ai")
                preserved.data["ai_review_note"] = reason
                self.actions.append(preserved)
        else:
            relation_ids = tuple(
                self.state.snapshot.relation_id(value)
                for value in region.trigger_ordinals
            )
            self.actions.append(
                RepairAction.make_flag(
                    relation_ids,
                    note=reason,
                    source="ai",
                    review_region=region.region_id,
                )
            )
        self.resolved_regions.add(region.region_id)
        self.reviewed_ids.update(region.trigger_ordinals)
        return json.dumps(
            {"status": "deferred", "region_id": region.region_id, **self._progress()},
            ensure_ascii=False,
        )

    def _handle_finish_review(self, _args: dict) -> str:
        if self.pending_region_ids:
            return "❌ unresolved review regions: " + ", ".join(self.pending_region_ids)
        return json.dumps(
            {"status": "finished", **self._progress()}, ensure_ascii=False
        )

    def unique_actions(self) -> list[RepairAction]:
        result: list[RepairAction] = []
        seen: set[str] = set()
        for action in self.actions:
            identity = _action_identity(action)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(action)
        return result
