import hashlib

from dualign.gui.window_actions import WindowActionsMixin
from dualign.gui.window_table import WindowTableMixin
from dualign.models.action import RepairAction
from dualign.services.repair import RepairState
from dualign.services.report_io import build_report, load_report, save_report


class _Harness(WindowActionsMixin):
    def __init__(self, tmp_path):
        self._src_path = str(tmp_path / "a.md")
        self._tgt_path = str(tmp_path / "b.md")
        self._alignment_path = str(tmp_path / "pair.report.json")
        (tmp_path / "a.md").write_text("甲\n乙\n", encoding="utf-8")
        (tmp_path / "b.md").write_text("A\n", encoding="utf-8")
        self._repair_state = RepairState.from_ops(
            [((0, 1), (0,), 0.9)], ["甲", "乙"], ["A"]
        )
        report = build_report(
            chapter_id="pair",
            document_a_path=self._src_path,
            document_b_path=self._tgt_path,
            operations=self._repair_state.original_ops,
            stats={"n_source": 2, "n_target": 1},
            quality={"level": "ok"},
            provenance={"tool": "test"},
        )
        save_report(report, self._alignment_path)
        self._alignment_file_hash = hashlib.sha256(
            (tmp_path / "pair.report.json").read_bytes()
        ).hexdigest()
        self._alignment_file_present = True
        self._score_cache = {}

    def _set_temp_status(self, *_args, **_kwargs):
        pass

    def _safe_status(self, message, *_args, **_kwargs):
        self.last_status = message


class _ScoreManager:
    def __init__(self):
        self.invalidated = []
        self.ready = {}

    def invalidate_snaps(self, snaps):
        self.invalidated.extend(snaps)

    def set_ready_score(self, snap_i, sub, score):
        self.ready[(snap_i, sub)] = score

    def set_text_provider(self, provider):
        self.text_provider = provider

    def start_polling(self):
        pass


class _ScoreLoadHarness(WindowTableMixin):
    pass


def test_save_records_relation_decision_without_touching_documents(tmp_path):
    harness = _Harness(tmp_path)
    action = RepairAction.make_ok(0)
    action.source = "user"
    harness._repair_state = harness._repair_state.apply(action)

    assert harness._on_save_alignment() is True

    assert load_report(harness._alignment_path)["repair_log"][0]["kind"] == "ok"
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "甲\n乙\n"
    assert (tmp_path / "b.md").read_text(encoding="utf-8") == "A\n"


def test_save_records_content_edit_without_implicitly_overwriting_sources(tmp_path):
    harness = _Harness(tmp_path)
    action = RepairAction.make_edit(
        0,
        source="user",
        new_src_lines=["甲校订", "乙"],
        new_tgt_lines=["A"],
    )
    harness._repair_state = harness._repair_state.apply(action)

    assert harness._on_save_alignment() is True

    assert load_report(harness._alignment_path)["repair_log"][0]["kind"] == "edit"
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "甲\n乙\n"


def test_ai_review_uses_the_same_guarded_atomic_report_update(tmp_path):
    harness = _Harness(tmp_path)

    harness._set_ai_review("completed", "checked")

    review = load_report(harness._alignment_path)["ai_review"]
    assert review["status"] == "completed"
    assert review["note"] == "checked"
    assert "updated_at" in review
    assert (
        harness._alignment_file_hash
        == hashlib.sha256((tmp_path / "pair.report.json").read_bytes()).hexdigest()
    )


def test_autosave_reports_an_external_change_without_overwriting_it(tmp_path):
    harness = _Harness(tmp_path)
    report_path = tmp_path / "pair.report.json"
    external = report_path.read_text(encoding="utf-8").replace(
        '"chapter_id": "pair"', '"chapter_id": "external"'
    )
    report_path.write_text(external, encoding="utf-8")

    assert harness._save_session() is False
    assert load_report(report_path)["chapter_id"] == "external"
    assert "外部修改" in harness.last_status


def test_known_split_scores_replace_stale_persisted_subrow_scores(tmp_path):
    harness = _Harness(tmp_path)
    harness._score_mgr = _ScoreManager()
    harness._score_cache = {"0_0": 0.66, "0_1": 0.0, "1_0": 0.9}

    harness._set_known_snap_scores(0, [0.73, 0.76])

    assert harness._score_mgr.invalidated == [0]
    assert harness._score_mgr.ready == {(0, 0): 0.73, (0, 1): 0.76}
    assert harness._score_cache == {"0_0": 0.73, "0_1": 0.76, "1_0": 0.9}


def test_loading_split_prefers_action_scores_over_pre_split_cache():
    state = RepairState.from_ops([((0, 1), (0,), 0.8)], ["甲", "乙"], ["A B"])
    state = state.apply(
        RepairAction.make_split(
            0,
            source="user",
            new_src_lines=["甲", "乙"],
            new_tgt_lines=["A", "B"],
            split_scores=[0.73, 0.76],
        )
    )
    harness = _ScoreLoadHarness()
    harness._repair_state = state
    harness._score_cache = {"0_0": 0.66, "0_1": 0.0}
    harness._score_mgr = _ScoreManager()

    harness._load_initial_scores()

    assert harness._score_mgr.ready == {(0, 0): 0.73, (0, 1): 0.76}
    assert harness._score_cache == {"0_0": 0.73, "0_1": 0.76}
