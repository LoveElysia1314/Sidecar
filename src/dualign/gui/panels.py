"""Dualign panel layout and relation navigation helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDockWidget,
    QMenu,
    QScrollArea,
    QFrame,
    QSizePolicy,
)

# ═══════════════════════════════════════════════════════════════
# DockPanelHelper — 面板管理工具函数
# ═══════════════════════════════════════════════════════════════


class DockPanelHelper:
    """静态工具函数集合，用于面板管理操作。"""

    @staticmethod
    def move_to_opposite_side(dock: QDockWidget, main_window):
        """将当前面板移到对侧，与对侧已有面板标签页化。宽度锁定 360px。"""
        area = main_window.dockWidgetArea(dock)
        new_area = (
            Qt.RightDockWidgetArea
            if area == Qt.LeftDockWidgetArea
            else Qt.LeftDockWidgetArea
        )

        # 找对侧的第一个 dock 作为 tab 锚点
        dock_map = getattr(main_window, "_dock_map", {})
        target_tab = None
        for d in dock_map.values():
            if d is dock:
                continue
            if main_window.dockWidgetArea(d) == new_area:
                target_tab = d
                break

        main_window.removeDockWidget(dock)
        main_window.addDockWidget(new_area, dock)
        if target_tab:
            main_window.tabifyDockWidget(target_tab, dock)
        dock.show()
        dock.setFloating(False)
        # 锁定宽度 360px
        main_window.resizeDocks([dock], [360], Qt.Orientation.Horizontal)
        return new_area

    @staticmethod
    def toggle_single_column(main_window):
        """切换标签页/单栏模式。

        单栏模式：文件管理在上、审校面板在下，用 QSplitter 纵向并排放
        入同一个 Dock 中。避免 qt splitDockWidget 的跨平台问题。
        """
        dock_map = getattr(main_window, "_dock_map", {})
        review = dock_map.get("review")
        files = dock_map.get("files")
        if not review or not files:
            return

        from PySide6.QtWidgets import QScrollArea, QSplitter

        from PySide6.QtWidgets import QTabBar

        is_active = getattr(main_window, "_single_column_active", False)
        if is_active:
            # ── 切回标签页 ──
            container = getattr(main_window, "_single_column_container", None)
            if container:
                # 先提取内部控件，防止 container.deleteLater() 级联删除原始 widget
                for i in range(container.count()):
                    scroll = container.widget(i)
                    if scroll and isinstance(scroll, QScrollArea):
                        w = scroll.takeWidget()
                        if w:
                            w.setParent(None)
                container.deleteLater()
            main_window._single_column_active = False
            main_window._single_column_container = None

            # 恢复 QTabBar 显示
            _saved_tab_bar = getattr(main_window, "_single_column_tab_bar", None)
            if _saved_tab_bar:
                try:
                    _saved_tab_bar.show()
                except RuntimeError:
                    pass
                main_window._single_column_tab_bar = None

            # 使用保存的原始引用恢复两个 dock 的 widget
            review.setWidget(main_window._review_orig_widget)
            files.setWidget(main_window._files_orig_widget)
            files.show()

            main_window.tabifyDockWidget(files, review)
            review.raise_()
        else:
            # ── 切到单栏 ──
            # 为两个原始面板包裹 QScrollArea，放入同一 QSplitter
            # 注意：保存的 _orig_widget 在其父级被删除后 Qt 会析构，
            # 所以每次都要从 dock 的 widget() 树中重新提取。
            fil_widget = main_window._files_orig_widget
            rev_widget = main_window._review_orig_widget

            fil_scroll = QScrollArea()
            fil_scroll.setWidgetResizable(True)
            fil_scroll.setFrameShape(QFrame.NoFrame)
            fil_scroll.setWidget(fil_widget)

            rev_scroll = QScrollArea()
            rev_scroll.setWidgetResizable(True)
            rev_scroll.setFrameShape(QFrame.NoFrame)
            rev_scroll.setWidget(rev_widget)

            splitter = QSplitter(Qt.Vertical)
            splitter.setObjectName("_single_column_splitter")
            splitter.addWidget(fil_scroll)
            splitter.addWidget(rev_scroll)
            splitter.setSizes([200, 300])
            # 分隔线样式：加粗、醒目
            splitter.setHandleWidth(4)
            splitter.setStyleSheet(
                "QSplitter::handle{background:palette(mid);}"
                "QSplitter::handle:hover{background:palette(highlight);}"
            )

            # 隐藏 QTabBar（左栏已无多标签需求）
            for tb in main_window.findChildren(QTabBar):
                if tb.isVisible():
                    main_window._single_column_tab_bar = tb
                    tb.hide()
                    break

            # 替换 review dock 内容为 splitter
            review.setWidget(splitter)
            review.show()

            # files dock 隐藏
            files.hide()

            main_window._single_column_container = splitter
            main_window._single_column_active = True

        main_window._schedule_settings_save()

    @staticmethod
    def build_panel_context_menu(
        dock: QDockWidget,
        panel_id: str,
        main_window,
        dock_map: dict,
        pos: QPoint,
    ):
        """构建面板右键菜单。"""
        menu = QMenu(main_window)

        menu.addAction("🔄  移动到对侧").triggered.connect(
            lambda: DockPanelHelper.move_to_opposite_side(dock, main_window)
        )

        # 单栏布局开关（使用原生 QAction 的 checkable 状态）
        split_action = menu.addAction("单栏布局")
        split_action.setCheckable(True)
        split_action.setChecked(getattr(main_window, "_single_column_active", False))
        split_action.setToolTip("单栏时文管在上、审校在下，2:3 比例")
        split_action.triggered.connect(
            lambda checked: DockPanelHelper.toggle_single_column(main_window)
        )

        menu.addAction("✖  关闭").triggered.connect(dock.close)
        menu.addSeparator()
        menu.addAction("🔄  重置布局").triggered.connect(
            getattr(main_window, "_on_reset_layout", lambda: None)
        )

        menu.exec(pos)


# ═══════════════════════════════════════════════════════════════
# RelationIndicator — 导航组（章节 + 文本对）
# ═══════════════════════════════════════════════════════════════


class RelationIndicator(QWidget):
    """四按钮导航组件：◀◀上一章 ◀上一条 下一条▶ 下一章▶▶"""

    # 章节导航
    prev_chapter = Signal()
    next_chapter = Signal()
    # 文本对导航
    go_prev = Signal()
    go_next = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._prev_chapter_btn = QPushButton("◀◀ 上一章")
        self._prev_chapter_btn.clicked.connect(self.prev_chapter.emit)
        layout.addWidget(self._prev_chapter_btn)

        self._prev_btn = QPushButton("◀ 上一条")
        self._prev_btn.clicked.connect(self.go_prev.emit)
        layout.addWidget(self._prev_btn)

        self._next_btn = QPushButton("下一条 ▶")
        self._next_btn.clicked.connect(self.go_next.emit)
        layout.addWidget(self._next_btn)

        self._next_chapter_btn = QPushButton("下一章 ▶▶")
        self._next_chapter_btn.clicked.connect(self.next_chapter.emit)
        layout.addWidget(self._next_chapter_btn)

    def set_enabled(self, has_prev: bool, has_next: bool):
        self._prev_btn.setEnabled(has_prev)
        self._next_btn.setEnabled(has_next)

    def set_preview_mode(self, active: bool):
        """预览模式：仅禁用文本对导航（上一条/下一条），章节导航保持可用。"""
        enabled = not active
        self._prev_btn.setEnabled(enabled)
        self._next_btn.setEnabled(enabled)
