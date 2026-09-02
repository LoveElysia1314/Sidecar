import json

import pytest

from dualign.models.action import (
    AiProposalStore,
    RepairAction,
    canonicalize_action_payload,
)
from dualign.models.relation_identity import (
    normalize_relation_ids,
    rebase_relation_ids,
)
from dualign.models.score_cache import RelationScoreCache
from dualign.models.state import AlignmentSnapshot
from dualign.services.report_io import (
    ReportError,
    build_report,
    load_report,
    repair_state_from_report,
    relation_ids_from_report,
)


def test_current_report_contract_rejects_missing_relation_ids():
    report = {"ops": [{"s": [0], "t": [0], "sc": 0.8}, {"s": [1], "t": []}]}

    with pytest.raises(ReportError, match="关系 ID 无效"):
        relation_ids_from_report(report)


def test_partial_relation_identity_is_rejected_instead_of_silently_rebased():
    report = {"ops": [{"id": "stable", "s": [0]}, {"s": [1]}]}

    with pytest.raises(ReportError):
        relation_ids_from_report(report)


def test_snapshot_projects_between_identity_and_current_position():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8), ((1,), (1,), 0.7)],
        ["A", "B"],
        ["a", "b"],
        ["stable-a", "stable-b"],
    )

    assert snapshot.relation_id(1) == "stable-b"
    assert snapshot.operation_index("stable-a") == 0
    with pytest.raises(KeyError):
        snapshot.operation_index("missing")


def test_action_is_bound_to_snapshot_identity_when_entering_repair_state():
    from dualign.services.repair import RepairState

    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8)], ["A"], ["a"], ["relation-original"]
    )

    state = RepairState(snapshot).apply(RepairAction.make_ok("relation-original"))

    assert state.repair_log[0].relation_ids == ("relation-original",)
    payload = state.repair_log[0].to_dict()
    assert payload["relation_ids"] == ["relation-original"]
    assert "op_index" not in payload
    assert "operation_indices" not in payload


def test_report_binds_unbound_actions_to_persisted_relation_ids(tmp_path):
    path_a = tmp_path / "a.md"
    path_b = tmp_path / "b.md"
    path_a.write_text("A\n", encoding="utf-8")
    path_b.write_text("a\n", encoding="utf-8")

    report = build_report(
        chapter_id="chapter",
        document_a_path=path_a,
        document_b_path=path_b,
        operations=[((0,), (0,), 0.8)],
        relation_ids=["relation-original"],
        stats={},
        quality={},
        provenance={},
        repair_log=[RepairAction.make_flag("relation-original", "review")],
    )

    payload = report["repair_log"][0]
    assert payload["relation_ids"] == ["relation-original"]
    assert "op_index" not in payload
    assert "operation_indices" not in payload


def test_report_freezes_low_score_policy_and_relation_diagnostics(tmp_path):
    from dualign.models.relation_status import project_relation_statuses
    from dualign.services.anomaly_detection import AnomalyDetectionConfig

    path_a = tmp_path / "a.md"
    path_b = tmp_path / "b.md"
    path_a.write_text("A\nB\nC\n", encoding="utf-8")
    path_b.write_text("a\nb\nc\n", encoding="utf-8")
    operations = [
        ((0,), (0,), 0.9),
        ((1,), (1,), 0.9),
        ((2,), (2,), 0.5),
    ]
    report = build_report(
        chapter_id="chapter",
        document_a_path=path_a,
        document_b_path=path_b,
        operations=operations,
        stats={},
        quality={},
        provenance={},
        anomaly_detection_config=AnomalyDetectionConfig(
            zscore_k=1.0, zscore_min_score=0.6
        ),
    )

    state = repair_state_from_report(report, path_a, path_b)
    statuses = project_relation_statuses(state, k=99.0)

    assert report["anomaly_diagnostics"]["config"] == {
        "zscore_k": 1.0,
        "zscore_min_score": 0.6,
    }
    assert statuses[2].is_low_score
    assert "LOW_SCORE" in statuses[2].current_anomaly_types


def test_stable_action_identity_is_authoritative_over_stale_position():
    from dualign.services.repair import RepairState

    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8), ((1,), (1,), 0.7)],
        ["A", "B"],
        ["a", "b"],
        ["relation-a", "relation-b"],
    )

    state = RepairState(
        snapshot,
        [RepairAction.make_ok("relation-b")],
    )

    assert state.action_ordinal(state.repair_log[0]) == 1
    row = state.current.group(1).rows[0]
    assert row.marker == ""
    assert row.effective_source == "auto"


def test_cross_relation_action_is_queryable_and_reset_from_every_target():
    from dualign.services.repair import RepairState

    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8), ((1,), (1,), 0.7)],
        ["A", "B"],
        ["a", "b"],
        ["relation-a", "relation-b"],
    )
    action = RepairAction.make_merge(("relation-a", "relation-b"))
    state = RepairState(snapshot).apply(action)

    assert state.action_for_relation("relation-a") is state.action_for_relation(
        "relation-b"
    )
    assert state.reset_relation("relation-b").repair_log == []


