import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from dualign.gui.window_table import WindowTableMixin
from dualign.gui.workspace import (
    FileQueueItem,
    REVIEW_COMPLETE,
    REVIEW_PENDING,
    REVIEW_UNOPENED,
    WorkspacePanel,
)
from dualign.models.relation_status import RelationStatus


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _item(name: str) -> FileQueueItem:
    return FileQueueItem(
        label=name,
        src_path=f"C:/library/{name}.source.md",
        tgt_path=f"C:/library/{name}.target.md",
    )


def _set_combo_data(combo, value: str) -> None:
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_file_queue_review_state_distinguishes_open_and_completion_scopes():
    item = _item("chapter")

    assert item.review_state("filtered") == REVIEW_UNOPENED

    item.opened = True
    assert item.review_state("filtered") == REVIEW_PENDING

    item.set_review_counts(
        all_subjects=3,
        all_required=1,
        filtered_subjects=1,
        filtered_required=0,
    )

    assert item.review_state("filtered") == REVIEW_COMPLETE
    assert item.review_state("all") == REVIEW_PENDING
    assert item.review_counts("all") == (3, 1)


def test_workspace_table_filters_native_tristate_and_copies_full_paths(tmp_path):
    app = _app()
    panel = WorkspacePanel()
    unopened = _item("unopened")
    filtered_complete = _item("filtered-complete")
    filtered_complete.set_review_counts(
        all_subjects=2,
        all_required=1,
        filtered_subjects=1,
        filtered_required=0,
    )
    loading = _item("loading")
    loading.opened = True
    complete = _item("complete")
    complete.set_review_counts(
        all_subjects=1,
        all_required=0,
        filtered_subjects=1,
        filtered_required=0,
    )
    source_path = tmp_path / "complete.source.md"
    source_path.write_text("\n# 完整章节标题\n正文", encoding="utf-8")
    complete.src_path = str(source_path)
    panel.set_queue([unopened, filtered_complete, loading, complete])

    assert panel._qlw.columnCount() == 5
    assert [panel._qlw.horizontalHeaderItem(i).text() for i in range(5)] == [
        "序号",
        "状态",
        "内容节选",
        "文档 A",
        "文档 B",
    ]
    assert panel._qlw.rowCount() == 4
    assert [
        panel._qlw.cellWidget(row, 1).findChild(QCheckBox).checkState()
        for row in range(4)
    ] == [
        Qt.CheckState.Unchecked,
        Qt.CheckState.Checked,
        Qt.CheckState.PartiallyChecked,
        Qt.CheckState.Checked,
    ]

    assert panel._qlw.item(3, 2).text() == "# 完整章节标题"
    assert panel._qlw.item(3, 2).toolTip() == "# 完整章节标题"
    assert panel._qlw.rowHeight(3) == 24

    copy_a = panel._qlw.cellWidget(1, 3).findChild(QPushButton)
    assert isinstance(copy_a, QPushButton)
    assert copy_a.text() == "复制"
    assert copy_a.toolTip() == filtered_complete.src_path
    copy_a.click()
    app.processEvents()
    assert QApplication.clipboard().text() == filtered_complete.src_path

    _set_combo_data(panel._status_filter, REVIEW_COMPLETE)
    assert panel._qlw.rowCount() == 2
    assert [panel._qlw.item(row, 0).text() for row in range(2)] == ["1", "3"]

    _set_combo_data(panel._review_scope, "all")
    assert panel._qlw.rowCount() == 1
    assert panel._qlw.item(0, 0).text() == "3"

    _set_combo_data(panel._status_filter, REVIEW_PENDING)
    assert panel._qlw.rowCount() == 2
    assert [panel._qlw.item(row, 0).text() for row in range(2)] == ["1", "2"]

    panel.deleteLater()


class _WorkspaceStatusRecorder:
    def __init__(self):
        self.call = None

    def update_review_status(self, src_path, tgt_path, **counts):
        self.call = (src_path, tgt_path, counts)


def test_table_projection_sends_all_and_filtered_user_review_counts():
    workspace = _WorkspaceStatusRecorder()
    harness = SimpleNamespace(
        _workspace=workspace,
        _src_path="A.md",
        _tgt_path="B.md",
        _anomalies=[
            SimpleNamespace(ordinals=(2,)),
            SimpleNamespace(ordinals=(2,)),
        ],
    )
    statuses = [
        RelationStatus(),
        RelationStatus(init_type="1:0"),
        RelationStatus(init_type="0:1", is_user_approved=True),
    ]

    WindowTableMixin._sync_workspace_review_status(harness, statuses)

    assert workspace.call == (
        "A.md",
        "B.md",
        {
            "all_subjects": 2,
            "all_required": 1,
            "filtered_subjects": 1,
            "filtered_required": 0,
        },
    )
