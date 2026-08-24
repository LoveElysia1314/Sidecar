"""
Dualign — 修复状态机测试
"""

import numpy as np
import pytest
from dualign.models.state import AlignmentSnapshot
from dualign.models.action import RepairAction
from dualign.models.state import ChapterState, RelationGroup, RelationRow
from dualign.services.repair import (
    RepairState,
    RepairService,
    SPLIT_FAILURE_AMBIGUOUS,
    SPLIT_FAILURE_UNSPLITTABLE,
    normalize_repair_log,
    review_flags_for_uncertain_regions,
    current_score_slot_exists,
    current_score_texts,
    make_table_view,
)
from dualign.services.table_projection import project_table_cells


@pytest.fixture
def simple_snapshot():
    ops = [((0,), (0,), 0.95), ((1,), (1,), 0.85), ((2, 3), (2,), 0.65)]
    return AlignmentSnapshot.from_alignment(ops, ["A", "B", "C", "D"], ["a", "b", "c"])


@pytest.fixture
def simple_state(simple_snapshot):
    return RepairState(simple_snapshot)


def test_uncertain_region_flags_cover_the_whole_disagreement_island():
    ops = [
        ((0,), (0,), 0.9),
        ((1, 2), (1,), 0.8),
        ((), (2,), 0.0),
        ((3,), (3,), 0.9),
    ]

    flags = review_flags_for_uncertain_regions(ops, (((1, 1), (3, 3)),))

    assert [flag.ordinal for flag in flags] == [1, 2]
    assert all(flag.source == "auto" for flag in flags)
    assert all(flag.data["reason"] == "composition_disagreement" for flag in flags)
    assert "A 行 2–3" in flags[0].data["note"]
    assert flags[0].data["uncertain_region"]["end"] == {
        "source": 3,
        "target": 3,
    }


def test_uncertain_region_flags_only_the_line_whose_matchedness_changes():
    current = [
        ((0,), (0,), 0.9),
        ((1,), (), 0.0),
        ((2,), (1,), 0.9),
    ]
    alternative = [((0, 1), (0,), 0.7), ((2,), (1,), 0.9)]

    flags = review_flags_for_uncertain_regions(
        current,
        (((0, 0), (2, 1)),),
        alternative_operations=alternative,
    )

    assert [flag.ordinal for flag in flags] == [1]
    assert flags[0].data["current_structure"] == "1:1+1:0"
    assert flags[0].data["alternative_structure"] == "2:1"
    assert "当前路径 1:1+1:0；备选路径 2:1" in flags[0].data["note"]


class TestRepairStateCreate:
    def test_initial_groups(self, simple_state):
        assert len(simple_state.current.groups) == 3

    def test_snap_index_access(self, simple_state):
        cs = simple_state.current
        assert cs.group(0) is not None
        assert cs.group(99) is None

    def test_current_reuses_immutable_replay_result(self, simple_state):
        assert simple_state.current is simple_state.current

        changed = simple_state.apply(RepairAction(kind="ok", operation_indices=(0,)))
        assert changed.current is changed.current
        assert changed.current is not simple_state.current

    def test_not_dirty_initially(self, simple_state):
        assert len(simple_state.repair_log) == 0

    def test_dirty_after_apply(self, simple_state):
        action = RepairAction(kind="ok", operation_indices=(0,))
        state2 = simple_state.apply(action)
        assert len(state2.repair_log) == 1
        assert len(simple_state.repair_log) == 0  # 原状态不变


