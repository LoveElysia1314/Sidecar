from collections import deque
from types import SimpleNamespace

from dualign.gui.window_actions import WindowActionsMixin
from dualign.gui.window_table import WindowTableMixin
from dualign.gui.review import REVIEW_SHORTCUTS, ReviewController
from dualign.gui.preview_table import AiSuggestionItem
from dualign.gui.base_table import compute_text_colors, relation_text_changes
from dualign.gui.settings import DualignConfig, KEY_AUTO_NEXT_CHAPTER
from dualign.gui.window import DualignWindow
from dualign.models.action import RepairAction
from dualign.models.relation_status import (
    RelationAnomaly,
    project_relation_statuses,
)
from dualign.models.source import SOURCE_USER
from dualign.models.state import AlignmentSnapshot
from dualign.services.repair import RepairState


class _Emitter:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class _Button:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = enabled


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
        self._anomalies = [RelationAnomaly(effective_source="user")]
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
    assert ReviewController._predict_auto_action(1, 0, "minimal") == "placeholder"
    assert ReviewController._predict_auto_action(0, 1, "minimal") == "placeholder"


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


def test_browse_mode_allows_explicit_rereview_without_an_auto_repair_plan():
    state = RepairState.from_ops([((0,), (0,), 0.99)], ["A"], ["B"])
    state = state.apply(state.make_action("ok", 0, source="ai"))
    suggest = _Button()
    review = SimpleNamespace(
        _window=SimpleNamespace(
            _repair_state=state,
            _strategy="src",
            selected_ordinals={0},
        ),
        _btn_refs={"suggest": suggest},
        _selected_ordinals=lambda: [0],
        _disable_all_buttons=lambda: None,
        _sync_menu_actions=lambda: None,
    )

    ReviewController._update_browse_button_states(review, 0)

    assert suggest.enabled is True


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


def test_adopting_ai_suggestion_is_a_user_action_but_not_user_approval():
    state = RepairState.from_ops([((0, 1), (0,), 0.7)], ["A", "B"], ["AB"])
    action = RepairAction.make_merge("L000001", source="ai")

    approved = state.apply(action.adopted_by("user"))
    status = project_relation_statuses(approved)[0]

    assert len(approved.repair_log) == 1
    assert approved.repair_log[-1].source == "user"
    assert approved.current.group(0).rows[0].marker == "[M]"
    assert status.effective_source == SOURCE_USER
    assert not status.is_user_approved
    assert status.requires_manual_review


def test_accept_button_adopts_proposal_without_ai_or_redundant_ok_marker():
    state = RepairState.from_ops([((0,), (0,), 0.7)], ["A"], ["B"])
    proposal = RepairAction.make_edit(
        "L000001", source="ai", new_src_lines=["A"], new_tgt_lines=["B+"]
    )
    state.ai_proposal_store.add(proposal)
    window = SimpleNamespace(
        _repair_state=state,
        _status_bar=SimpleNamespace(is_auto_advance=lambda: False),
        _save_session=lambda: None,
    )

    def apply_action(action):
        window._repair_state = window._repair_state.apply(action)

    review = SimpleNamespace(
        _focused_action=proposal,
        _window=window,
        action_requested=SimpleNamespace(emit=apply_action),
        actions_updated=_Emitter(),
        _rebuild_ai_suggestions=lambda: None,
        _set_focused_action=lambda _action: None,
        _on_next_suggestion=lambda: None,
    )

    ReviewController._on_ai_accept_focused(review)

    applied = window._repair_state.repair_log
    assert len(applied) == 1
    assert applied[0].kind == "edit"
    assert applied[0].source == "user"
    assert window._repair_state.current.group(0).rows[0].marker == "[E]"
    assert window._repair_state.ai_proposal_store.get_status(proposal) == "accepted"


def test_accepted_suggestion_preview_uses_current_score_cache():
    action = RepairAction.make_edit(
        "L000001", source="ai", new_src_lines=["A"], new_tgt_lines=["B+"]
    )
    item = AiSuggestionItem(
        0,
        action,
        "已应用",
        src_line="A",
        tgt_line="B+",
        score=0.0,
    )
    review = SimpleNamespace(
        _window=SimpleNamespace(
            _score_cache=SimpleNamespace(get=lambda relation_id, sub: 0.721)
        ),
        _suggestion_score_cache={},
        _suggestion_scores_pending=set(),
    )
    requests = []

    ReviewController._prepare_suggestion_scores(
        review, action, "已应用", [item], requests
    )

    assert item.score == 0.721
    assert requests == []


