"""
Dualign — RepairAction + AiProposalStore

操作分类:
  info-free (仅存 marker): merge, delete, placeholder, flag, ok
  info-full (存完整文本):   split, edit
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional

from dualign.models.marker import from_kind as _marker_from_kind

# ── 有效操作类型 ──
_VALID_KINDS = frozenset(
    {
        "merge",
        "split",
        "edit",
        "delete",
        "flag",
        "ok",
        "placeholder_src",
        "placeholder_tgt",
    }
)


def canonicalize_action_payload(
    payload: Mapping[str, Any], relation_ids: tuple[str, ...]
) -> dict[str, Any]:
    """Bind a serialized action to stable IDs and remove legacy positions.

    Positional fields are accepted only at the report boundary. Every caller
    receives the same ID-only representation, including a copied ``data``
    mapping that no longer contains the historical ``orig_snaps`` field.
    """

    result = dict(payload)
    raw_data = result.get("data")
    data = dict(raw_data) if isinstance(raw_data, Mapping) else {}
    raw_ids = result.get("relation_ids") or ()
    if isinstance(raw_ids, (str, bytes)):
        raw_ids = ()
    target_ids = list(dict.fromkeys(str(value) for value in raw_ids))
    if not target_ids:
        raw_positions = (
            result.get("operation_indices")
            or data.get("orig_snaps")
            or (result.get("op_index"),)
        )
        if not isinstance(raw_positions, (list, tuple)):
            raw_positions = (raw_positions,)
        for value in raw_positions:
            try:
                ordinal = int(value)
                relation_id = relation_ids[ordinal]
            except (IndexError, TypeError, ValueError):
                continue
            if ordinal >= 0 and relation_id not in target_ids:
                target_ids.append(relation_id)
    if not target_ids or any(value not in relation_ids for value in target_ids):
        raise ValueError("修复动作无法绑定到当前关系身份")
    result["relation_ids"] = target_ids
    result.pop("op_index", None)
    result.pop("operation_indices", None)
    data.pop("orig_snaps", None)
    result["data"] = data
    return result


@dataclass
class RepairAction:
    """单一修复操作。

    kind:          操作类型 (merge|split|edit|delete|flag|ok|placeholder_src|placeholder_tgt)
    sub_count:     合并行数（仅 merge 使用）
    source:        来源: "auto"(CLI自动修复) / "ai"(AI Agent) / "user"(GUI手动)
    data:          附加数据（info-full 时存 new_src_lines/new_tgt_lines/scores；
                   不保存关系身份或位置）
    timestamp:     ISO 时间戳
    relation_ids:  稳定关系身份
    """

    kind: str
    sub_count: int = 1
    source: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    relation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in _VALID_KINDS:
            raise ValueError(f"未知操作类型: {self.kind}")
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.source:
            self.source = "auto"
        normalized_ids = tuple(str(value).strip() for value in self.relation_ids)
        if not normalized_ids or any(not value for value in normalized_ids):
            raise ValueError("关系 ID 不能为空")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("修复动作中的关系 ID 必须唯一")
        self.relation_ids = normalized_ids

    @property
    def marker(self) -> str:
        """返回带来源前缀的 marker 字符串。

        委托给 marker.py 的 from_kind() 统一管理。
        """
        return _marker_from_kind(self.kind, self.source)

    @property
    def is_merge(self) -> bool:
        """是否为合并操作。"""
        return self.kind == "merge"

    # ── Factory methods ──

    @classmethod
    def _make(
        cls,
        relation_ids: str | Iterable[str],
        kind: str,
        *,
        sub_count: int = 1,
        **values: Any,
    ) -> RepairAction:
        """Construct an action while keeping metadata out of action data."""

        if isinstance(relation_ids, str):
            relation_ids = (relation_ids,)
        source = str(values.pop("source", ""))
        timestamp = str(values.pop("timestamp", ""))
        return cls(
            kind=kind,
            sub_count=sub_count,
            source=source,
            data=values,
            timestamp=timestamp,
            relation_ids=tuple(relation_ids),
        )

    @classmethod
    def make_merge(
        cls, relation_ids: str | Iterable[str], sub_count: int = 1, **kw
    ) -> RepairAction:
        return cls._make(relation_ids, "merge", sub_count=sub_count, **kw)

    @classmethod
    def make_split(cls, relation_ids: str | Iterable[str], **kw) -> RepairAction:
        return cls._make(relation_ids, "split", **kw)

    @classmethod
    def make_edit(cls, relation_ids: str | Iterable[str], **kw) -> RepairAction:
        return cls._make(relation_ids, "edit", **kw)

    @classmethod
    def make_delete(cls, relation_ids: str | Iterable[str], **kw) -> RepairAction:
        return cls._make(relation_ids, "delete", **kw)

    @classmethod
    def make_flag(
        cls, relation_ids: str | Iterable[str], note: str = "", **kw
    ) -> RepairAction:
        return cls._make(relation_ids, "flag", note=note, **kw)

    @classmethod
    def make_ok(cls, relation_ids: str | Iterable[str], **kw) -> RepairAction:
        return cls._make(relation_ids, "ok", **kw)

    @classmethod
    def make_placeholder_src(
        cls, relation_ids: str | Iterable[str], **kw
    ) -> RepairAction:
        return cls._make(relation_ids, "placeholder_src", **kw)

    @classmethod
    def make_placeholder_tgt(
        cls, relation_ids: str | Iterable[str], **kw
    ) -> RepairAction:
        return cls._make(relation_ids, "placeholder_tgt", **kw)

    # ── 序列化 ──

    def to_dict(self) -> dict:
        d: Dict[str, Any] = {
            "kind": self.kind,
            "sub_count": self.sub_count,
            "source": self.source,
            "data": {},
            "timestamp": self.timestamp,
        }
        d["relation_ids"] = list(self.relation_ids)
        for k, v in self.data.items():
            d["data"][k] = sorted(v) if isinstance(v, set) else v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> RepairAction:
        data = dict(d.get("data") or {})
        relation_ids = tuple(
            d.get("relation_ids") or data.pop("relation_ids", ()) or ()
        )
        source = d.get("source", "") or data.pop("source", "")
        return cls(
            kind=d["kind"],
            sub_count=d.get("sub_count", 1),
            source=source,
            data=data,
            timestamp=d.get("timestamp", ""),
            relation_ids=relation_ids,
        )


# ═══════════════════════════════════════════════════════════════
# AiProposal — AI 建议单条记录
# ═══════════════════════════════════════════════════════════════


@dataclass
class AiProposal:
    """单条 AI 建议的完整记录。

    action:   AI 生成的 RepairAction
    status:   "pending" | "accepted" | "rejected"
    created_at: ISO 时间戳
    resolved_at: ISO 时间戳 (采纳/忽略后设置)
    summary:  简短描述文本（用于卡片显示）
    """

    action: RepairAction
    status: str = "pending"
    created_at: str = ""
    resolved_at: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def accept(self) -> None:
        self.status = "accepted"
        self.resolved_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def reject(self) -> None:
        self.status = "rejected"
        self.resolved_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def reset(self) -> None:
        self.status = "pending"
        self.resolved_at = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action.to_dict(),
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Optional[AiProposal]:
        try:
            action = RepairAction.from_dict(d["action"])
            return cls(
                action=action,
                status=d.get("status", "pending"),
                created_at=d.get("created_at", ""),
                resolved_at=d.get("resolved_at", ""),
                summary=d.get("summary", ""),
            )
        except Exception:
            return None


@dataclass
class AiProposalStore:
    """AI 建议持久化存储。按稳定关系 ID 分组。

    独立于 repair_log——重置修复不会丢失 AI 建议。
    """

    proposals: Dict[str, List[AiProposal]] = field(default_factory=dict)

    @staticmethod
    def _relation_id(action: RepairAction) -> str:
        if not action.relation_ids:
            raise ValueError("AI 建议动作必须先绑定稳定关系 ID")
        return action.relation_ids[0]

    @staticmethod
    def _find(
        proposals: List[AiProposal], action: RepairAction
    ) -> Optional[AiProposal]:
        """Return the proposal matching an action's stable identity."""
        for proposal in proposals:
            if (
                proposal.action.relation_ids == action.relation_ids
                and proposal.action.kind == action.kind
            ):
                return proposal
        return None

    def add(self, action: RepairAction, summary: str = "") -> None:
        """Add one identity-bound AI proposal."""

        relation_id = self._relation_id(action)
        existing = self.proposals.get(relation_id, [])
        for proposal in existing:
            if proposal.action.kind != action.kind:
                continue
            if proposal.status == "accepted":
                return
            if proposal.status == "pending":
                proposal.action = action
                proposal.summary = summary
                proposal.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                return
        prop = AiProposal(action=action, summary=summary)
        self.proposals.setdefault(relation_id, []).append(prop)

    def get(self, relation_id: str) -> List[AiProposal]:
        return self.proposals.get(relation_id, [])

    def get_pending(self) -> List[AiProposal]:
        result = []
        for props in self.proposals.values():
            for p in props:
                if p.status == "pending":
                    result.append(p)
        return result

    def accept(self, action: RepairAction) -> bool:
        proposal = self._find(self.proposals.get(self._relation_id(action), []), action)
        if proposal is None:
            return False
        proposal.accept()
        return True

    def reject(self, action: RepairAction) -> bool:
        proposal = self._find(self.proposals.get(self._relation_id(action), []), action)
        if proposal is None:
            return False
        proposal.reject()
        return True

    def restore(self, action: RepairAction) -> bool:
        proposal = self._find(self.proposals.get(self._relation_id(action), []), action)
        if proposal is None:
            return False
        proposal.reset()
        return True

    def reset(self, relation_id: str) -> None:
        for p in self.proposals.get(relation_id, []):
            p.reset()

    def get_status(self, action: RepairAction) -> str | None:
        proposal = self._find(self.proposals.get(self._relation_id(action), []), action)
        return proposal.status if proposal is not None else None

    def validated_copy(self, validator) -> AiProposalStore:
        """Validate proposal identities and regroup them by their stable anchor."""

        validated = AiProposalStore()
        for props in self.proposals.values():
            for proposal in props:
                action = validator(proposal.action)
                validated.proposals.setdefault(action.relation_ids[0], []).append(
                    replace(proposal, action=action)
                )
        return validated

    def to_dict(self) -> dict:
        return {
            relation_id: [p.to_dict() for p in props]
            for relation_id, props in self.proposals.items()
        }

    @classmethod
    def from_dict(cls, d: dict) -> AiProposalStore:
        store = cls()
        try:
            for raw_key, props_list in d.items():
                key = str(raw_key)
                for pd in props_list:
                    prop = AiProposal.from_dict(pd)
                    if prop is not None:
                        store.proposals.setdefault(key, []).append(prop)
        except Exception:
            pass
        return store
