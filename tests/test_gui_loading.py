import json

from dualign.__main__ import _load_gui_entries
from dualign.common import FilePair
from dualign.gui.workers import EncodeThread
from dualign.gui.window_actions import WindowActionsMixin
from dualign.models.action import RepairAction
from dualign.services.cli_pipeline import align_documents
from dualign.services.report_io import load_report

from test_cli_pipeline import MockEncoder


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _LoadThread:
    def __init__(self, *, finishes_while_waiting: bool):
        self.running = True
        self.finishes_while_waiting = finishes_while_waiting
        self.stop_calls = 0
        self.wait_calls = []
        self.finished = _Signal()

    def isRunning(self):
        return self.running

    def stop(self):
        self.stop_calls += 1

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self.finishes_while_waiting:
            self.running = False


class _CancellationHarness(WindowActionsMixin):
    def __init__(self, thread):
        self._load_op_id = 4
        self._enc_thread = thread
        self._worker = None
        self._retired_load_threads = set()


def _report_pair(tmp_path):
    source = tmp_path / "one.source.md"
    target = tmp_path / "one.target.md"
    report = tmp_path / "alignment" / "one.report.json"
    source.write_text("甲\n乙\n", encoding="utf-8")
    target.write_text("A\nB\n", encoding="utf-8")
    assert align_documents(str(source), str(target), str(report), model=MockEncoder())[
        "success"
    ]
    return source, target, report


def test_load_gui_entries_uses_neutral_documents_and_one_report(tmp_path):
    manifest = tmp_path / "entries.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "entry_id": "one",
                    "label": "第一章",
                    "document_a_path": "a.md",
                    "document_b_path": "b.md",
                    "report_path": "alignment/one.report.json",
                    "language_a": "zh-Hans",
                    "language_b": "en",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entry = _load_gui_entries(str(manifest))[0]

    assert entry.document_a_path == "a.md"
    assert entry.document_b_path == "b.md"
    assert entry.report_path == "alignment/one.report.json"
    assert entry.alignment_path == entry.report_path


def test_file_pair_exposes_read_only_source_target_aliases():
    entry = FilePair("one", "One", "a.md", "b.md", "one.report.json")
    assert entry.source_path == "a.md"
    assert entry.target_path == "b.md"


def test_encode_thread_restores_report_before_loading_model(tmp_path, monkeypatch):
    source, target, report = _report_pair(tmp_path)
    worker = EncodeThread(
        str(source),
        str(target),
        alignment_path=str(report),
        expected_provenance=load_report(report)["provenance"],
    )
    hits = []
    worker.cache_hit_signal.connect(hits.append)
    monkeypatch.setattr(
        "dualign.gui.workers._try_lazy_load_model",
        lambda: (_ for _ in ()).throw(AssertionError("report hit must skip model")),
    )

    worker._run_impl()

    assert len(hits) == 1
    assert hits[0][0].stats["load_origin"] == "report"


def test_encode_thread_rejects_report_after_source_change(tmp_path):
    source, target, report = _report_pair(tmp_path)
    source.write_text("changed\n", encoding="utf-8")
    worker = EncodeThread(str(source), str(target), alignment_path=str(report))

    assert worker._load_cached_alignment("ignored", "ignored") is None
    assert "变化" in worker.formal_alignment_error


def test_encode_thread_rejects_report_after_alignment_config_change(tmp_path):
    source, target, report = _report_pair(tmp_path)
    provenance = load_report(report)["provenance"]
    changed = json.loads(json.dumps(provenance))
    changed["algorithm"]["configuration_sha256"] = "changed"
    worker = EncodeThread(
        str(source),
        str(target),
        alignment_path=str(report),
        expected_provenance=changed,
    )

    assert worker._load_cached_alignment("ignored", "ignored") is None
    assert "配置已变化" in worker.formal_alignment_error


def test_cancel_retains_a_worker_that_has_not_stopped_yet():
    thread = _LoadThread(finishes_while_waiting=False)
    harness = _CancellationHarness(thread)

    assert harness._cancel_current_load() is False
    assert harness._load_op_id == 5
    assert harness._enc_thread is None
    assert thread in harness._retired_load_threads

    thread.running = False
    thread.finished.callback()
    assert not harness._retired_load_threads


def test_cancel_releases_a_worker_that_stops_during_the_grace_period():
    thread = _LoadThread(finishes_while_waiting=True)
    harness = _CancellationHarness(thread)

    assert harness._cancel_current_load() is True
    assert thread.stop_calls == 1
    assert thread.wait_calls == [15000]
    assert not harness._retired_load_threads


def test_report_can_store_snap_anchored_action_without_materialized_files(tmp_path):
    source, target, report = _report_pair(tmp_path)
    data = json.loads(report.read_text(encoding="utf-8"))
    action = RepairAction.make_ok(0)
    action.source = "user"
    data["repair_log"] = [action.to_dict()]
    from dualign.services.report_io import save_report

    save_report(data, report)

    assert report.is_file()
    assert not (report.parent / "one.source.md").exists()
    assert (
        json.loads(report.read_text(encoding="utf-8"))["repair_log"][0]["op_index"] == 0
    )
