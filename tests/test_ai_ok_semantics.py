"""Regression tests: AI "ok" must approve, not override, existing repairs.

原缺陷（两层）：
  1. ai_repair_chapter 调用 agent.run(ctx) 未传 initial_state，导致
     ToolExecutor._get_current_snap_action 恒返回 None，_handle_ok 的
     "AI ok 等同于认可已有修复操作" 语义永远不生效 —— AI 对已合并的
     snap 发 ok 会生成独立的 ok（marker [AI][OK]）而非转换后的 merge。
  2. replay 的 _apply_info_free 对 [AI][OK]/[AI][F] 直接设置 marker，
     覆盖已有 [M]/[S]/[E]/[D]/[P] —— 合并等修复操作从状态列消失。
"""

import json

from dualign.models.state import AlignmentSnapshot
from dualign.models.action import RepairAction
from dualign.services.repair import RepairState
from dualign.services.ai_repair_agent import (
    ChapterContext,
    ToolExecutor,
    ToolCall,
    LLMResponse,
    LLMBackend,
    AiRepairAgent,
    build_agent_review_session,
)


def _snapshot():
    ops = [
        ((0,), (0,), 0.95),
        ((1, 2), (1,), 0.80),  # snap 1: 2:1 → auto merge
        ((3,), (2, 3), 0.70),  # snap 2: 1:2 → auto merge
        ((4,), (4,), 0.95),
    ]
    return AlignmentSnapshot.from_alignment(
        ops,
        ["S0", "S1", "S2", "S3", "S4"],
        ["T0", "T1", "T2", "T3", "T4"],
    )


def _repaired_state():
    """snap 1 已有自动合并。"""
    return RepairState(_snapshot(), [RepairAction.make_merge(1, sub_count=2)])


def _ctx_with_repair():
    return ChapterContext.from_repair_state(
        _repaired_state(),
        chapter_id="t1",
        chapter_title="测试",
        strategy="src",
        model=None,
    )


class TestOkConvertsToExistingRepair:
    """Bug A：ok 必须携带 initial_state 才能识别已有修复操作。"""

    def test_ok_without_initial_state_stays_ok(self):
        # 对照：未传 initial_state（旧行为）时 ok 不会被转换
        ctx = _ctx_with_repair()
        ex = ToolExecutor(ctx, model=None, initial_state=None, strategy="src")
        ex.execute(ToolCall("c1", "ok", {"target": "1"}))
        act = ex.reviewed_actions.get(1)
        assert act is not None
        assert act.kind == "ok"

    def test_ok_with_initial_state_converts_to_merge(self):
        ctx = _ctx_with_repair()
        ex = ToolExecutor(
            ctx, model=None, initial_state=_repaired_state(), strategy="src"
        )
        ex.execute(ToolCall("c2", "ok", {"target": "1"}))
        act = ex.reviewed_actions.get(1)
        assert act is not None
        assert act.kind == "merge"  # AI ok 认可已有合并 → 转换为 merge
        assert act.source == "ai"
        assert act.marker == "[AI][M]"

    def test_ok_with_initial_state_on_clean_snap_stays_ok(self):
        ctx = ChapterContext.from_repair_state(
            RepairState(_snapshot()),
            chapter_id="t1",
            chapter_title="测试",
            strategy="src",
            model=None,
        )
        ex = ToolExecutor(
            ctx, model=None, initial_state=RepairState(_snapshot()), strategy="src"
        )
        ex.execute(ToolCall("c3", "ok", {"target": "1"}))
        act = ex.reviewed_actions.get(1)
        assert act.kind == "ok"  # snap 1 无先前修复 → 真正的通过
        assert act.marker == "[AI][OK]"


class TestAiOkDoesNotEraseRepairMarker:
    """Bug B：replay 时 [AI][OK] 必须叠加而非覆盖已有修复标记。"""

    def test_ai_ok_preserves_merge_marker(self):
        state = RepairState(
            _snapshot(),
            [
                RepairAction.make_merge(1, sub_count=2),
                RepairAction(op_index=1, kind="ok", source="ai"),
            ],
        )
        markers = {row.marker for row in state.current.rows if row.snap_index == 1}
        assert markers == {"[M] [AI][OK]"}, markers

    def test_ai_flag_preserves_repair_marker(self):
        state = RepairState(
            _snapshot(),
            [
                RepairAction.make_merge(1, sub_count=2),
                RepairAction(op_index=1, kind="flag", source="ai"),
            ],
        )
        markers = {row.marker for row in state.current.rows if row.snap_index == 1}
        assert markers == {"[M] [AI][F]"}, markers

    def test_ai_ok_without_prior_repair_keeps_full_marker(self):
        state = RepairState(
            _snapshot(), [RepairAction(op_index=1, kind="ok", source="ai")]
        )
        markers = {row.marker for row in state.current.rows if row.snap_index == 1}
        assert markers == {"[AI][OK]"}, markers

    def test_manual_ok_still_combines(self):
        # 对照组：手动 ok（无 AI 前缀）行为不变
        state = RepairState(
            _snapshot(),
            [RepairAction.make_merge(1, sub_count=2), RepairAction.make_ok(1)],
        )
        markers = {row.marker for row in state.current.rows if row.snap_index == 1}
        assert markers == {"[M] [OK]"}, markers

    def test_ok_f_mutual_exclusion_with_ai_prefix(self):
        # [OK] 与 [F] 互斥：已有 [AI][OK] 再叠加 AI flag → 移除 [OK] 保留 [AI][F]
        state = RepairState(
            _snapshot(),
            [
                RepairAction(op_index=1, kind="ok", source="ai"),
                RepairAction(op_index=1, kind="flag", source="ai"),
            ],
        )
        markers = {row.marker for row in state.current.rows if row.snap_index == 1}
        assert markers == {"[AI][F]"}, markers


