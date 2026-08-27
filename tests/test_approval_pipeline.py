"""Effective-source projection tests.

Unchanged decisions may advance none → auto → ai → user. A material change
belongs to the actor who made it, while flags remain orthogonal.
"""

import pytest
from dualign.models.state import AlignmentSnapshot
from dualign.models.action import RepairAction
from dualign.services.repair import RepairState, RepairService
from dualign.models.relation_status import (
    project_relation_statuses,
    derive_effective_source,
)
from dualign.models.source import SOURCE_AI, SOURCE_AUTO, SOURCE_NONE, SOURCE_USER

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
# derive_effective_source 单元测试
# ═══════════════════════════════════════════════════════════════


class TestDeriveEffectiveSource:
    def test_none_when_no_action(self):
        assert derive_effective_source(None) == SOURCE_NONE

    def test_auto_source(self):
        a = RepairAction(kind="merge", relation_ids=("L000001",), source="auto")
        assert derive_effective_source(a) == SOURCE_AUTO

    def test_ai_source(self):
        a = RepairAction(kind="ok", relation_ids=("L000001",), source="ai")
        assert derive_effective_source(a) == SOURCE_AI

    def test_user_source(self):
        a = RepairAction(kind="ok", relation_ids=("L000001",), source="user")
        assert derive_effective_source(a) == SOURCE_USER

    def test_flag_does_not_advance(self):
        """flag 不推进管线。"""
        a = RepairAction(kind="flag", relation_ids=("L000001",), source="ai")
        assert derive_effective_source(a) == SOURCE_NONE

        a2 = RepairAction(kind="flag", relation_ids=("L000001",), source="user")
        assert derive_effective_source(a2) == SOURCE_NONE

    def test_empty_source_is_auto(self):
        """兼容旧 source=""。"""
        a = RepairAction(kind="merge", relation_ids=("L000001",), source="")
        assert derive_effective_source(a) == SOURCE_AUTO

    def test_legacy_agent_source_is_canonicalized_to_ai(self):
        a = RepairAction(kind="edit", relation_ids=("L000001",), source="agent")

        assert a.source == "ai"
        assert derive_effective_source(a) == SOURCE_AI

    def test_legacy_review_metadata_is_migrated_to_effective_source(self):
        a = RepairAction.from_dict(
            {
                "kind": "merge",
                "source": "auto",
                "relation_ids": ["L000001"],
                "data": {"review_state": "ok", "review_source": "agent"},
            }
        )

        assert a.reviewers == ("ai",)
        assert a.effective_source == SOURCE_AI
        assert "review_state" not in a.data
        assert "review_source" not in a.data


# ═══════════════════════════════════════════════════════════════
# 四态管线推进
# ═══════════════════════════════════════════════════════════════


