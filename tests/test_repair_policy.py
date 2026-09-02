import pytest

from dualign.models.state import AlignmentSnapshot
from dualign.services.repair import RepairService, RepairState
from dualign.services.repair_policy import (
    AutoRepairPlan,
    choose_auto_repair,
    strategy_for_ai_review,
)


@pytest.mark.parametrize(
    ("relation", "strategy", "expected"),
    [
        ((2, 1), "src", AutoRepairPlan("split", "tgt")),
        ((2, 1), "tgt", AutoRepairPlan("merge")),
        ((2, 1), "minimal", AutoRepairPlan("merge")),
        ((1, 2), "src", AutoRepairPlan("merge")),
        ((1, 2), "tgt", AutoRepairPlan("split", "src")),
        ((1, 2), "minimal", AutoRepairPlan("merge")),
        ((1, 0), "src", AutoRepairPlan("placeholder_tgt")),
        ((1, 0), "tgt", AutoRepairPlan("delete")),
        ((1, 0), "minimal", AutoRepairPlan("delete")),
        ((0, 1), "src", AutoRepairPlan("delete")),
        ((0, 1), "tgt", AutoRepairPlan("placeholder_src")),
        ((0, 1), "minimal", AutoRepairPlan("delete")),
        ((1, 1), "src", None),
        ((2, 2), "src", None),
        ((2, 2), "tgt", None),
    ],
)
def test_strategy_matrix_has_one_canonical_mapping(relation, strategy, expected):
    assert choose_auto_repair(*relation, strategy) == expected


def test_unknown_strategy_is_not_silently_treated_as_src():
    with pytest.raises(ValueError, match="未知对齐策略"):
        choose_auto_repair(2, 1, "typo")


def test_minimal_intentionally_maps_to_src_for_ai_review_only():
    assert strategy_for_ai_review("minimal") == "src"
    assert choose_auto_repair(2, 1, "minimal") == AutoRepairPlan("merge")
    assert choose_auto_repair(
        2, 1, strategy_for_ai_review("minimal")
    ) == AutoRepairPlan("split", "tgt")


def test_missing_split_capability_preserves_relation_instead_of_merging_it():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0, 1), (0,), 0.8)], ["A", "B"], ["one. two."]
    )

    repaired = RepairService.auto_repair(
        RepairState(snapshot), strategy="src", model=None
    )

    assert repaired.repair_log == []
    assert repaired.current.group(0).rows[0].cur_type == "2:1"


def test_document_a_strategy_preserves_a_and_inserts_target_placeholder_for_1_to_0():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (), 0.0)], ["必须保留的文档 A 行"], []
    )

    repaired = RepairService.auto_repair(
        RepairState(snapshot), strategy="src", model=None
    )

    assert [action.kind for action in repaired.repair_log] == ["placeholder_tgt"]
    rows = repaired.current.group(0).rows
    assert [(row.src_text, row.tgt_text) for row in rows] == [
        ("必须保留的文档 A 行", "⟢MISSING⟣")
    ]
    assert repaired.repair_log[0].data["strategy"] == "src"


def test_switching_to_document_a_replaces_stale_automatic_delete():
    snapshot = AlignmentSnapshot.from_alignment(
        [((0,), (), 0.0)], ["必须保留的文档 A 行"], []
    )
    deleted = RepairService.auto_repair(
        RepairState(snapshot), strategy="tgt", model=None
    )
    assert deleted.repair_log[0].kind == "delete"

    repaired = RepairService.auto_repair(
        deleted,
        strategy="src",
        model=None,
        unresolved_only=True,
    )

    assert [action.kind for action in repaired.repair_log] == ["placeholder_tgt"]
    row = repaired.current.group(0).rows[0]
    assert (row.src_text, row.tgt_text) == (
        "必须保留的文档 A 行",
        "⟢MISSING⟣",
    )