class TestApplyUndo:
    def test_apply_new_instance(self, simple_state):
        action = RepairAction(kind="ok", operation_indices=(0,))
        state2 = simple_state.apply(action)
        assert state2 is not simple_state

    def test_undo_new_instance(self, simple_state):
        action = RepairAction(kind="ok", operation_indices=(0,))
        state2 = simple_state.apply(action)
        state3 = RepairState(
            state2.snapshot, state2.repair_log[:-1], state2.ai_proposal_store
        )
        assert len(state3.repair_log) == 0

    def test_undo_empty(self, simple_state):
        assert len(simple_state.repair_log) == 0

    def test_apply_then_undo_restores(self, simple_state):
        action = RepairAction(kind="ok", operation_indices=(0,))
        n_before = len(simple_state.current.groups)
        state2 = simple_state.apply(action)
        state3 = RepairState(
            state2.snapshot, state2.repair_log[:-1], state2.ai_proposal_store
        )
        assert len(state3.current.groups) == n_before

    def test_reset_clears_log(self, simple_state):
        state2 = simple_state.apply(RepairAction(kind="ok", operation_indices=(0,)))
        assert len(state2.reset().repair_log) == 0

    def test_reset_relation(self, simple_state):
        s1 = simple_state.apply(RepairAction(kind="ok", operation_indices=(0,)))
        s2 = s1.apply(RepairAction(kind="flag", operation_indices=(1,)))
        sr = s2.reset_relation(simple_state.snapshot.relation_id(0))
        assert sr.action_for_relation(simple_state.snapshot.relation_id(0)) is None
        assert sr.action_for_relation(simple_state.snapshot.relation_id(1)) is not None

    def test_flag_note_can_be_updated_and_removed_without_losing_edit(
        self, simple_state
    ):
        edited = simple_state.apply(
            RepairAction.make_edit(
                0, new_src_lines=["edited"], new_tgt_lines=["translated"]
            )
        )
        flagged = edited.apply(RepairAction.make_flag(0, "需要复查"))
        updated = flagged.apply(RepairAction.make_flag(0, "拆分失败"))

        relation_id = simple_state.snapshot.relation_id(0)
        assert updated.flag_for_relation(relation_id).data["note"] == "拆分失败"
        assert len([a for a in updated.repair_log if a.kind == "flag"]) == 1

        cleared = updated.without_relation_flag(relation_id)
        assert cleared.flag_for_relation(relation_id) is None
        assert cleared.action_for_relation(relation_id).kind == "edit"
        assert cleared.current.group(0).rows[0].src_text == "edited"

    def test_new_content_decision_replaces_stale_append_only_decision(
        self, simple_state
    ):
        deletion = RepairAction.make_delete(0, source="auto")
        edit = RepairAction.make_edit(0, source="ai", new_tgt_lines=["fixed"])

        normalized = normalize_repair_log([deletion, edit])
        restored = RepairState(simple_state.snapshot, [deletion, edit])

        assert normalized == [edit]
        assert [action.kind for action in restored.repair_log] == ["edit"]
        assert restored.repair_log[0].relation_ids == ("L000001",)
        assert restored.current.group(0).rows[0].tgt_text == "fixed"

    def test_meta_decisions_survive_a_compatible_content_decision(self):
        edit = RepairAction.make_edit(0, source="ai", new_tgt_lines=["fixed"])
        flag = RepairAction.make_flag(0, "review")
        approval = RepairAction.make_ok(0)

        assert normalize_repair_log([edit, flag, approval]) == [
            edit,
            flag,
            approval,
        ]


class _PartitionEncoder:
    def encode(self, texts, **_kwargs):
        vectors = {
            "source one": (1.0, 0.0),
            "source two": (0.0, 1.0),
            "First.": (1.0, 0.0),
            "Second. Third.": (0.0, 1.0),
        }
        return np.asarray([vectors.get(text, (0.5, 0.5)) for text in texts])


class _ZeroEncoder:
    def encode(self, texts, **_kwargs):
        return np.zeros((len(texts), 2))