class TestEffectiveSourcePipeline:
    """Source reflects responsibility for the current effective result."""

    def test_initial_is_none(self, raw_state):
        states = _build_states(raw_state)
        # snap 0: 1:1 正常锚点，无 repair → none
        assert (
            states[0].effective_source == SOURCE_NONE
            if states[0].initial_anomaly_types == []
            else states[0].effective_source
        )
        # snap 1: 1:2，无 repair → none
        assert states[1].effective_source == SOURCE_NONE

    def test_auto_repair_advances_to_auto(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        states = _build_states(repaired)
        # snap 1: 1:2 → merge(auto) → AUTO
        assert states[1].effective_source == SOURCE_AUTO

    def test_ai_ok_advances_to_agent(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(repaired.make_action("ok", 1, source="ai"))
        states = _build_states(s2)
        assert states[1].effective_source == SOURCE_AI
        assert not states[1].is_user_approved

    def test_ai_edit_advances_to_agent(self, raw_state):
        """AI 直接 edit（覆盖 auto_repair）→ AGENT。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(
            repaired.make_action(
                "edit", 1, source="ai", new_tgt_lines=["修正1", "修正2"]
            )
        )
        states = _build_states(s2)
        assert states[1].effective_source == SOURCE_AI

    def test_human_ok_advances_to_user(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(repaired.make_action("ok", 1, source="user"))
        states = _build_states(s2)
        assert states[1].effective_source == SOURCE_USER
        assert states[1].is_user_approved

    def test_user_content_operation_is_not_implicit_approval(self, raw_state):
        changed = raw_state.apply(
            raw_state.make_action(
                "edit",
                1,
                source="user",
                new_src_lines=["异常原文"],
                new_tgt_lines=["user revision"],
            )
        )

        state = _build_states(changed)[1]
        assert state.effective_source == SOURCE_USER
        assert not state.is_user_approved
        assert state.requires_manual_review

    def test_material_ai_change_after_user_review_belongs_to_ai(self, raw_state):
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        user_reviewed = repaired.apply(repaired.make_action("ok", 1, source="user"))

        ai_changed = user_reviewed.apply(
            user_reviewed.make_action(
                "edit",
                1,
                source="ai",
                new_src_lines=["异常原文"],
                new_tgt_lines=["AI revised translation"],
            )
        )

        row = ai_changed.current.group(1).rows[0]
        assert row.marker == "[E]"
        assert row.effective_source == "ai"
        assert _build_states(ai_changed)[1].effective_source == "ai"

    def test_human_overrides_ai(self, raw_state):
        """auto → ai → user：确认同一结果时来源按可信度提升。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        # AI ok
        s2 = repaired.apply(repaired.make_action("ok", 1, source="ai"))
        states2 = _build_states(s2)
        assert states2[1].effective_source == SOURCE_AI
        assert RepairService.valid_operations(s2, 1)["ok"]
        row2 = s2.current.group(1).rows[0]
        assert row2.marker == "[M]"
        assert row2.effective_source == "ai"
        assert s2.repair_log[-1].data["reviewed_by"] == ["ai"]
        # 人类 ok 覆盖
        s3 = s2.apply(s2.make_action("ok", 1, source="user"))
        states3 = _build_states(s3)
        assert states3[1].effective_source == SOURCE_USER
        row3 = s3.current.group(1).rows[0]
        assert row3.marker == "[M] [OK]"
        assert row3.effective_source == "user"
        assert s3.repair_log[-1].source == "user"
        assert s3.repair_log[-1].data["reviewed_by"] == ["ai", "user"]
        assert RepairService.valid_operations(s3, 1)["ok"]

        # Repeating an idempotent review does not grow the effective log.
        s4 = s3.apply(s3.make_action("ok", 1, source="user"))
        assert len(s4.repair_log) == len(s3.repair_log)
        assert s4.current.group(1).rows[0].marker == "[M] [OK]"
        assert s4.current.group(1).rows[0].effective_source == "user"

    def test_human_can_upgrade_legacy_ai_ok_on_unresolved_non_1to1(self):
        state = RepairState.from_ops(
            [((0, 1), (0,), 0.63)],
            ["句子前半", "句子后半"],
            ["The complete sentence."],
        )
        ai_reviewed = state.apply(state.make_action("ok", 0, source="ai"))

        source, target, _score = ai_reviewed.snapshot.original_ops[0]
        assert (len(source), len(target)) == (2, 1)
        ai_row = ai_reviewed.current.group(0).rows[0]
        assert ai_row.marker == "[OK]"
        assert ai_row.effective_source == "ai"
        assert RepairService.valid_operations(ai_reviewed, 0)["ok"]

        user_reviewed = ai_reviewed.apply(
            ai_reviewed.make_action("ok", 0, source="user")
        )
        user_row = user_reviewed.current.group(0).rows[0]
        assert user_row.marker == "[OK]"
        assert user_row.effective_source == "user"

    def test_flag_no_advance(self, raw_state):
        """auto → flag(ai) → 仍为 AUTO。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(repaired.make_action("flag", 1, source="ai"))
        states = _build_states(s2)
        assert states[1].effective_source == SOURCE_AUTO
        assert states[1].is_flagged
        # 人类 flag 同样不推进
        s3 = s2.apply(s2.make_action("flag", 1, source="user"))
        states3 = _build_states(s3)
        assert states3[1].effective_source == SOURCE_AUTO
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

        # auto_repair 操作仍是唯一内容决策；AI 审阅记录在元数据中。
        assert log_after == log_before
        assert s2.repair_log[-1].data["reviewed_by"] == ["ai"]

    def test_ai_edit_overrides_auto_repair(self, raw_state):
        """AI edit 应清除 auto_repair 操作（覆盖语义）。"""
        repaired = RepairService.auto_repair(raw_state, strategy="src")
        s2 = repaired.apply(
            repaired.make_action("edit", 1, source="ai", new_tgt_lines=["修正1"])
        )
        log_after = [(s2.action_ordinal(a), a.kind, a.source) for a in s2.repair_log]
        # auto_repair 的 merge 被清除，只剩 edit
        assert log_after == [(1, "edit", "ai")], f"edit should override: {log_after}"