class _ScriptedBackend(LLMBackend):
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages, thinking=False, tools=None):
        self.calls += 1
        return self.script.pop(0)


def test_agent_run_with_initial_state_passes_ok_through():
    """端到端：Agent 用 initial_state 运行时，ok 转换由 ToolExecutor 完成。"""
    ctx = _ctx_with_repair()
    t1 = LLMResponse(
        tool_calls=[
            ToolCall("a", "ok", {"target": "1"}),
            ToolCall("b", "ok", {"target": "2"}),
            ToolCall("c", "done", {}),
        ]
    )
    agent = AiRepairAgent(backend="deepseek", verbose=False, strategy="src")
    agent._llm = _ScriptedBackend([t1])
    actions = agent.run(ctx, initial_state=_repaired_state())
    by_op = {a.op_index: a for a in actions}
    assert by_op[1].kind == "merge"  # AI ok 认可已有 merge
    assert by_op[2].kind == "ok"  # snap 2 无修复 → 真正的通过


def test_review_session_keeps_context_and_proposed_state_together():
    """回归：上下文内部生成了拟修复时，Agent 必须收到同一状态。"""
    raw_state = RepairState(_snapshot())
    session = build_agent_review_session(raw_state, strategy="tgt", model=None)

    proposed = [
        action
        for action in session.proposed_state.repair_log
        if action.op_index == 1 and action.kind not in {"ok", "flag"}
    ]
    assert proposed
    assert proposed[-1].kind == "merge"
    # Context 和 proposed_state 均保留 merge 后的组内行布局。
    info = session.context.get_snap_info(1)
    assert info.src_text.splitlines() == ["S1", "S2"]
    assert json.loads(str(info))["proposal"] == "merge"

    ex = ToolExecutor(
        session.context,
        model=None,
        initial_state=session.proposed_state,
        strategy="tgt",
    )
    result = ex.execute(ToolCall("c4", "ok", {"target": "1"}))

    assert ex.reviewed_actions[1].kind == "merge"
    assert "通过拟修复 merge" in result


def test_review_session_does_not_overwrite_existing_user_repair():
    user_edit = RepairAction.make_edit(
        1,
        source="user",
        new_src_lines=["S1", "S2"],
        new_tgt_lines=["T1a", "T1b"],
        inherited_scores=[0.9, 0.8],
    )
    state = RepairState(_snapshot(), [user_edit])

    session = build_agent_review_session(state, strategy="tgt", model=None)

    assert session.proposed_state.action_for_op(1).kind == "edit"
    assert session.proposed_state.action_for_op(1).source == "user"


def test_review_session_preserves_explicitly_selected_normal_pairs():
    state = RepairState(_snapshot())

    session = build_agent_review_session(
        state,
        strategy="tgt",
        model=None,
        reviewable_ids=[0, 3],
    )

    assert session.context.reviewable_ids == [0, 3]
    assert [info.snap_id for info in session.context.reviewable_infos] == [0, 3]
    assert not session.context.get_snap_info(0).is_reviewable
    assert not session.context.get_snap_info(3).is_reviewable

    prompt = AiRepairAgent(strategy="tgt")._build_initial_user_message(session.context)
    assert '>> {"id": 0' in prompt
    assert '>> {"id": 3' in prompt

    executor = ToolExecutor(
        session.context,
        initial_state=session.proposed_state,
        strategy="tgt",
    )
    executor.execute(ToolCall("normal", "ok", {"target": "0"}))
    assert executor.reviewed_actions[0].kind == "ok"


def test_ok_result_distinguishes_original_relation_confirmation():
    """无拟修复时，工具回复应明确说明是确认原始关系。"""
    raw_state = RepairState(_snapshot())
    ctx = ChapterContext.from_repair_state(raw_state, skip_auto_repair=True)
    ex = ToolExecutor(ctx, initial_state=raw_state, strategy="tgt")

    result = ex.execute(ToolCall("c5", "ok", {"target": "1"}))

    assert ex.reviewed_actions[1].kind == "ok"
    assert "确认原始对齐关系（无修改）" in result