def test_new_decision_on_secondary_relation_replaces_cross_relation_action():
    from dualign.services.repair import RepairState

    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8), ((1,), (1,), 0.7)],
        ["A", "B"],
        ["a", "b"],
        ["relation-a", "relation-b"],
    )
    state = RepairState(snapshot).apply(
        RepairAction.make_merge(("relation-a", "relation-b"))
    )
    state = state.apply(
        RepairAction.make_edit("relation-b", new_src_lines=["B2"], new_tgt_lines=["b2"])
    )

    assert [action.kind for action in state.repair_log] == ["edit"]
    assert state.repair_log[0].relation_ids == ("relation-b",)


def test_legacy_proposal_keys_are_regrouped_by_bound_relation_identity():
    from dualign.services.repair import RepairState

    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (0,), 0.8)], ["A"], ["a"], ["stable-relation"]
    )
    store = AiProposalStore.from_dict(
        {
            "0": [
                {
                    "action": RepairAction.make_edit(
                        "stable-relation", new_tgt_lines=["edited"]
                    ).to_dict(),
                    "status": "pending",
                }
            ]
        }
    )

    state = RepairState(snapshot, [], store)
    proposal = state.ai_proposal_store.get("stable-relation")[0]

    assert list(state.ai_proposal_store.proposals) == ["stable-relation"]
    assert proposal.action.relation_ids == ("stable-relation",)
    assert state.ai_proposal_store.accept(proposal.action)
    assert state.ai_proposal_store.get_status(proposal.action) == "accepted"


def test_action_rejects_missing_stable_identity():
    store = AiProposalStore()

    with pytest.raises(ValueError):
        store.add(RepairAction(kind="ok"))


def test_explicit_rereview_removes_every_proposal_touching_the_relation():
    store = AiProposalStore()
    first = RepairAction.make_edit(
        ("relation-a", "relation-b"), source="ai", new_tgt_lines=["first"]
    )
    second = RepairAction.make_ok("relation-c", source="ai")
    store.add(first)
    store.accept(first)
    store.add(second)

    assert store.remove_for_relations({"relation-b"}) == 1
    assert store.get("relation-a") == []
    assert store.get("relation-c")[0].action == second


def test_canonicalized_legacy_positions_create_an_id_only_action():
    payload = canonicalize_action_payload(
        {
            "op_index": 1,
            "kind": "merge",
            "data": {"orig_snaps": [1, 2]},
        },
        ("relation-a", "relation-b", "relation-c"),
    )
    action = RepairAction.from_dict(payload)

    assert action.relation_ids == ("relation-b", "relation-c")
    assert "orig_snaps" not in action.data
    assert "operation_indices" not in action.to_dict()


def test_legacy_action_payload_is_canonicalized_without_mutating_input():
    payload = {
        "op_index": 0,
        "operation_indices": [1],
        "kind": "merge",
        "data": {"orig_snaps": [0], "note": "keep"},
    }

    result = canonicalize_action_payload(payload, ("relation-a", "relation-b"))

    assert result["relation_ids"] == ["relation-b"]
    assert "op_index" not in result
    assert "operation_indices" not in result
    assert result["data"] == {"note": "keep"}
    assert payload["data"]["orig_snaps"] == [0]


def test_report_load_is_the_only_legacy_position_migration_boundary(tmp_path):
    path_a = tmp_path / "a.md"
    path_b = tmp_path / "b.md"
    report_path = tmp_path / "pair.report.json"
    path_a.write_text("A\n", encoding="utf-8")
    path_b.write_text("a\n", encoding="utf-8")
    report = build_report(
        chapter_id="chapter",
        document_a_path=path_a,
        document_b_path=path_b,
        operations=[((0,), (0,), 0.8)],
        relation_ids=["stable-relation"],
        stats={},
        quality={},
        provenance={},
    )
    report["repair_log"] = [
        {
            "kind": "merge",
            "op_index": 0,
            "data": {"orig_snaps": [0], "note": "keep"},
        }
    ]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    loaded = load_report(report_path)
    payload = loaded["repair_log"][0]
    action = RepairAction.from_dict(payload)

    assert action.relation_ids == ("stable-relation",)
    assert action.data == {"note": "keep"}
    assert "op_index" not in payload
    assert "operation_indices" not in payload


def test_rebase_preserves_exact_matches_and_never_recycles_removed_ids():
    assert rebase_relation_ids(
        ("L000001", "L000002", "custom"),
        (1, None, 0),
        3,
    ) == ("custom", "L000001", "L000003")


def test_relation_ids_must_match_count_and_be_unique():
    with pytest.raises(ValueError):
        normalize_relation_ids(2, ["same", "same"])
    with pytest.raises(ValueError):
        normalize_relation_ids(2, ["only-one"])


def test_score_cache_migrates_legacy_positions_to_relation_ids_once():
    cache = RelationScoreCache.from_dict(
        {"0_0": 0.8, "1_2": 0.6, "bad": 1.0},
        ("relation-a", "relation-b"),
    )

    assert cache.to_dict() == {
        "relation-a": {"0": 0.8},
        "relation-b": {"2": 0.6},
    }


def test_score_cache_retain_uses_identity_without_position_rebasing():
    cache = RelationScoreCache.from_dict(
        {"relation-a": {"0": 0.8}, "relation-b": {"1": 0.6}}
    )

    retained = cache.retain({"relation-b", "relation-new"})

    assert retained.to_dict() == {"relation-b": {"1": 0.6}}