class TestSplitAttempt:
    def test_split_chooses_best_partition_for_the_known_target_row_count(self):
        state = RepairState.from_ops(
            [((0, 1), (0,), 0.7)],
            ["source one", "source two"],
            ["First. Second. Third."],
        )

        attempt = RepairService.try_split(state, 0, "tgt", model=_PartitionEncoder())

        assert attempt.succeeded
        action = attempt.state.repair_log[-1]
        assert action.data["new_tgt_lines"] == ["First.", "Second. Third."]
        assert action.data["split_scores"] == pytest.approx([1.0, 1.0])

    def test_split_reports_when_text_has_no_further_boundary(self):
        state = RepairState.from_ops(
            [((0, 1), (0,), 0.7)],
            ["source one", "source two"],
            ["No further boundary"],
        )

        attempt = RepairService.try_split(state, 0, "tgt", model=_PartitionEncoder())

        assert not attempt.succeeded
        assert attempt.failure_reason == SPLIT_FAILURE_UNSPLITTABLE
        assert attempt.state is state

    def test_split_does_not_use_soft_clause_punctuation(self):
        state = RepairState.from_ops(
            [((0, 1), (0,), 0.7)],
            ["source one", "source two"],
            ["A grammatical clause, but still one sentence"],
        )

        attempt = RepairService.try_split(state, 0, "tgt", model=_ZeroEncoder())

        assert not attempt.succeeded
        assert attempt.failure_reason == SPLIT_FAILURE_UNSPLITTABLE
        assert attempt.state is state

    def test_split_reports_when_local_evidence_is_exactly_ambiguous(self):
        state = RepairState.from_ops(
            [((0, 1, 2), (0,), 0.7)],
            ["one", "two", "three"],
            ["First. Second."],
        )

        attempt = RepairService.try_split(state, 0, "tgt", model=_ZeroEncoder())

        assert not attempt.succeeded
        assert attempt.needs_review
        assert attempt.failure_reason == SPLIT_FAILURE_AMBIGUOUS
        assert attempt.state is state

    def test_split_may_merge_the_other_side_after_adding_a_boundary(self):
        state = RepairState.from_ops(
            [((0, 1, 2), (0,), 0.7)],
            ["alpha first", "alpha second", "beta"],
            ["Alpha. Beta."],
        )

        class RecursiveEncoder:
            def encode(self, texts, **_kwargs):
                vectors = {
                    "alpha first": (1.0, 0.0),
                    "alpha second": (0.9, 0.1),
                    "beta": (0.0, 1.0),
                    "Alpha.": (1.0, 0.0),
                    "Beta.": (0.0, 1.0),
                    "alpha first alpha second": (1.0, 0.0),
                    "alpha second beta": (0.2, 0.8),
                }
                return np.asarray([vectors.get(text, (0.5, 0.5)) for text in texts])

        attempt = RepairService.try_split(state, 0, "tgt", model=RecursiveEncoder())

        assert attempt.succeeded
        action = attempt.state.repair_log[-1]
        assert action.data["new_src_lines"] == [
            "alpha first alpha second",
            "beta",
        ]
        assert action.data["new_tgt_lines"] == ["Alpha.", "Beta."]


class TestChapterState:
    def test_replace_relation_immutable(self, simple_state):
        cs = simple_state.current
        g0_edited = cs.group(0).with_text([("NewSrc", "NewTgt")], [0.99], "[E]")
        cs2 = cs.replace_relation(0, g0_edited)
        assert cs2.group(0).rows[0].src_text == "NewSrc"
        assert cs.group(0).rows[0].src_text == "A"

    def test_remove_relation(self, simple_state):
        cs = simple_state.current
        cs2 = cs.remove_relation(1)
        assert len(cs2.groups) == 2
        assert cs2.group(1) is None
        assert cs.group(1) is not None


class TestRelationGroup:
    def test_from_snapshot_2to1(self, simple_snapshot):
        g = RelationGroup.from_snapshot(2, simple_snapshot)
        assert g.ordinal == 2
        assert g.relation_id == simple_snapshot.relation_id(2)
        assert len(g.rows) == 2

    def test_from_snapshot_1to1(self, simple_snapshot):
        assert len(RelationGroup.from_snapshot(0, simple_snapshot).rows) == 1

    def test_with_marker_immutable(self, simple_snapshot):
        g = RelationGroup.from_snapshot(0, simple_snapshot)
        g2 = g.with_marker("[M]")
        assert g2.rows[0].marker == "[M]"
        assert g.rows[0].marker == ""

    def test_with_text_immutable(self, simple_snapshot):
        g = RelationGroup.from_snapshot(0, simple_snapshot)
        g2 = g.with_text([("new_src", "new_tgt"), ("second", "第二")], [0.99], "[E]")
        assert g2.rows[0].src_text == "new_src"
        assert [row.sub for row in g2.rows] == [0, 1]

    def test_row_frozen(self):
        row = RelationRow(
            ordinal=0,
            sub=0,
            init_type="1:1",
            cur_type="1:1",
            src_text="A",
            tgt_text="a",
            score=0.9,
            orig_score=0.9,
            n_src=1,
            n_tgt=1,
        )
        with pytest.raises(Exception):
            row.src_text = "B"  # type: ignore


