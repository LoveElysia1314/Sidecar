"""
Dualign — WorkspacePanel: 统一工作区面板
"""

from __future__ import annotations

import os
import json
from typing import List, Tuple, Optional
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QGroupBox,
    QFileDialog,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
    QApplication,
    QAbstractItemView,
    QSizePolicy,
)

REVIEW_UNOPENED = "unopened"
REVIEW_PENDING = "pending"
REVIEW_COMPLETE = "complete"


class DragDropLineEdit(QLineEdit):
    file_dropped = Signal(str)

    def __init__(self, ph="", parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setPlaceholderText(ph)
        self.setStyleSheet("")

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasUrls() else None

    def dropEvent(self, e):
        if e.mimeData().urls():
            p = e.mimeData().urls()[0].toLocalFile()
            if p.lower().endswith((".md", ".txt", ".markdown")):
                self.setText(p)
                self.file_dropped.emit(p)
        e.acceptProposedAction()


class FileQueueItem:
    def __init__(self, label="", src_path="", tgt_path="", entry=None):
        self.label = label
        self.src_path = src_path
        self.tgt_path = tgt_path
        self.entry = entry
        self.opened = False
        self._review_known = False
        self._all_review_counts = (0, 0)
        self._filtered_review_counts = (0, 0)
        self._excerpt_signature = None
        self._source_excerpt = ""

    @property
    def display_title(self):
        return (
            Path(self.src_path).name if self.src_path else (self.label or "（未命名）")
        )

    @property
    def aligned(self) -> bool:
        """Compatibility alias for callers predating the review-state split."""

        return self.opened

    @aligned.setter
    def aligned(self, value: bool) -> None:
        self.opened = bool(value)

    def set_review_counts(
        self,
        *,
        all_subjects: int,
        all_required: int,
        filtered_subjects: int,
        filtered_required: int,
    ) -> bool:
        all_counts = (int(all_subjects), int(all_required))
        filtered_counts = (int(filtered_subjects), int(filtered_required))
        changed = (
            not self.opened
            or not self._review_known
            or self._all_review_counts != all_counts
            or self._filtered_review_counts != filtered_counts
        )
        self.opened = True
        self._review_known = True
        self._all_review_counts = all_counts
        self._filtered_review_counts = filtered_counts
        return changed

    def review_counts(self, scope: str = "filtered") -> tuple[int, int]:
        return (
            self._all_review_counts if scope == "all" else self._filtered_review_counts
        )

    def review_state(self, scope: str = "filtered") -> str:
        if not self.opened:
            return REVIEW_UNOPENED
        if not self._review_known:
            return REVIEW_PENDING
        _subjects, required = self.review_counts(scope)
        return REVIEW_COMPLETE if required == 0 else REVIEW_PENDING

    def source_excerpt(self) -> str:
        """Return the first non-empty source line, cached until the file changes."""

        try:
            stat = os.stat(self.src_path)
            signature = (self.src_path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = (self.src_path, None, None)
        if signature == self._excerpt_signature:
            return self._source_excerpt

        self._excerpt_signature = signature
        if signature[1] is None:
            self._source_excerpt = "（无法读取）"
            return self._source_excerpt

        self._source_excerpt = "（空文档）"
        try:
            with open(
                self.src_path,
                "r",
                encoding="utf-8-sig",
                errors="replace",
            ) as handle:
                for line in handle:
                    text = line.strip()
                    if text:
                        self._source_excerpt = text
                        break
        except OSError:
            self._source_excerpt = "（无法读取）"
        return self._source_excerpt


class WorkspacePanel(QWidget):
    pair_selected = Signal(object)  # FileQueueItem，完整保留 entry 元数据
    add_queue_requested = Signal()
    doc_remove_requested = Signal()
    chapter_nav_requested = Signal(int)

    _RF = os.path.join(os.path.expanduser("~"), ".dualign", "recent_pairs.json")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: List[FileQueueItem] = []
        self._selected: Optional[FileQueueItem] = None
        self._recent_pairs: List[Tuple[str, str, str]] = self._load_recent()
        self._build_ui()
        self._rrc()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(200)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(0, super().minimumSizeHint().height())

    def _build_ui(self):
        r = QVBoxLayout(self)
        r.setContentsMargins(2, 2, 2, 2)
        r.setSpacing(4)

        # ── 添加文件对 ──
        pg = QGroupBox("添加文件对")
        pl = QVBoxLayout(pg)
        pl.setContentsMargins(6, 8, 6, 4)
        pl.setSpacing(4)
        self._se = DragDropLineEdit("拖拽或浏览 .md/.txt")
        self._te = DragDropLineEdit("拖拽或浏览 .md/.txt")
        for ic, label, ed, slt in [
            ("📄", "文档 A:", self._se, self._on_browse_src),
            ("📄", "文档 B:", self._te, self._on_browse_tgt),
        ]:
            rr = QHBoxLayout()
            rr.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFixedWidth(58)
            lbl.setStyleSheet("")
            rr.addWidget(lbl)
            ed.setMinimumWidth(0)
            rr.addWidget(ed, 1)
            b = QPushButton("...")
            b.clicked.connect(slt)
            rr.addWidget(b)
            pl.addLayout(rr)
        ar = QHBoxLayout()
        ar.setSpacing(4)
        ab = QPushButton("＋ 添加到列表")
        # Fusion palette handles button style
        ab.clicked.connect(self._on_add)
        ar.addWidget(ab)
        self._rc = QComboBox()
        self._rc.addItem("📋 最近文件对")
        self._rc.currentIndexChanged.connect(self._on_recent)
        ar.addWidget(self._rc, 1)
        pl.addLayout(ar)
        r.addWidget(pg)

        # ── 文件对列表 ──
        qg = QGroupBox("文件对列表")
        ql = QVBoxLayout(qg)
        ql.setContentsMargins(6, 8, 6, 4)
        ql.setSpacing(3)

        # 标题栏 + 操作按钮行
        h = QHBoxLayout()
        h.setSpacing(4)
        self._qc = QLabel("文件 (0)")
        h.addWidget(self._qc)
        h.addStretch()
        for tx, handler, tip in [
            ("◀ 上一章", self._on_prev_chapter, "切换到上一章"),
            ("▶ 下一章", self._on_next_chapter, "切换到下一章"),
            ("删除", self._on_remove_selected, "从列表移除选中文件对"),
        ]:
            b = QPushButton(tx)
            b.setFixedHeight(22)
            b.setToolTip(tip)
            b.clicked.connect(handler)
            h.addWidget(b)
        ql.addLayout(h)

        filters = QHBoxLayout()
        filters.setSpacing(4)
        filters.addWidget(QLabel("状态"))
        self._status_filter = QComboBox()
        for label, value in (
            ("全部", "all"),
            ("未打开", REVIEW_UNOPENED),
            ("待确认", REVIEW_PENDING),
            ("已完成", REVIEW_COMPLETE),
        ):
            self._status_filter.addItem(label, value)
        self._status_filter.currentIndexChanged.connect(lambda _index: self._rebuild())
        filters.addWidget(self._status_filter)
        filters.addWidget(QLabel("完成范围"))
        self._review_scope = QComboBox()
        self._review_scope.addItem("当前筛选", "filtered")
        self._review_scope.addItem("全部异常", "all")
        self._review_scope.currentIndexChanged.connect(lambda _index: self._rebuild())
        filters.addWidget(self._review_scope)
        filters.addStretch()
        ql.addLayout(filters)

        self._qlw = QTableWidget(0, 5)
        self._qlw.setHorizontalHeaderLabels(
            ["序号", "状态", "内容节选", "文档 A", "文档 B"]
        )
        self._qlw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._qlw.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._qlw.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._qlw.setShowGrid(False)
        self._qlw.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._qlw.verticalHeader().setVisible(False)
        self._qlw.verticalHeader().setDefaultSectionSize(24)
        self._qlw.verticalHeader().setMinimumSectionSize(24)
        header = self._qlw.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._qlw.cellClicked.connect(self._on_row_clicked)
        self._qlw.setMinimumHeight(28)
        ql.addWidget(self._qlw, 1)
        qg.setMinimumHeight(160)
        r.addWidget(qg, 1)

        # 文档操作已移至 ReviewController

    def add_log_panel(self, log_panel):
        """将运行日志面板添加到文件管理面板底部。"""
        g = QGroupBox("📋 运行日志")
        g.setMinimumHeight(160)
        gl = QVBoxLayout(g)
        gl.setContentsMargins(4, 2, 4, 4)
        gl.setSpacing(1)
        gl.addWidget(log_panel, 1)
        r = self.layout()
        if r is not None:
            r.addWidget(g, 1)

    def _on_browse_src(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择文档 A", "", "Markdown (*.md);;Text (*.txt);;All (*)"
        )
        if p:
            self._se.setText(p)

    def _on_browse_tgt(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择文档 B", "", "Markdown (*.md);;Text (*.txt);;All (*)"
        )
        if p:
            self._te.setText(p)

    def _on_add(self):
        s = self._se.text().strip()
        t = self._te.text().strip()
        if not s or not t:
            return
        if not os.path.exists(s):
            print(f"⚠ 文档 A 不存在: {s}")
            return
        if not os.path.exists(t):
            print(f"⚠ 文档 B 不存在: {t}")
            return
        lb = Path(s).stem.split(".")[0]
        self._add_to_recent(lb, s, t)
        for it in self._queue:
            if it.src_path == s and it.tgt_path == t:
                self._select(it)
                self._se.clear()
                self._te.clear()
                return
        ni = FileQueueItem(label=lb, src_path=s, tgt_path=t)
        self._queue.append(ni)
        self._rebuild()
        self._select(ni)
        self._se.clear()
        self._te.clear()

    def _select(self, item: FileQueueItem):
        self._selected = item
        self._qlw.clearSelection()
        for row in range(self._qlw.rowCount()):
            cell = self._qlw.item(row, 0)
            if cell is not None and cell.data(Qt.ItemDataRole.UserRole) is item:
                self._qlw.setCurrentCell(row, 0)
                self._qlw.selectRow(row)
                break

    def selected_item(self):
        return self._selected

    def queue_items(self):
        """Return a snapshot of the file queue for document-level batch actions."""

        return list(self._queue)

    def _scope(self) -> str:
        return str(self._review_scope.currentData() or "filtered")

    def _visible_queue(self) -> list[tuple[int, FileQueueItem]]:
        selected_state = str(self._status_filter.currentData() or "all")
        scope = self._scope()
        return [
            (index, item)
            for index, item in enumerate(self._queue)
            if selected_state == "all" or item.review_state(scope) == selected_state
        ]

    @staticmethod
    def _status_tooltip(item: FileQueueItem, scope: str) -> str:
        state = item.review_state(scope)
        if state == REVIEW_UNOPENED:
            return "本次会话尚未打开"
        if not item._review_known:
            return "已打开，正在读取或建立审校状态"
        subjects, required = item.review_counts(scope)
        completed = subjects - required
        scope_label = "全部异常" if scope == "all" else "当前筛选"
        return f"{scope_label}：已人工确认 {completed}/{subjects}，待确认 {required}"

    def _status_widget(self, item: FileQueueItem, scope: str) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        checkbox = QCheckBox()
        checkbox.setTristate(True)
        state = item.review_state(scope)
        check_state = {
            REVIEW_UNOPENED: Qt.CheckState.Unchecked,
            REVIEW_PENDING: Qt.CheckState.PartiallyChecked,
            REVIEW_COMPLETE: Qt.CheckState.Checked,
        }[state]
        checkbox.setCheckState(check_state)
        checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        checkbox.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        tooltip = self._status_tooltip(item, scope)
        checkbox.setToolTip(tooltip)
        wrapper.setToolTip(tooltip)
        wrapper.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addStretch()
        layout.addWidget(checkbox)
        layout.addStretch()
        return wrapper

    def _copy_button(self, path: str, side: str) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(1, 1, 1, 1)
        button = QPushButton("复制")
        button.setFixedSize(42, 20)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(path or f"文档 {side} 路径为空")
        button.setEnabled(bool(path))
        button.clicked.connect(lambda _checked=False, p=path: self._copy_path(p))
        layout.addWidget(button)
        return wrapper

    @staticmethod
    def _copy_path(path: str) -> None:
        if not path:
            return
        QApplication.clipboard().setText(path)

    def _rebuild(self):
        """按当前状态范围和筛选条件重建文件对表格。"""
        self._qlw.blockSignals(True)
        self._qlw.clearContents()
        visible = self._visible_queue()
        self._qlw.setRowCount(len(visible))
        scope = self._scope()
        for row, (index, item) in enumerate(visible):
            ordinal = QTableWidgetItem(str(index))
            ordinal.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ordinal.setData(Qt.ItemDataRole.UserRole, item)
            self._qlw.setItem(row, 0, ordinal)
            status_cell = QTableWidgetItem("")
            status_cell.setToolTip(self._status_tooltip(item, scope))
            self._qlw.setItem(row, 1, status_cell)
            self._qlw.setCellWidget(row, 1, self._status_widget(item, scope))
            excerpt = item.source_excerpt()
            excerpt_cell = QTableWidgetItem(excerpt)
            excerpt_cell.setToolTip(excerpt)
            self._qlw.setItem(row, 2, excerpt_cell)
            self._qlw.setCellWidget(row, 3, self._copy_button(item.src_path, "A"))
            self._qlw.setCellWidget(row, 4, self._copy_button(item.tgt_path, "B"))
            self._qlw.setRowHeight(row, 24)
        self._qlw.blockSignals(False)
        self._qc.setText(f"文件 ({len(self._queue)})")
        if self._selected:
            self._select(self._selected)

    def _on_prev_chapter(self):
        self.chapter_nav_requested.emit(-1)

    def _on_next_chapter(self):
        self.chapter_nav_requested.emit(1)

    def _on_remove_selected(self):
        self.remove_selected()

    def _on_row_clicked(self, row: int, _column: int):
        cell = self._qlw.item(row, 0)
        it = cell.data(Qt.ItemDataRole.UserRole) if cell is not None else None
        if it is not None:
            self._selected = it
            self.pair_selected.emit(it)

    def _add_to_recent(self, lb, s, t):
        self._recent_pairs = [
            p for p in self._recent_pairs if not (p[1] == s and p[2] == t)
        ]
        self._recent_pairs.insert(0, (lb, s, t))
        if len(self._recent_pairs) > 20:
            self._recent_pairs = self._recent_pairs[:20]
        self._rrc()
        self._save_recent()

    def _load_recent(self):
        try:
            if os.path.isfile(self._RF):
                with open(self._RF, encoding="utf-8") as f:
                    return [
                        tuple(e)
                        for e in json.load(f)
                        if isinstance(e, list) and len(e) >= 3
                    ][:20]
        except Exception:
            pass
        return []

    def _save_recent(self):
        try:
            os.makedirs(os.path.dirname(self._RF), exist_ok=True)
            with open(self._RF, "w", encoding="utf-8") as f:
                json.dump(
                    self._recent_pairs, f, ensure_ascii=False, separators=(",", ":")
                )
        except Exception:
            import traceback

            traceback.print_exc()

    def _rrc(self):
        self._rc.blockSignals(True)
        self._rc.clear()
        self._rc.addItem("📋 最近文件对")
        for label, s, t in self._recent_pairs:
            self._rc.addItem(f"{label}  ({Path(s).name} ↔ {Path(t).name})")
        self._rc.blockSignals(False)

    def _on_recent(self, idx):
        if idx <= 0 or idx - 1 >= len(self._recent_pairs):
            return
        _, s, t = self._recent_pairs[idx - 1]
        self._se.setText(s)
        self._te.setText(t)

    # ── 外部接口 ──
    def get_recent_pairs(self):
        """返回最近文件对列表 [(label, src, tgt), ...]"""
        return list(self._recent_pairs)

    def remove_recent_pair(self, src_path: str, tgt_path: str):
        """从最近列表中移除指定文件对（文件不存在时自动清理用）。"""
        old_len = len(self._recent_pairs)
        self._recent_pairs = [
            p for p in self._recent_pairs if not (p[1] == src_path and p[2] == tgt_path)
        ]
        if len(self._recent_pairs) < old_len:
            self._rrc()
            self._save_recent()

    def set_queue(self, items):
        self._queue = list(items)
        self._selected = None
        self._rebuild()

    def add_to_queue(self, item):
        for e in self._queue:
            if e.src_path == item.src_path and e.tgt_path == item.tgt_path:
                self._select(e)
                return
        self._queue.append(item)
        self._rebuild()
        self._select(item)
        self._add_to_recent(item.label, item.src_path, item.tgt_path)

    def remove_selected(self):
        target = self._selected
        if target is None:
            selected = self._qlw.selectionModel().selectedRows(0)
            if selected:
                target = self._qlw.item(selected[0].row(), 0).data(
                    Qt.ItemDataRole.UserRole
                )
        if target is not None and target in self._queue:
            self._queue.remove(target)
            self._selected = None
            self._rebuild()

    def set_file_paths(self, s, t, label=""):
        lb = label or Path(s).stem.split(".")[0]
        fd = None
        for it in self._queue:
            if it.src_path == s and it.tgt_path == t:
                fd = it
                break
        if fd is None:
            fd = FileQueueItem(label=lb, src_path=s, tgt_path=t)
            self._queue.append(fd)
        fd.opened = True
        fd.label = lb
        self._select(fd)
        self._rebuild()
        self._add_to_recent(lb, s, t)

    def update_review_status(
        self,
        src_path: str,
        tgt_path: str,
        *,
        all_subjects: int,
        all_required: int,
        filtered_subjects: int,
        filtered_required: int,
    ) -> None:
        for item in self._queue:
            if item.src_path == src_path and item.tgt_path == tgt_path:
                changed = item.set_review_counts(
                    all_subjects=all_subjects,
                    all_required=all_required,
                    filtered_subjects=filtered_subjects,
                    filtered_required=filtered_required,
                )
                if changed:
                    self._rebuild()
                return

    def _nav_prev(self):
        visible = [item for _index, item in self._visible_queue()]
        if not visible or not self._selected:
            return
        idx = next((i for i, q in enumerate(visible) if q is self._selected), -1)
        if idx > 0:
            nxt = visible[idx - 1]
        elif idx == 0:
            nxt = visible[-1]
        else:
            return
        self._select(nxt)
        self.pair_selected.emit(nxt)

    def _nav_next(self):
        visible = [item for _index, item in self._visible_queue()]
        if not visible:
            return
        if self._selected is None:
            self._select(visible[0])
            self.pair_selected.emit(visible[0])
            return
        idx = next((i for i, q in enumerate(visible) if q is self._selected), -1)
        next_index = idx + 1 if idx + 1 < len(visible) else 0
        self._select(visible[next_index])
        self.pair_selected.emit(visible[next_index])
