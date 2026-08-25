from collections import deque
from types import SimpleNamespace

from dualign.gui.window_actions import WindowActionsMixin
from dualign.gui.window_table import WindowTableMixin
from dualign.gui.review import REVIEW_SHORTCUTS, ReviewController
from dualign.gui.base_table import compute_text_colors, relation_text_changes
from dualign.gui.settings import DualignConfig, KEY_AUTO_NEXT_CHAPTER
from dualign.gui.window import DualignWindow
from dualign.models.action import RepairAction
from dualign.models.relation_status import (
    APPROVAL_USER,
    RelationAnomaly,
    project_relation_statuses,
)
from dualign.models.state import AlignmentSnapshot
from dualign.services.repair import RepairState


class _Emitter:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


def test_relation_text_changes_are_shared_but_marker_coloring_stays_visual():
    snapshot = AlignmentSnapshot.from_alignment([((0,), (0,), 0.9)], ["A"], ["B"])
    edit = RepairAction.make_edit("L000001", new_src_lines=["A+"], new_tgt_lines=["B"])
    placeholder = RepairAction.make_placeholder_src("L000001")
    merge = RepairAction.make_merge("L000001")

    assert relation_text_changes(0, edit, snapshot) == (True, False)
    assert relation_text_changes(0, placeholder, snapshot) == (True, False)
    assert relation_text_changes(0, merge, snapshot) == (False, False)
    assert compute_text_colors(0, placeholder, snapshot) == (True, True)
    assert compute_text_colors(0, merge, snapshot) == (True, True)


class _ReviewNavigationHarness:
    def __init__(self, auto_next):
        self._current_idx = 0
        self._anomalies = [RelationAnomaly(approval="user")]
        self._auto_next = auto_next
        self.next_chapter_requested = _Emitter()
        self.visited = []

    def auto_next_chapter(self):
        return self._auto_next

    def _all_handled(self):
        return True

    def go(self, index):
        self.visited.append(index)


class _HistoryReview:
    def set_history_enabled(self, can_undo, can_redo):
        self.history_enabled = (can_undo, can_redo)


class _HistoryHarness:
    def __init__(self, undo_count, redo_count, has_data=True):
        self._undo_stack = [object()] * undo_count
        self._redo_stack = [object()] * redo_count
        self._repair_state = object() if has_data else None
        self._review = _HistoryReview()


class _FlagHarness(WindowActionsMixin):
    def __init__(self):
        state = RepairState.from_ops([((0,), (0,), 0.9)], ["A"], ["B"])
        self._repair_state = state.apply(
            RepairAction.make_edit(
                "L000001", new_src_lines=["A+"], new_tgt_lines=["B+"]
            )
        )
        self._undo_stack = deque(maxlen=50)
        self._redo_stack = deque(maxlen=50)

    def _save_session(self):
        pass

    def _refresh(self):
        pass

    def _set_temp_status(self, *_args):
        pass


class _InitialFocusHarness:
    def __init__(self, anomalies, all_anomalies, show_all=True):
        self._anomalies = anomalies
        self._all_anomaly_ordinals = set(all_anomalies)
        self._filter_panel = type("Filter", (), {"show_all": show_all})()
        self._row_op_map = {0: 7, 1: 8}


class _BottomPanelHarness:
    def __init__(self, user_collapsed):
        self._bottom_locked = False
        self._preview_active = False
        self._bottom_collapsed = True
        self._bottom_user_collapsed = user_collapsed
        self._repair_state = object()
        self._review = SimpleNamespace(_pending_action_list=[object()])
        self.toggle_origins = []

    def _toggle_bottom_panel(self, *, user_initiated=True):
        self.toggle_origins.append(user_initiated)
        self._bottom_collapsed = not self._bottom_collapsed


def test_auto_next_chapter_is_opt_in():
    assert DualignConfig.default_values()[KEY_AUTO_NEXT_CHAPTER] is False

    review = _ReviewNavigationHarness(auto_next=False)
    ReviewController._go_next(review)

    assert review.next_chapter_requested.count == 0
    assert review.visited == [0]


def test_review_shortcuts_cover_every_direct_review_operation():
    assert REVIEW_SHORTCUTS == {
        "merge": "M",
        "split": "S",
        "edit": "E",
        "ok": "O",
        "flag": "F",
        "delete": "Delete",
        "placeholder": "P",
        "reset": "Ctrl+R",
    }


def test_auto_action_preview_uses_the_auto_repair_strategy_matrix():
    assert ReviewController._predict_auto_action(1, 0, "src") == "placeholder"
    assert ReviewController._predict_auto_action(1, 0, "minimal") == "delete"


def test_handled_last_item_advances_when_enabled():
    review = _ReviewNavigationHarness(auto_next=True)

    ReviewController._go_next(review)

    assert review.next_chapter_requested.count == 1
    assert review.visited == []


def test_history_buttons_follow_history_stacks():
    window = _HistoryHarness(undo_count=1, redo_count=0)

    DualignWindow._sync_undo_redo(window)

    assert window._review.history_enabled == (True, False)