class TestRepairAction:
    def test_serialize(self):
        action = RepairAction(
            kind="edit",
            sub_count=1,
            data={"new_src_lines": ["X"], "new_tgt_lines": ["Y"]},
            operation_indices=(0,),
        )
        d = action.to_dict()
        assert d["kind"] == "edit"
        assert d["data"]["new_src_lines"] == ["X"]

    def test_deserialize(self):
        d = {"kind": "edit", "op_index": 0, "data": {"X": 1}}
        action = RepairAction.from_dict(d)
        assert action.kind == "edit"

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError):
            RepairAction(kind="invalid_kind", operation_indices=(0,))

    def test_auto_timestamp(self):
        action = RepairAction(kind="ok", operation_indices=(0,))
        assert len(action.timestamp) > 0
        assert "T" in action.timestamp


class TestActionEdgeCases:
    def test_delete_snap(self, simple_state):
        """删除操作将 marker 设为 [D]，groups 数不变但 marker 变化。"""
        state2 = simple_state.apply(RepairAction(kind="delete", operation_indices=(0,)))
        g0 = state2.current.group(0)
        assert g0 is not None
        # 删除操作给 group 打上 [D] 标记
        assert "[D]" in g0.rows[0].marker or g0.rows[0].marker != ""

    def test_action_for_relation(self, simple_state):
        relation_id = simple_state.snapshot.relation_id(0)
        assert simple_state.action_for_relation(relation_id) is None
        action = RepairAction(kind="ok", operation_indices=(0,))
        state2 = simple_state.apply(action)
        assert state2.action_for_relation(relation_id) is not None

    def test_repair_log_property(self, simple_state):
        assert simple_state.repair_log == []
        state2 = simple_state.apply(RepairAction(kind="ok", operation_indices=(0,)))
        assert len(state2.repair_log) == 1
        # 原始 state 不受影响
        assert simple_state.repair_log == []

    def test_snapshot_property(self, simple_state):
        assert simple_state.snapshot is not None
        assert len(simple_state.original_ops) == 3


# ═══════════════════════════════════════════════════════════════
# render_rows 测试 — 所有标记类型的文本输出正确性
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def multi_state():
    """ops: snap0=1:1, snap1=2:1(需合并), snap2=1:1, snap3=0:2(多余译文)"""
    ops = [
        ((0,), (0,), 0.95),
        ((1, 2), (1,), 0.80),
        ((3,), (2,), 0.70),
        ((), (3, 4), 0.0),
    ]
    src = ["A", "B", "C", "D", "E"]
    tgt = ["a", "b", "c", "d", "e"]
    return RepairState(AlignmentSnapshot.from_alignment(ops, src, tgt))


