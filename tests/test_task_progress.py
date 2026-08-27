import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from dualign.gui.task_progress import TaskProgress, TaskProgressDialog, run_modal_task


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_modal_task_returns_worker_result_and_progresses_event_loop():
    _app()
    parent = QWidget()

    def operation(_token, progress):
        progress(TaskProgress("正在测试", 1, 1))
        return 42

    outcome = run_modal_task(
        parent,
        title="测试",
        message="准备中",
        operation=operation,
    )

    assert outcome.result == 42
    assert not outcome.cancelled
    assert not outcome.error


def test_modal_task_requests_cooperative_cancellation_without_terminating_thread():
    _app()

    def operation(token, _progress):
        while not token.wait(0.01):
            pass
        token.raise_if_cancelled()

    dialog = TaskProgressDialog("测试", "运行中", operation)
    QTimer.singleShot(20, dialog.request_cancel)
    dialog.exec()

    assert dialog.outcome.cancelled
    assert not dialog.worker.isRunning()
