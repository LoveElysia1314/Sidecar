from dualign.core import AlignmentResult
from dualign.gui.window_actions import WindowActionsMixin
from dualign.gui.window_table import WindowTableMixin


class _Harness(WindowActionsMixin):
    def __init__(self):
        self._load_op_id = 2
        self.src_lines = ["current-source"]
        self.tgt_lines = ["current-target"]
        self.src_emb = "current-embedding"


def test_stale_load_callbacks_cannot_mutate_current_document():
    window = _Harness()
    stale_result = AlignmentResult(all_ops=[], stats={})

    window._on_text_ready(1, "old-a", "old-b", ["old"], ["old"])
    window._on_encoded(1, "old-embedding", None, ["old"], ["old"], "a", "b")
    window._on_alignment_cache_hit(
        1, (stale_result, ["old"], ["old"], "old-a", "old-b")
    )
    window._on_align_done(1, stale_result)

    assert window.src_lines == ["current-source"]
    assert window.tgt_lines == ["current-target"]
    assert window.src_emb == "current-embedding"


class _StatusBar:
    def __init__(self):
        self.preview = None
        self.preview_only = False

    def set_view_mode(self, preview):
        self.preview = preview

    def set_preview_active(self, active, rejected=False, phase=""):
        self.preview = active

    def set_preview_only(self):
        self.preview_only = True


class _RejectedHarness(WindowActionsMixin, WindowTableMixin):
    def __init__(self, report_path):
        self._load_op_id = 1
        self._report_path = str(report_path)
        self._preview_active = True
        self._status_bar = _StatusBar()
        self._repair_state = object()
        self.src_lines = ["甲", "乙"]
        self.tgt_lines = ["A", "B"]
        self.render_count = 0
        self.gating_count = 0
        self.statuses = []

    def _session_path(self):
        return self._report_path

    def _status(self, message, level=None):
        self.statuses.append((message, level))

    def _on_view_mode_toggled(self, preview):
        self._preview_active = preview
        self._apply_filter()

    def _render_preview(self):
        self.render_count += 1

    def _update_feature_gating(self):
        self.gating_count += 1

    def _show_error(self, context, error):
        raise AssertionError(f"{context}: {error}")


def test_rejected_cached_report_renders_preview_without_rewriting(tmp_path):
    report = tmp_path / "one.report.json"
    original = b'{"alignment":{"status":"rejected"}}\n'
    report.write_bytes(original)
    window = _RejectedHarness(report)
    result = AlignmentResult(
        all_ops=[],
        stats={"load_origin": "report"},
        status="rejected",
        reason="order_incompatible",
    )

    window._on_align_done(1, result)

    assert window._repair_state is None
    assert window._preview_active is True
    assert window.render_count == 1
    assert window._status_bar.preview_only is True
    assert window.gating_count == 1
    assert report.read_bytes() == original
