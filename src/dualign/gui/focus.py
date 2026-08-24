"""
Dualign — FocusManager: 统一焦点与选中管理

集中管理所有组件的焦点状态，通过 3 个信号驱动 UI 同步。
消除分散的选择、当前序号、异常位置和 AI 动作焦点状态。
"""

from __future__ import annotations

from typing import Optional, Set

from PySide6.QtCore import QObject, Signal

from dualign.models.action import RepairAction


class FocusManager(QObject):
    """统一焦点管理器。

    集中管理：
      - focused_ordinal:     对齐表的焦点关系序号（同步到预览表和定位器）
      - selected_ordinals:   对齐表的选中关系序号集合（Ctrl/Shift 选择）
      - focused_action:      AI 建议的焦点操作
      - anomaly_index:       异常导航索引（◀▶）
      - force_show_ordinals: 跨筛选强制显示的关系序号集合（AI 跨区建议）
      - source:              最后一次焦点来源 ("table"|"review"|"ai")

    信号（3 个，替代当前所有分散信号）:
      relation_focused    → 对齐表滚动+高亮 + preview表高亮 + 定位器更新
      selection_changed   → _emit_indicator 更新定位器
      action_focused      → AI 按钮状态变更
    """

    relation_focused = Signal(int)  # relation ordinal
    selection_changed = Signal(set)  # Set[int]
    action_focused = Signal(object)  # RepairAction | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.focused_ordinal: Optional[int] = None
        self.selected_ordinals: Set[int] = set()
        self.focused_action: Optional[RepairAction] = None
        self.anomaly_index: int = -1
        self.force_show_ordinals: Set[int] = set()
        self.source: str = "table"  # "table" | "review" | "ai"
        self._sync_lock: bool = False

    # ══════════════════════════════════════════════════════════
    # 统一入口
    # ══════════════════════════════════════════════════════════

    def go_to_ordinal(self, ordinal: int, source: str = "table"):
        """聚焦一个关系序号（3 组件同步入口）。

        等同于旧的 _on_go_to_row，但纯状态 + 信号，
        由各组件的 slot 响应信号做 UI 操作。
        """
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            self.focused_ordinal = ordinal
            self.source = source
            self.selected_ordinals = {ordinal}
            self.relation_focused.emit(ordinal)
            self.selection_changed.emit(self.selected_ordinals)
        finally:
            self._sync_lock = False

    def select_ordinals(self, ordinals: Set[int], source: str = "table"):
        """批量选中关系序号。"""
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            self.selected_ordinals = ordinals
            if ordinals:
                self.focused_ordinal = min(ordinals)
            self.source = source
            self.selection_changed.emit(ordinals)
        finally:
            self._sync_lock = False

    def focus_action(self, action: Optional[RepairAction]):
        """聚焦一条 AI 建议。

        设置 focused_action + force_show_ordinals，
        以便 _apply_filter 能强制显示涉及的所有关系。
        """
        if self._sync_lock:
            return
        self._sync_lock = True
        try:
            self.focused_action = action
            if action is not None:
                self.source = "ai"
                self.force_show_ordinals = set(action.operation_indices)
            else:
                self.force_show_ordinals = set()
            self.action_focused.emit(action)
        finally:
            self._sync_lock = False

    def navigate_anomaly(self, idx: int):
        """异常导航：设置 anomaly_index；关系焦点由调用方设置。"""
        self.anomaly_index = idx

    def clear_force_show(self):
        """清除跨筛选强制显示标记。"""
        self.force_show_ordinals = set()

    def clear(self):
        """清除所有焦点状态。"""
        self.focused_ordinal = None
        self.selected_ordinals = set()
        self.anomaly_index = -1
        self.clear_force_show()
        self.focus_action(None)
