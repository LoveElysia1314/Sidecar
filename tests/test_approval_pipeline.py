"""
Dualign — Approval 四态管线测试

none → auto → agent → user（递进）
flag 不推进管线。
"""

import pytest
from dualign.models.state import AlignmentSnapshot
from dualign.models.action import RepairAction
from dualign.services.repair import RepairState, RepairService
from dualign.models.relation_status import (
    project_relation_statuses,
    _derive_approval,
    APPROVAL_NONE,
    APPROVAL_PROPOSED,
    APPROVAL_AGENT,
    APPROVAL_USER,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def two_snap_snapshot():
    """snap 0: 1:1, snap 1: 1:2（待 auto_repair）。"""
    ops = [
        ((0,), (0,), 0.95),
        ((1,), (1, 2), 0.60),
    ]
    return AlignmentSnapshot.from_alignment(
        ops,
        ["锚点", "异常原文"],
        ["锚点译文", "异常译文行1", "异常译文行2"],
    )


@pytest.fixture
def raw_state(two_snap_snapshot):
    return RepairState(two_snap_snapshot)


def _build_states(state):
    return project_relation_statuses(state)


# ═══════════════════════════════════════════════════════════════
# _derive_approval 单元测试
# ═══════════════════════════════════════════════════════════════


class TestDeriveApproval:
    def test_none_when_no_action(self):
        assert _derive_approval(None) == APPROVAL_NONE

    def test_auto_source(self):
        a = RepairAction(kind="merge", relation_ids=("L000001",), source="auto")
        assert _derive_approval(a) == APPROVAL_PROPOSED

    def test_ai_source(self):
        a = RepairAction(kind="ok", relation_ids=("L000001",), source="ai")
        assert _derive_approval(a) == APPROVAL_AGENT

    def test_user_source(self):
        a = RepairAction(kind="ok", relation_ids=("L000001",), source="user")
        assert _derive_approval(a) == APPROVAL_USER

    def test_flag_does_not_advance(self):
        """flag 不推进管线。"""
        a = RepairAction(kind="flag", relation_ids=("L000001",), source="ai")
        assert _derive_approval(a) == APPROVAL_NONE

        a2 = RepairAction(kind="flag", relation_ids=("L000001",), source="user")
        assert _derive_approval(a2) == APPROVAL_NONE

    def test_empty_source_is_auto(self):
        """兼容旧 source=""。"""
        a = RepairAction(kind="merge", relation_ids=("L000001",), source="")
        assert _derive_approval(a) == APPROVAL_PROPOSED


# ═══════════════════════════════════════════════════════════════
# 四态管线推进
# ═══════════════════════════════════════════════════════════════


class TestApprovalPipeline:
    """none → auto → agent → user"""

    def test_initial_is_none(self, raw_state):
        states = _build_states(raw_state)
        # snap 0: 1:1 正常锚点，无 repair → none
        assert (
            states[0].approval == APPROVAL_NONE
            if states[0].initial_anomaly_types == []
            else states[0].approval
        )
        # snap 1: 1:2，无 repair → none
        assert states[1].approval == APPROVAL_NONE

    def test_auto_repair_advances_to_auto(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        states = _build_states(repaired)
        # snap 1: 1:2 → merge(auto) → AUTO
        assert states[1].approval == APPROVAL_PROPOSED

    def test_ai_ok_advances_to_agent(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(repaired.make_action("ok", 1, source="ai"))
        states = _build_states(s2)
        assert states[1].approval == APPROVAL_AGENT

    def test_ai_edit_advances_to_agent(self, raw_state):
        """AI 直接 edit（覆盖 auto_repair）→ AGENT。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(
            repaired.make_action(
                "edit", 1, source="ai", new_tgt_lines=["修正1", "修正2"]
            )
        )
        states = _build_states(s2)
        assert states[1].approval == APPROVAL_AGENT

    def test_human_ok_advances_to_user(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(repaired.make_action("ok", 1, source="user"))
        states = _build_states(s2)
        assert states[1].approval == APPROVAL_USER

    def test_human_overrides_ai(self, raw_state):
        """auto → agent → user：AI ok 后人类 ok → approval=USER。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        # AI ok
        s2 = repaired.apply(repaired.make_action("ok", 1, source="ai"))
        states2 = _build_states(s2)
        assert states2[1].approval == APPROVAL_AGENT
        # 人类 ok 覆盖
        s3 = s2.apply(s2.make_action("ok", 1, source="user"))
        states3 = _build_states(s3)
        assert states3[1].approval == APPROVAL_USER

    def test_flag_no_advance(self, raw_state):
        """auto → flag(ai) → 仍为 AUTO。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(repaired.make_action("flag", 1, source="ai"))
        states = _build_states(s2)
        assert states[1].approval == APPROVAL_PROPOSED
        assert states[1].is_flagged
        # 人类 flag 同样不推进
        s3 = s2.apply(s2.make_action("flag", 1, source="user"))
        states3 = _build_states(s3)
        assert states3[1].approval == APPROVAL_PROPOSED
        assert states3[1].is_flagged


# ═══════════════════════════════════════════════════════════════
# AI ok 不丢失 auto_repair 操作
# ═══════════════════════════════════════════════════════════════


class TestAiOkPreservesAutoRepair:
    """AI ok 应保留 auto_repair 操作，而非覆盖。"""

    def test_auto_repair_is_preserved_after_ai_ok(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        log_before = [
            (repaired.action_ordinal(a), a.kind, a.source) for a in repaired.repair_log
        ]
        s2 = repaired.apply(repaired.make_action("ok", 1, source="ai"))
        log_after = [(s2.action_ordinal(a), a.kind, a.source) for a in s2.repair_log]

        # auto_repair 操作仍在
        assert len(log_after) == len(log_before) + 1, (
            f"AI ok should add to repair_log, not wipe auto_repair. "
            f"before={log_before}, after={log_after}"
        )
        # AI ok 是最后一条
        assert log_after[-1] == (1, "ok", "ai")

    def test_ai_edit_overrides_auto_repair(self, raw_state):
        """AI edit 应清除 auto_repair 操作（覆盖语义）。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(
            repaired.make_action("edit", 1, source="ai", new_tgt_lines=["修正1"])
        )
        log_after = [(s2.action_ordinal(a), a.kind, a.source) for a in s2.repair_log]
        # auto_repair 的 merge 被清除，只剩 edit
        assert log_after == [(1, "edit", "ai")], f"edit should override: {log_after}"
