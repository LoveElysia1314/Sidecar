from pathlib import Path

import pytest

from dualign.__main__ import main_solidify, main_solidify_batch
from dualign.models.action import RepairAction
from dualign.models.alignment_pair import (
    AlignmentLink,
    AlignmentPair,
    DocumentReference,
)
from dualign.models.pair_editing import PairEditingState
from dualign.services.alignment_io import document_sha256
from dualign.services.report_io import (
    build_report,
    load_report,
    materialize_reader_rows,
    save_report,
)
from dualign.services.pair_save import PairSaveConflictError
from dualign.services.realignment import RebuiltAlignment
from dualign.services.solidify import (
    SolidifyPolicy,
    SolidifyTarget,
    apply_batch_solidification,
    build_solidification_plan,
    load_solidify_policy,
    plan_batch_solidification,
    solidify_report,
)


def _positional_rebuild(document_a, document_b):
    paired = min(len(document_a), len(document_b))
    operations = [((index,), (index,), 0.75) for index in range(paired)]
    operations.extend(((index,), (), 0.0) for index in range(paired, len(document_a)))
    operations.extend(((), (index,), 0.0) for index in range(paired, len(document_b)))
    return RebuiltAlignment(tuple(operations), {}, {}, {})


@pytest.fixture(autouse=True)
def _deterministic_realign(monkeypatch):
    monkeypatch.setattr(
        "dualign.services.pair_save.rebuild_alignment", _positional_rebuild
    )


def _baseline(text_a="甲\n", text_b="A\n"):
    pair = AlignmentPair(
        id="pair",
        document_a=DocumentReference("a", "a.md"),
        document_b=DocumentReference("b", "b.md"),
        links=(AlignmentLink("L000001", (1,), (1,), state="suggested"),),
    )
    return PairEditingState.from_alignment_pair(pair, text_a, text_b)


def _report_case(tmp_path: Path, text_a: str, text_b: str, operations, actions):
    path_a = tmp_path / "a.md"
    path_b = tmp_path / "b.md"
    report_path = tmp_path / "pair.report.json"
    path_a.write_text(text_a, encoding="utf-8")
    path_b.write_text(text_b, encoding="utf-8")
    report = build_report(
        chapter_id="pair",
        document_a_path=path_a,
        document_b_path=path_b,
        operations=operations,
        stats={
            "n_source": len(text_a.splitlines()),
            "n_target": len(text_b.splitlines()),
        },
        quality={"level": "ok", "rejections": [], "indicators": {}},
        provenance={"tool": "test"},
        repair_log=actions,
    )
    save_report(report, report_path)
    return path_a, path_b, report_path


def test_partial_edit_solidification_keeps_other_side_as_rebased_action():
    action = RepairAction.make_edit(
        0,
        source="user",
        new_src_lines=["甲校订"],
        new_tgt_lines=["A edited"],
    )
    plan = build_solidification_plan(
        _baseline(), [action], SolidifyPolicy(frozenset({"edit_b"}))
    )

    assert plan.solidified.document_a.render_text() == "甲\n"
    assert plan.solidified.document_b.render_text() == "A edited\n"
    assert len(plan.remaining_actions) == 1
    assert "new_src_lines" in plan.remaining_actions[0].data
    assert "new_tgt_lines" not in plan.remaining_actions[0].data


def test_partial_edit_does_not_promote_score_for_the_uncommitted_full_edit(
    tmp_path: Path,
):
    action = RepairAction.make_edit(
        0,
        source="user",
        new_src_lines=["甲校订"],
        new_tgt_lines=["A edited"],
    )
    path_a, path_b, report_path = _report_case(
        tmp_path, "甲\n", "A\n", [((0,), (0,), 0.4)], [action]
    )
    report = load_report(report_path)
    report["scores"] = {"0_0": 0.9}
    save_report(report, report_path)

    solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"edit_b"})),
    )

    saved = load_report(report_path)
    assert saved["ops"][0]["sc"] == pytest.approx(0.75)
    assert saved["scores"] == {}