def test_history_buttons_require_loaded_data():
    window = _HistoryHarness(undo_count=1, redo_count=1, has_data=False)

    DualignWindow._sync_undo_redo(window)

    assert window._review.history_enabled == (False, False)


def test_flag_note_update_and_removal_are_single_undoable_operations():
    window = _FlagHarness()

    window._set_flags([0], "拆分失败：文本重对齐失败")

    assert len(window._undo_stack) == 1
    relation_id = window._repair_state.snapshot.relation_id(0)
    assert (
        window._repair_state.flag_for_relation(relation_id)
        .data["note"]
        .endswith("重对齐失败")
    )

    window._remove_flags([0])

    assert len(window._undo_stack) == 2
    assert window._repair_state.flag_for_relation(relation_id) is None
    assert window._repair_state.action_for_relation(relation_id).kind == "edit"


def test_undo_projects_relation_identity_before_resetting_ai_proposal():
    state = RepairState.from_ops([((0,), (0,), 0.9)], ["A"], ["B"])
    action = state.make_action(
        "edit", 0, source="ai", new_src_lines=["A"], new_tgt_lines=["B+"]
    )
    store = state.ai_proposal_store
    store.add(action)
    assert store.accept(action)
    applied = state.apply(action)

    ordinals = WindowActionsMixin._sync_proposals_on_undo(
        SimpleNamespace(), applied, state
    )

    assert ordinals == [0]
    assert store.get_status(action) == "pending"


def test_new_chapter_focus_prefers_first_visible_anomaly():
    window = _InitialFocusHarness([RelationAnomaly(ordinals=(12,))], {12})

    assert WindowTableMixin._initial_focus_target(window) == 12


def test_clean_chapter_focuses_first_pair_when_showing_all():
    window = _InitialFocusHarness([], set(), show_all=True)

    assert WindowTableMixin._initial_focus_target(window) == 7


def test_empty_anomaly_only_view_has_no_synthetic_focus():
    window = _InitialFocusHarness([], set(), show_all=False)

    assert WindowTableMixin._initial_focus_target(window) is None


def test_explicit_ai_selection_bypasses_anomaly_filter():
    state = RepairState.from_ops([((0,), (0,), 0.99)], ["A"], ["B"])
    review = SimpleNamespace(
        _window=SimpleNamespace(
            _repair_state=state,
            _strategy="src",
            _model=object(),
        ),
        _anomalies=[],
    )

    context = ReviewController._build_chapter_context(
        review,
        for_ordinals=[0],
        skip_auto_repair=True,
    )

    assert context is not None
    assert context.reviewable_ids == [0]
    assert not context.get_relation_info(0).is_reviewable


def test_chapter_ai_still_requires_anomalies_without_explicit_selection():
    state = RepairState.from_ops([((0,), (0,), 0.99)], ["A"], ["B"])
    review = SimpleNamespace(
        _window=SimpleNamespace(
            _repair_state=state,
            _strategy="src",
            _model=object(),
        ),
        _anomalies=[],
    )

    context = ReviewController._build_chapter_context(
        review,
        skip_auto_repair=True,
    )

    assert context is None


def test_applying_ai_suggestion_creates_a_user_approval():
    state = RepairState.from_ops([((0, 1), (0,), 0.7)], ["A", "B"], ["AB"])
    action = RepairAction.make_merge("L000001", source="ai")

    approved = state.apply(action).apply(ReviewController._make_user_approval(action))
    status = project_relation_statuses(approved)[0]

    assert approved.repair_log[-1].source == "user"
    assert status.approval == APPROVAL_USER
    assert not status.requires_manual_review


def test_chapter_ai_excludes_user_reviewed_relations_but_explicit_review_can_include():
    state = RepairState.from_ops([((0, 1), (0,), 0.7)], ["A", "B"], ["AB"])
    state = state.apply(RepairAction.make_ok("L000001", source="user"))
    review = SimpleNamespace(
        _window=SimpleNamespace(_repair_state=state, _strategy="src", _model=object()),
        _anomalies=[RelationAnomaly(ordinals=(0,), approval="user")],
    )

    assert (
        ReviewController._build_chapter_context(review, skip_auto_repair=True) is None
    )
    explicit = ReviewController._build_chapter_context(
        review,
        for_ordinals=[0],
        skip_auto_repair=True,
    )
    assert explicit.reviewable_ids == [0]


def test_user_collapsed_ai_panel_stays_closed_during_auto_sync(monkeypatch):
    monkeypatch.setattr("dualign.providers.active_repair_agent", lambda: None)
    window = _BottomPanelHarness(user_collapsed=True)

    DualignWindow._sync_bottom_panel(window)

    assert window._bottom_collapsed
    assert window.toggle_origins == []


def test_ai_panel_can_auto_expand_without_user_collapse(monkeypatch):
    monkeypatch.setattr("dualign.providers.active_repair_agent", lambda: None)
    window = _BottomPanelHarness(user_collapsed=False)

    DualignWindow._sync_bottom_panel(window)

    assert not window._bottom_collapsed
    assert window.toggle_origins == [False]
