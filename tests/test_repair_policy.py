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