def test_two_sided_merge_requires_both_merge_types(tmp_path: Path):
    action = RepairAction.make_merge(0, sub_count=2, source="auto")
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "甲\n乙\n",
        "A\nB\n",
        [((0, 1), (0, 1), 0.8)],
        [action],
    )

    first, first_result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"merge_b"})),
    )

    assert first_result is None
    assert path_a.read_text(encoding="utf-8") == "甲\n乙\n"
    assert path_b.read_text(encoding="utf-8") == "A\nB\n"
    assert len(load_report(report_path)["repair_log"]) == 1

    second, second_result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"merge_a", "merge_b"})),
    )

    assert second_result is not None
    assert path_a.read_text(encoding="utf-8") == "甲乙\n"
    assert path_b.read_text(encoding="utf-8") == "A B\n"
    assert load_report(report_path)["repair_log"] == []
    assert load_report(report_path)["documents"]["a"]["sha256"] == document_sha256(
        path_a
    )


def test_split_solidification_rebuilds_ops_and_removes_applied_action(tmp_path: Path):
    action = RepairAction.make_split(
        0,
        source="user",
        side="tgt",
        new_src_lines=["甲", "乙"],
        new_tgt_lines=["A", "B"],
    )
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "甲\n乙\n",
        "A B\n",
        [((0, 1), (0,), 0.8)],
        [action],
    )

    plan, result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"split_b"})),
    )

    assert result is not None
    assert plan.remaining_actions == ()
    assert path_b.read_text(encoding="utf-8") == "A\nB\n"
    saved = load_report(report_path)
    assert saved["ops"] == [
        {"id": "L000002", "s": [0], "t": [0], "sc": 0.75},
        {"id": "L000003", "s": [1], "t": [1], "sc": 0.75},
    ]
    assert saved["repair_log"] == []
    assert saved["history"][-1]["type"] == "selective-solidification"


def test_cross_snap_two_sided_merge_is_atomic(tmp_path: Path):
    action = RepairAction.make_merge(
        0, sub_count=2, source="user", operation_indices=(0, 1)
    )
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "甲\n乙\n",
        "A\nB\n",
        [((0,), (0,), 0.9), ((1,), (1,), 0.8)],
        [action],
    )

    plan, result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"merge_a", "merge_b"})),
    )

    assert result is not None
    assert path_a.read_text(encoding="utf-8") == "甲乙\n"
    assert path_b.read_text(encoding="utf-8") == "A B\n"
    saved = load_report(report_path)
    assert saved["ops"] == [{"id": "L000001", "s": [0], "t": [0], "sc": 0.75}]
    assert saved["repair_log"] == []
    assert materialize_reader_rows(report_path, path_a, path_b) == (["甲乙"], ["A B"])


def test_two_sided_split_requires_both_split_types(tmp_path: Path):
    action = RepairAction.make_split(
        0,
        source="user",
        side="src",
        new_src_lines=["甲", "乙"],
        new_tgt_lines=["A", "B"],
    )
    path_a, path_b, report_path = _report_case(
        tmp_path, "甲乙\n", "AB\n", [((0,), (0,), 0.8)], [action]
    )

    partial, partial_result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"split_a"})),
    )

    assert partial_result is None
    assert len(partial.remaining_actions) == 1
    assert partial.remaining_actions[0].kind == action.kind
    assert partial.remaining_actions[0].data == action.data
    assert partial.remaining_actions[0].relation_ids == ("L000001",)
    assert path_a.read_text(encoding="utf-8") == "甲乙\n"
    assert path_b.read_text(encoding="utf-8") == "AB\n"

    complete, complete_result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"split_a", "split_b"})),
    )

    assert complete_result is not None
    assert complete.remaining_actions == ()
    assert path_a.read_text(encoding="utf-8") == "甲\n乙\n"
    assert path_b.read_text(encoding="utf-8") == "A\nB\n"


