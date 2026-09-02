from dualign.services.repair import RepairService, RepairState
from dualign.services.text_search import TextSearchMatch, find_current_text


def test_search_is_case_insensitive_and_checks_both_current_sides():
    state = RepairState.from_ops(
        [((0,), (0,), 0.8), ((1,), (1,), 0.7)],
        ["Alpha", "乙"],
        ["甲", "beta ALPHA"],
    )

    assert find_current_text(state, "alpha") == (
        TextSearchMatch(0, 0, "src"),
        TextSearchMatch(1, 0, "tgt"),
    )


def test_search_uses_current_cross_relation_rows_not_removed_baseline_groups():
    state = RepairState.from_ops(
        [((0,), (0,), 0.8), ((), (1,), 0.0), ((1,), (2,), 0.7)],
        ["甲", "丙"],
        ["A", "obsolete correction", "C"],
    )
    edited = RepairService.repair_multi_edit(
        state,
        [0, 1, 2],
        ["甲", "丙"],
        ["A", "relocated C"],
    )

    assert find_current_text(edited, "obsolete") == ()
    assert find_current_text(edited, "relocated") == (TextSearchMatch(0, 1, "tgt"),)