def test_pending_suggestion_score_requests_are_deduplicated():
    action = RepairAction.make_edit(
        "L000001", source="ai", new_src_lines=["A"], new_tgt_lines=["B+"]
    )
    first = AiSuggestionItem(0, action, src_line="A", tgt_line="B+")
    second = AiSuggestionItem(0, action, src_line="A", tgt_line="B+")
    review = SimpleNamespace(
        _window=SimpleNamespace(_score_cache=None),
        _suggestion_score_cache={},
        _suggestion_scores_pending=set(),
    )
    requests = []

    ReviewController._prepare_suggestion_scores(
        review, action, "pending", [first], requests
    )
    ReviewController._prepare_suggestion_scores(
        review, action, "pending", [second], requests
    )

    assert requests == [("A", "B+")]


def test_chapter_ai_excludes_user_reviewed_relations_but_explicit_review_can_include():
    state = RepairState.from_ops([((0, 1), (0,), 0.7)], ["A", "B"], ["AB"])
    state = state.apply(RepairAction.make_ok("L000001", source="user"))
    review = SimpleNamespace(
        _window=SimpleNamespace(_repair_state=state, _strategy="src", _model=object()),
        _anomalies=[RelationAnomaly(ordinals=(0,), effective_source="user")],
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


def test_review_current_relation_falls_back_to_unified_focus():
    review = SimpleNamespace(
        _current_ordinals=lambda: [],
        _window=SimpleNamespace(
            selected_ordinals=set(),
            _focus=SimpleNamespace(focused_ordinal=7),
        ),
    )

    assert ReviewController._current_ordinal(review) == 7


def test_review_button_uses_focused_relation_when_selection_is_empty():
    analyzed = []
    review = SimpleNamespace(
        _has_active_agent=lambda: False,
        _selected_ordinals=lambda: [],
        _current_ordinal=lambda: 7,
        analyze_relations=lambda ordinals: analyzed.append(ordinals),
        _emit_log=lambda *_args: None,
        _on_agent_error=lambda _error: None,
    )

    ReviewController._on_ai_analyze(review)

    assert analyzed == [[7]]


def test_review_button_click_dispatches_the_unified_focus():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    review = ReviewController()
    review._window = SimpleNamespace(
        selected_ordinals=set(),
        _focus=SimpleNamespace(focused_ordinal=7),
    )
    analyzed = []
    review.analyze_relations = lambda ordinals: analyzed.append(ordinals)
    review._btn_refs["suggest"].setEnabled(True)

    review._btn_refs["suggest"].click()

    assert analyzed == [[7]]
    review.close()
    app.processEvents()


def test_review_button_reports_missing_relation_instead_of_silent_noop():
    logs = []
    review = SimpleNamespace(
        _has_active_agent=lambda: False,
        _selected_ordinals=lambda: [],
        _current_ordinal=lambda: None,
        _emit_log=lambda message, role: logs.append((message, role)),
    )

    ReviewController._on_ai_analyze(review)

    assert logs == [("请先选择要审校的文本对", "warning")]


def test_cancel_active_agent_requests_cooperative_stop_and_updates_ui():
    class Thread:
        def __init__(self):
            self.cancel_calls = 0

        def isRunning(self):
            return True

        def request_cancel(self):
            self.cancel_calls += 1
            return True

    thread = Thread()
    logs = []
    states = []
    review = SimpleNamespace(
        _active_threads=[thread],
        _emit_log=lambda message, role: logs.append((message, role)),
        _set_ai_running_state=lambda loading, **kwargs: states.append(
            (loading, kwargs)
        ),
    )

    ReviewController._cancel_active_agent(review)

    assert thread.cancel_calls == 1
    assert logs == [("正在停止 AI 校订…", "info")]
    assert states == [(True, {"stopping": True})]


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