def test_flag_and_ok_are_reanchored_after_surviving_content_solidification(
    tmp_path: Path,
):
    edit = RepairAction.make_edit(0, source="user", new_tgt_lines=["edited"])
    flag = RepairAction.make_flag(0, note="复查术语")
    approval = RepairAction.make_ok(0)
    approval.source = "user"
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "甲\n",
        "A\n",
        [((0,), (0,), 0.9)],
        [edit, flag, approval],
    )

    _plan, result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"edit_b"})),
    )

    assert result is not None
    remaining = load_report(report_path)["repair_log"]
    assert [item["kind"] for item in remaining] == ["flag", "ok"]
    assert remaining[0]["data"]["note"] == "复查术语"


def test_delete_is_solidified_but_review_markers_remain_in_history(tmp_path: Path):
    deletion = RepairAction.make_delete(0, source="ai")
    flag = RepairAction.make_flag(0, note="确认冗余")
    approval = RepairAction.make_ok(0)
    approval.source = "user"
    approval.data["approvals"] = {"manual"}
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "多余\n保留\n",
        "extra\nkeep\n",
        [((0,), (0,), 0.9), ((1,), (1,), 0.9)],
        [deletion, flag, approval],
    )

    plan, result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"delete_pair"})),
    )

    assert result is not None
    assert path_a.read_text(encoding="utf-8") == "保留\n"
    assert path_b.read_text(encoding="utf-8") == "keep\n"
    saved = load_report(report_path)
    assert saved["repair_log"] == []
    assert [item["kind"] for item in saved["history"][-1]["repair_log"]] == [
        "delete",
        "flag",
        "ok",
    ]
    assert saved["history"][-1]["applied_repairs"][0]["effects"] == ["delete_pair"]


def test_placeholder_is_not_a_solidification_type():
    with pytest.raises(ValueError, match="未知固化类型"):
        SolidifyPolicy(frozenset({"placeholder_src"}))


def test_policy_file_supports_toml_preset_overrides(tmp_path: Path):
    config = tmp_path / "solidify.toml"
    config.write_text(
        '[solidify]\npreset = "edits"\ninclude = ["merge_b"]\nexclude = ["edit_a"]\n',
        encoding="utf-8",
    )

    policy = load_solidify_policy(config)

    assert policy.enabled == {"edit_b", "merge_b"}


def test_report_changed_during_batch_plan_is_not_overwritten(
    tmp_path: Path, monkeypatch
):
    action = RepairAction.make_edit(0, source="user", new_tgt_lines=["changed"])
    path_a, path_b, report_path = _report_case(
        tmp_path, "甲\n", "A\n", [((0,), (0,), 0.9)], [action]
    )
    from dualign.services import solidify as service

    real_plan = service.plan_report_solidification

    def plan_then_external_change(*args, **kwargs):
        result = real_plan(*args, **kwargs)
        report = load_report(report_path)
        report["external_note"] = "changed concurrently"
        save_report(report, report_path)
        return result

    monkeypatch.setattr(
        service, "plan_report_solidification", plan_then_external_change
    )

    with pytest.raises(PairSaveConflictError, match="工作报告"):
        solidify_report(
            path_a,
            path_b,
            report_path,
            SolidifyPolicy(frozenset({"edit_b"})),
        )

    assert path_b.read_text(encoding="utf-8") == "A\n"


def test_ai_edit_can_be_solidified_without_manual_ok(tmp_path: Path):
    action = RepairAction.make_edit(
        0,
        source="ai",
        new_tgt_lines=["AI edit"],
    )
    path_a, path_b, report_path = _report_case(
        tmp_path, "甲\n", "A\n", [((0,), (0,), 0.9)], [action]
    )

    plan, result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"edit_b"})),
    )

    assert result is not None
    assert path_b.read_text(encoding="utf-8") == "AI edit\n"
    assert load_report(report_path)["repair_log"] == []


