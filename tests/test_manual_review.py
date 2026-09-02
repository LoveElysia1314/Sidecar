from types import SimpleNamespace

from dualign.gui.review import ReviewController
from dualign.models.action import RepairAction
from dualign.models.relation_status import (
    APPROVAL_AGENT,
    APPROVAL_PROPOSED,
    APPROVAL_USER,
    manual_review_counts,
    project_relation_statuses,
)
from dualign.services.repair import RepairState


def _non_1to1_state():
    return RepairState.from_ops(
        [((0, 1), (0,), 0.7), ((2,), (1,), 0.95)],
        ["A0", "A1", "A2"],
        ["B0", "B1"],
    )


def test_ordinary_none_relation_is_not_manual_review_work():
    state = RepairState.from_ops([((0,), (0,), 0.95)], ["A"], ["B"])

    counts = manual_review_counts(project_relation_statuses(state))

    assert (counts.subjects, counts.required, counts.completed) == (0, 0, 0)
    assert counts.is_complete


def test_auto_and_agent_repairs_still_require_a_user_decision():
    initial = _non_1to1_state()
    proposed = initial.apply(
        RepairAction.make_merge("L000001", sub_count=2, source="auto")
    )
    agent = initial.apply(RepairAction.make_merge("L000001", sub_count=2, source="ai"))

    proposed_status = project_relation_statuses(proposed)[0]
    agent_status = project_relation_statuses(agent)[0]

    assert proposed_status.approval == APPROVAL_PROPOSED
    assert agent_status.approval == APPROVAL_AGENT
    assert proposed_status.requires_manual_review
    assert agent_status.requires_manual_review
    assert manual_review_counts(project_relation_statuses(agent)).required == 1


def test_user_approval_completes_the_relation_and_deletion_removes_it():
    initial = _non_1to1_state()
    approved = initial.apply(RepairAction.make_ok("L000001", source="user"))
    deleted = initial.apply(RepairAction.make_delete("L000001", source="auto"))

    approved_status = project_relation_statuses(approved)[0]
    deleted_status = project_relation_statuses(deleted)[0]

    assert approved_status.approval == APPROVAL_USER
    assert approved_status.is_manual_review_subject
    assert not approved_status.requires_manual_review
    assert not deleted_status.is_manual_review_subject


def test_flagged_regular_relation_requires_manual_review():
    state = RepairState.from_ops([((0,), (0,), 0.95)], ["A"], ["B"])
    flagged = state.apply(RepairAction.make_flag("L000001", "组合路径分歧"))

    status = project_relation_statuses(flagged)[0]

    assert status.requires_manual_review


def test_review_controller_uses_relation_semantics_not_historical_string():
    state = _non_1to1_state()
    review = SimpleNamespace(_window=SimpleNamespace(_repair_state=state))

    assert not ReviewController._all_handled(review)

    approved = state.apply(RepairAction.make_ok("L000001", source="user"))
    review._window._repair_state = approved
    assert ReviewController._all_handled(review)

    clean = RepairState.from_ops([((0,), (0,), 0.95)], ["A"], ["B"])
    review._window._repair_state = clean
    assert ReviewController._all_handled(review)