class TestRenderRows:
    """验证 render_rows 对所有标记类型的文本输出正确性。

    测试数据 (multi_state):
      snap0=1:1 → (A, a)
      snap1=2:1 → (B, b), (C, '')
      snap2=1:1 → (D, c)
      snap3=0:2 → ('', d), ('', e)
      total=6 行
    """

    def test_no_marker_passthrough(self, multi_state):
        """无标记时逐行输出原始文本。"""
        src, tgt = RepairService.render_rows(multi_state)
        assert len(src) == 6, f"expect 6 rows (1+2+1+2), got {len(src)}"
        assert src[0] == "A"
        assert tgt[0] == "a"
        # snap1=2:1: sub0=(B,b), sub1=(C,'')
        assert src[1] == "B"
        assert tgt[1] == "b"
        assert src[2] == "C"
        assert tgt[2] == ""
        # snap3=0:2: sub0=('',d), sub1=('',e)
        assert src[4] == ""
        assert tgt[4] == "d"
        assert tgt[5] == "e"

    def test_merge_single_snap(self, multi_state):
        """[M] 单行合并：2:1 → 1 行输出。"""
        repaired = RepairService.repair_merge(multi_state, 1)
        src, tgt = RepairService.render_rows(repaired)
        assert len(src) == 5, f"expect 5 rows (1+1+1+2), got {len(src)}"
        assert src[1] == "B C", f"merged src mismatch: {src[1]!r}"
        assert tgt[1] == "b", f"merged tgt mismatch: {tgt[1]!r}"

    def test_merge_bundle(self, multi_state):
        """[M] 跨行合并 (bundle)：合并 snap0+snap2。"""
        repaired = RepairService.repair_bundle_relations(multi_state, [0, 2])
        src, tgt = RepairService.render_rows(repaired)
        assert len(src) == 5, f"expect 5 rows, got {len(src)}"
        assert src[0] == "A D", f"bundle src mismatch: {src[0]!r}"
        assert tgt[0] == "a c", f"bundle tgt mismatch: {tgt[0]!r}"

        # 平坦预览也必须使用整个 bundle，而不是只读取 anchor 的原始 snap。
        from dualign.gui.window_table import WindowTableMixin

        stub = type("WindowStub", (), {"_repair_state": repaired})()
        flat_src, flat_tgt = WindowTableMixin._get_flat_lines(stub)
        assert flat_src[0] == "A D"
        assert flat_tgt[0] == "a c"

    def test_native_asymmetric_relation_uses_one_current_score(self, multi_state):
        view = make_table_view(multi_state)
        spans = project_table_cells(view.rows, col_offset=1, relation_col=0).spans

        # snap1 starts at table row 1 and is a native 2:1 relation.
        assert spans[(1, 3)] == (2, 1)
        assert spans[(1, 4)] == (2, 1)
        assert spans[(1, 6)] == (2, 1)
        group = multi_state.current.group(1)
        assert current_score_texts(group, 0) == ("B C", "b")
        assert current_score_texts(group, 1) is None

        # snap3 is 0:2: its empty A side is likewise a relation-level cell.
        assert spans[(4, 5)] == (2, 1)

    def test_bundle_spans_initial_segments_and_current_relation_independently(self):
        """1:1 + 1:0 → 2:1：初始列分开，当前列和短侧文本合为一格。"""
        snapshot = AlignmentSnapshot.from_alignment(
            [((0,), (0,), 0.825), ((1,), (), 0.0)],
            ["# 第一卷 第1话 与天使相遇", "台版 转自 轻之国度"],
            ["# Volume 1, Chapter 1: Meeting the Angel"],
        )
        repaired = RepairService.repair_bundle_relations(RepairState(snapshot), [0, 1])
        view = make_table_view(repaired)
        spans = project_table_cells(view.rows, col_offset=1, relation_col=0).spans

        assert [(r.n_src, r.n_tgt) for r in view.rows] == [(2, 1), (2, 1)]
        assert (0, 1) not in spans  # 两个独立的初始类型
        assert (0, 2) not in spans  # 两个独立的初始评分
        assert spans[(0, 3)] == (2, 1)  # 当前状态
        assert spans[(0, 4)] == (2, 1)  # 当前评分
        assert spans[(0, 6)] == (2, 1)  # 当前关系的短侧文档 B

        group = repaired.current.group(0)
        assert current_score_texts(group, 0) == (
            "# 第一卷 第1话 与天使相遇台版 转自 轻之国度",
            "# Volume 1, Chapter 1: Meeting the Angel",
        )
        assert current_score_texts(group, 1) is None

    def test_multi_edit_keeps_current_rows_independent(self, multi_state):
        repaired = RepairService.repair_multi_edit(
            multi_state, [0, 1], ["X", "Y"], ["x", "y"], [0.9, 0.8]
        )
        view = make_table_view(repaired)
        bundle_rows = [r for r in view.rows if r.ordinal == 0]
        spans = project_table_cells(bundle_rows, col_offset=1, relation_col=0).spans

        assert (0, 3) not in spans
        assert (0, 4) not in spans
        group = repaired.current.group(0)
        assert current_score_texts(group, 0) == ("X", "x")
        assert current_score_texts(group, 1) == ("Y", "y")
        assert bundle_rows[0].init_score_text == "* 88%"

    def test_edit(self, multi_state):
        """[E] 校订：替换为自定义文本。"""
        repaired = multi_state.apply(
            RepairAction.make_edit(
                1,
                new_src_lines=["X", "Y"],
                new_tgt_lines=["x", "y"],
                inherited_scores=[0.9, 0.8],
            )
        )
        src, tgt = RepairService.render_rows(repaired)
        assert len(src) == 6
        assert src[1] == "X", f"edit src[1] mismatch: {src[1]!r}"
        assert tgt[1] == "x", f"edit tgt[1] mismatch: {tgt[1]!r}"
        assert src[2] == "Y", f"edit src[2] mismatch: {src[2]!r}"

    def test_edit_multi_snap(self, multi_state):
        """[E] 跨行校订 (multi-snap edit)。"""
        repaired = RepairService.repair_multi_edit(
            multi_state, [0, 1], ["X", "Y"], ["x", "y"], [0.9, 0.8]
        )
        src, tgt = RepairService.render_rows(repaired)
        # snap1 被删除，anchor=snap0 有 2 行；snap2(1) + snap3(2) = 5
        assert len(src) == 5, f"expect 5 rows (2+1+2), got {len(src)}"
        assert src[0] == "X"
        assert src[1] == "Y"

    def test_delete(self, multi_state):
        """[D] 删除：跳过不输出。"""
        repaired = multi_state.apply(RepairAction.make_delete(1))
        src, tgt = RepairService.render_rows(repaired)
        assert "B" not in src, "deleted snap text should not appear"
        group = repaired.current.group(1)
        assert current_score_slot_exists(group, 0)
        assert not current_score_slot_exists(group, 1)
        assert current_score_texts(group, 0) is None

    def test_placeholder(self, multi_state):
        """[P] 占位符：空侧标记 ⟢MISSING⟣。"""
        # snap3=0:2 → 多余译文，占位符填原文侧
        repaired = RepairService.repair_placeholder(multi_state, 3, "src")
        src, tgt = RepairService.render_rows(repaired)
        assert len(src) == 6
        # snap3 sub0 和 sub1 的原文侧均为 ⟢MISSING⟣
        assert src[4] == "\u27e2MISSING\u27e3", f"placeholder[4] mismatch: {src[4]!r}"
        assert src[5] == "\u27e2MISSING\u27e3", f"placeholder[5] mismatch: {src[5]!r}"
        assert tgt[4] == "d", f"placeholder tgt[4] mismatch: {tgt[4]!r}"
        assert tgt[5] == "e", f"placeholder tgt[5] mismatch: {tgt[5]!r}"
        group = repaired.current.group(3)
        assert all(current_score_slot_exists(group, sub) for sub in (0, 1))
        assert all(current_score_texts(group, sub) is None for sub in (0, 1))

    def test_flag_preserves_text(self, multi_state):
        """[F] 标记：文本不变。"""
        repaired = multi_state.apply(RepairAction.make_flag(1))
        src_before, _ = RepairService.render_rows(multi_state)
        src_after, _ = RepairService.render_rows(repaired)
        assert src_before == src_after, "flag should not change text"

    def test_ok_preserves_text(self, multi_state):
        """[OK] 确认：文本不变。"""
        repaired = multi_state.apply(RepairAction.make_ok(1))
        src_before, _ = RepairService.render_rows(multi_state)
        src_after, _ = RepairService.render_rows(repaired)
        assert src_before == src_after, "ok should not change text"

    def test_mixed_merge_edit(self, multi_state):
        """混合操作：先 merge 再 bundle。"""
        s1 = RepairService.repair_merge(multi_state, 1)
        s2 = RepairService.repair_bundle_relations(s1, [0, 1])
        src, tgt = RepairService.render_rows(s2)
        # bundle snap0+snap1=1行；snap2(1)+snap3(2)=4
        assert len(src) == 4, f"expect 4 rows, got {len(src)}"
        assert src[0] == "A B C", f"mixed src mismatch: {src[0]!r}"
        assert tgt[0] == "a b", f"mixed tgt mismatch: {tgt[0]!r}"

    def test_delete_and_merge_preserves_order(self, multi_state):
        """删除后再合并，顺序保持正确。"""
        s1 = multi_state.apply(RepairAction.make_delete(0))
        s2 = RepairService.repair_bundle_relations(s1, [1, 2])
        src, tgt = RepairService.render_rows(s2)
        # [D]skip snap0 + bundle snap1+snap2=1行 + snap3(2) = 3
        assert len(src) == 3, f"expect 3 rows, got {len(src)}"
        assert src[0] == "B C D", f"delete+merge src mismatch: {src[0]!r}"

    def test_render_after_full_reset(self, multi_state):
        """重置所有操作后文本恢复原始。"""
        s1 = RepairService.repair_merge(multi_state, 1)
        s2 = s1.apply(RepairAction.make_delete(0))
        src_reset, _ = RepairService.render_rows(s2.reset())
        assert src_reset == [
            "A",
            "B",
            "C",
            "D",
            "",
            "",
        ], f"reset restore mismatch: {src_reset}"