def test_later_edit_supersedes_stale_delete_before_solidification(tmp_path: Path):
    deletion = RepairAction.make_delete(0, source="auto")
    edit = RepairAction.make_edit(0, source="ai", new_tgt_lines=["AI edit"])
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "甲\n",
        "A\n",
        [((0,), (0,), 0.9)],
        [deletion, edit],
    )

    plan, result = solidify_report(
        path_a,
        path_b,
        report_path,
        SolidifyPolicy(frozenset({"edit_b", "delete_pair"})),
    )

    assert result is not None
    assert [item["action"]["kind"] for item in plan.applied] == ["edit"]
    assert path_a.read_text(encoding="utf-8") == "甲\n"
    assert path_b.read_text(encoding="utf-8") == "AI edit\n"


def test_cli_is_preview_only_until_apply_flag(tmp_path: Path, capsys):
    action = RepairAction.make_edit(0, source="user", new_tgt_lines=["changed"])
    path_a, path_b, report_path = _report_case(
        tmp_path, "甲\n", "A\n", [((0,), (0,), 0.9)], [action]
    )

    assert (
        main_solidify(
            str(path_a),
            str(path_b),
            str(report_path),
            preset="edits",
        )
        == 0
    )
    assert path_b.read_text(encoding="utf-8") == "A\n"
    assert "仅为预览" in capsys.readouterr().out

    assert (
        main_solidify(
            str(path_a),
            str(path_b),
            str(report_path),
            preset="edits",
            apply=True,
        )
        == 0
    )
    assert path_b.read_text(encoding="utf-8") == "changed\n"


def test_batch_plan_and_apply_share_the_exact_previewed_transactions(tmp_path: Path):
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first = _report_case(
        tmp_path / "first",
        "甲\n",
        "A\n",
        [((0,), (0,), 0.9)],
        [RepairAction.make_edit(0, source="user", new_tgt_lines=["A1"])],
    )
    second = _report_case(
        tmp_path / "second",
        "乙\n",
        "B\n",
        [((0,), (0,), 0.8)],
        [],
    )
    targets = [
        SolidifyTarget("first", *(str(path) for path in first)),
        SolidifyTarget("second", *(str(path) for path in second)),
    ]

    batch = plan_batch_solidification(targets, SolidifyPolicy(frozenset({"edit_b"})))

    assert len(batch.ready) == 1
    assert batch.action_count == 1
    assert batch.document_b_count == 1
    assert len(batch.skipped) == 1
    assert not batch.skipped[0].error

    result = apply_batch_solidification(batch)

    assert [target.label for target in result.succeeded] == ["first"]
    assert result.failed == ()
    assert first[1].read_text(encoding="utf-8") == "A1\n"
    assert second[1].read_text(encoding="utf-8") == "B\n"


def test_batch_cli_uses_the_gui_manifest_and_is_preview_only_by_default(
    tmp_path: Path, capsys
):
    path_a, path_b, report_path = _report_case(
        tmp_path,
        "甲\n",
        "A\n",
        [((0,), (0,), 0.9)],
        [RepairAction.make_edit(0, source="user", new_tgt_lines=["changed"])],
    )
    manifest = tmp_path / "entries.json"
    manifest.write_text(
        __import__("json").dumps(
            [
                {
                    "label": "chapter",
                    "document_a_path": str(path_a),
                    "document_b_path": str(path_b),
                    "report_path": str(report_path),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main_solidify_batch(str(manifest), preset="edits") == 0
    assert path_b.read_text(encoding="utf-8") == "A\n"
    assert "仅为预览" in capsys.readouterr().out

    assert main_solidify_batch(str(manifest), preset="edits", apply=True) == 0
    assert path_b.read_text(encoding="utf-8") == "changed\n"
