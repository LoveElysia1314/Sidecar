"""Responsive modal execution for long GUI tasks.

The dialog keeps the Qt event loop alive while deliberately preventing edits
to its parent window. Cancellation is cooperative: services may defer it
across an atomic commit boundary, but the GUI never terminates a worker thread.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dualign.services.cancellation import CancellationError, CancellationToken


@dataclass(frozen=True, slots=True)
class TaskProgress:
    message: str
    current: int = 0
    total: int = 0
    cancellable: bool = True


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    result: object | None = None
    cancelled: bool = False
    error: str = ""
    traceback: str = ""


class _TaskThread(QThread):
    progress = Signal(object)

    def __init__(self, operation: Callable, parent: QWidget | None = None):
        super().__init__(parent)
        self.operation = operation
        self.token = CancellationToken()
        self.outcome = TaskOutcome()

    def run(self) -> None:
        try:
            result = self.operation(self.token, self.progress.emit)
            self.outcome = TaskOutcome(result=result)
        except CancellationError as exc:
            self.outcome = TaskOutcome(cancelled=True, error=str(exc))
        except Exception as exc:  # pragma: no cover - traceback is UI evidence
            self.outcome = TaskOutcome(error=str(exc), traceback=traceback.format_exc())


class TaskProgressDialog(QDialog):
    """Application-modal progress UI backed by a cooperative QThread."""

    def __init__(
        self,
        title: str,
        message: str,
        operation: Callable,
        parent: QWidget | None = None,
        *,
        cancellable: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(420)
        self.setModal(True)
        self._started_at = time.monotonic()
        self._can_cancel = cancellable
        self._closing = False

        layout = QVBoxLayout(self)
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.elapsed_label = QLabel("已用时 0 秒")
        layout.addWidget(self.elapsed_label)

        buttons = QDialogButtonBox()
        self.cancel_button = QPushButton("停止")
        self.cancel_button.setEnabled(cancellable)
        self.cancel_button.setVisible(cancellable)
        self.cancel_button.clicked.connect(self.request_cancel)
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        self.worker = _TaskThread(operation, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(250)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

    @property
    def outcome(self) -> TaskOutcome:
        return self.worker.outcome

    def exec(self) -> int:
        self._elapsed_timer.start()
        self.worker.start()
        return super().exec()

    def request_cancel(self) -> None:
        if not self.worker.isRunning() or not self._can_cancel:
            return
        if self.worker.token.cancel():
            self.cancel_button.setEnabled(False)
            self.message_label.setText(
                "正在停止；若已进入原子写入阶段，将先安全完成或回滚…"
            )

    def _on_progress(self, progress: TaskProgress) -> None:
        self.message_label.setText(progress.message)
        self._can_cancel = progress.cancellable
        self.cancel_button.setEnabled(
            progress.cancellable and not self.worker.token.is_cancelled
        )
        if progress.total > 0:
            self.progress_bar.setRange(0, progress.total)
            self.progress_bar.setValue(max(0, min(progress.current, progress.total)))
            self.progress_bar.setFormat("%v / %m  %p%")
        else:
            self.progress_bar.setRange(0, 0)

    def _update_elapsed(self) -> None:
        seconds = max(0, int(time.monotonic() - self._started_at))
        self.elapsed_label.setText(f"已用时 {seconds} 秒")

    def _on_finished(self) -> None:
        self._elapsed_timer.stop()
        self._update_elapsed()
        self._closing = True
        if self.outcome.error and not self.outcome.cancelled:
            super().reject()
        else:
            super().accept()

    def reject(self) -> None:
        if self.worker.isRunning() and not self._closing:
            self.request_cancel()
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self.worker.isRunning() and not self._closing:
            self.request_cancel()
            event.ignore()
            return
        super().closeEvent(event)


def run_modal_task(
    parent: QWidget,
    *,
    title: str,
    message: str,
    operation: Callable,
    cancellable: bool = True,
) -> TaskOutcome:
    """Run ``operation(token, progress_callback)`` with a responsive parent."""

    dialog = TaskProgressDialog(
        title,
        message,
        operation,
        parent,
        cancellable=cancellable,
    )
    dialog.exec()
    return dialog.outcome
