"""
Dualign — ReviewController: 审校面板 + AI 校订控制器

以当前关系序号（ordinals）为单元进行定位和操作。
所有操作委托给 DualignWindow（window 再委托给 RepairService）。
AI 校订（Agent 模式）直接内建于此面板。
"""

from __future__ import annotations

import os
from typing import List, Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QComboBox,
    QCheckBox,
    QSizePolicy,
)
from PySide6.QtGui import QDesktopServices

from dualign.models.action import RepairAction
from dualign.models.action import AiProposalStore
from dualign.models.relation_status import RelationAnomaly
from dualign.gui.preview_table import AiSuggestionItem
from dualign.gui.preview_table import SuggestionPreviewTable
from dualign.gui.filter import FilterPanel

REVIEW_SHORTCUTS = {
    "merge": "M",
    "split": "S",
    "edit": "E",
    "ok": "O",
    "flag": "F",
    "delete": "Delete",
    "placeholder": "P",
    "reset": "Ctrl+R",
}


def _next_suggestion_ordinal(
    items: list[AiSuggestionItem], current_ordinal: int | None, step: int
) -> int | None:
    """Return the adjacent visible suggestion ordinal, wrapping at either end."""
    ordinals = list(dict.fromkeys(item.ordinal for item in items))
    if not ordinals:
        return None
    if current_ordinal not in ordinals:
        return ordinals[0] if step > 0 else ordinals[-1]
    return ordinals[(ordinals.index(current_ordinal) + step) % len(ordinals)]


from dualign.services.ai_repair_agent import (
    AiRepairAgent,
    ChapterContext,
    build_chapter_context,
    AgentEvent,
    MaxTurnsExceeded,
)
from dualign.gui.theme import T, disabled_fg

if TYPE_CHECKING:
    from dualign.gui.window import DualignWindow


# ═══════════════════════════════════════════════════════════════
# AgentRunThread — 后台运行 AiRepairAgent
# ═══════════════════════════════════════════════════════════════


class AgentRunThread(QThread):
    """后台运行 AiRepairAgent，通过 Qt 信号报告每步事件。

    内部自动构造拟修复（auto_repair），确保工作线程内 w._repair_state
    与 AI 看到的文本一致，不阻塞主线程。
    """

    event_occurred = Signal(object)  # AgentEvent
    finished_actions = Signal(list)  # List[RepairAction]
    error_occurred = Signal(str)

    def __init__(
        self,
        ctx,
        backend: str = "deepseek",
        max_turns: int = 20,
        model=None,
        strategy: str = "src",
        parent=None,
        model_name: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        repair_state=None,
    ):
        super().__init__(parent)
        self._ctx = ctx
        self._backend = backend
        self._max_turns = max_turns
        self._model = model
        self._strategy = strategy
        self._model_name = model_name
        self._base_url = base_url
        self._api_key = api_key
        self._repair_state = repair_state
        # 日志导出用 — agent.run 执行后由 run() 写入
        self.turn_log: list = []
        self.agent_ctx = ctx
        self.token_stats: dict = {"prompt": 0, "cache": 0, "completion": 0}
        self.elapsed: float = 0.0

    def run(self):
        try:
            import time as _time

            _start = _time.time()
            # ── 拟修复（异步线程内构造，不阻塞主线程）──
            ctx = self._ctx
            if self._repair_state is not None:
                from dualign.services.ai_repair_agent import (
                    build_agent_review_session,
                )

                session = build_agent_review_session(
                    self._repair_state,
                    strategy=self._strategy,
                    model=self._model,
                    reviewable_ids=self._ctx.reviewable_ids,
                )
                self._repair_state = session.proposed_state
                ctx = session.context

            agent = AiRepairAgent(
                backend=self._backend,
                max_turns=self._max_turns,
                verbose=False,
                model=self._model,
                strategy=self._strategy,
                model_name=self._model_name,
                base_url=self._base_url,
                api_key=self._api_key,
            )

            # ── 收集 turn_log 和 token 统计（用于日志导出）──
            _local_turn_log: list = []
            _token_stats = {"prompt": 0, "cache": 0, "completion": 0}

            def _wrapped_on_event(evt):
                if evt.type == "done" and hasattr(evt, "turn_log"):
                    _local_turn_log[:] = list(evt.turn_log)
                if evt.type == "llm_response" and evt.usage:
                    _token_stats["prompt"] += evt.usage.get("prompt_tokens", 0)
                    _token_stats["cache"] += evt.usage.get("cached_tokens", 0)
                    _token_stats["completion"] += evt.usage.get("completion_tokens", 0)
                self._on_agent_event(evt)

            actions = agent.run(
                ctx, on_event=_wrapped_on_event, initial_state=self._repair_state
            )
            self.turn_log = _local_turn_log
            self.token_stats = _token_stats
            self.agent_ctx = ctx
            self.elapsed = _time.time() - _start
            self.finished_actions.emit(actions)
        except MaxTurnsExceeded as e:
            self.error_occurred.emit(f"Agent 超时: {e}")
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _on_agent_event(self, evt: AgentEvent):
        self.event_occurred.emit(evt)


class ReviewController(QWidget):
    """审校面板 + AI 校订控制器。

    定位器以初始对齐关系（ordinals）为单元。
    操作按钮根据 valid_operations 动态启用/禁用。
    """

    go_to_row = Signal(int)
    next_chapter_requested = Signal()
    prev_chapter_requested = Signal()
    action_requested = Signal(object)  # RepairAction — AI 建议被采纳
    batch_finished = Signal()
    ai_error = Signal(str)  # AI 校订错误 → 窗口写入 ai_review
    actions_updated = Signal()
    log_message = Signal(str, str)  # (message, role) — 转发给 LogPanel
    # ── 文档操作 signals（从 WorkspacePanel 移入）──
    doc_align_requested = Signal()
    doc_auto_repair_requested = Signal()
    doc_reset_repair_requested = Signal()
    doc_realign_requested = Signal()
    doc_ai_chapter_requested = Signal()
    doc_remove_requested = Signal()
    doc_overwrite_requested = Signal()
    strategy_changed = Signal(int)
    auto_next_chapter_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window: Optional[DualignWindow] = None
        self._anomalies: List[RelationAnomaly] = []
        self._current_idx: int = -1
        self._btn_refs: dict = {}
        # AI 校订状态
        self._backend = "deepseek"
        self._auto_approve_enabled = False
        self._batch_mode = False
        self._active_threads: list = []
        # 焦点跟踪：当前聚焦的 AI 建议
        self._focused_action: Optional[RepairAction] = None
        self._suggestions: list[AiSuggestionItem] = []
        # ── 内嵌筛选面板（不再从外部注入）──
        self._filter_panel = FilterPanel()
        self._filter_panel.filter_changed.connect(self._on_filter_changed)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._build_ui()

    def minimumSizeHint(self):
        """不传播最小宽度约束——dock 已被 QScrollArea 包裹，可自由滚动。"""
        from PySide6.QtCore import QSize

        return QSize(0, super().minimumSizeHint().height())

    @property
    def _pending_action_list(self) -> List[RepairAction]:
        """从 ai_proposal_store 派生待处理建议列表。"""
        actions = []
        w = self._window
        if w and w._repair_state:
            store = w._repair_state.ai_proposal_store
            for p in store.get_pending():
                actions.append(p.action)
        return actions

    def set_window(self, window: DualignWindow):
        self._window = window

    def _on_filter_changed(self):
        """转发筛选变更到主窗口。"""

        w = self._window
        if w is not None:
            w._apply_filter()
            w._schedule_settings_save()

    @property
    def filter_panel(self) -> FilterPanel:
        return self._filter_panel

    def set_backend(self, backend: str):
        self._backend = backend

    def set_ai_enabled(self, enabled: bool):
        """启用/禁用 AI 审校相关按钮。"""
        for key in ("suggest",):
            btn = self._btn_refs.get(key)
            if btn:
                btn.setEnabled(enabled)
        if self._ai_review_btn is not None:
            self._ai_review_btn.setEnabled(enabled)

    def set_data_loaded(self, loaded: bool):
        """启用/禁用所有修复操作按钮（AI 审校按钮不受数据加载影响）。"""
        for key in (
            "merge",
            "split",
            "edit",
            "ok",
            "flag",
            "delete",
            "placeholder",
            "reset",
        ):
            btn = self._btn_refs.get(key)
            if btn:
                btn.setEnabled(loaded)

    def create_ai_panel(self) -> QWidget:
        """创建 AI 建议表格面板（放入底部栏）。无需额外标题框——底部栏已有标题。"""

        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        panel.setMinimumWidth(200)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._preview_table = SuggestionPreviewTable()
        self._preview_table.table.itemClicked.connect(
            lambda it: self._on_ai_table_row_clicked(it)
        )
        layout.addWidget(self._preview_table, 1)

        # 空状态提示标签（表格无 item 时显示）
        self._ai_empty_lbl = QLabel("")
        self._ai_empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ai_empty_lbl.setStyleSheet(
            f"color:{T.FG_SECONDARY}; font-size:12px; padding:20px;"
        )
        self._ai_empty_lbl.setVisible(False)
        layout.addWidget(self._ai_empty_lbl)

        return panel

    def _on_ai_table_row_clicked(self, item):
        """预览表行点击 → 展开未显示的关系后定位。"""
        row = item.row()
        items = getattr(self._preview_table, "_items", [])
        if row < len(items):
            it = items[row]
            self._focus_suggestion(it.action, it.ordinal)

    def _focus_suggestion(self, action: RepairAction, ordinal: int):
        """展开并定位一条建议；供点击和建议导航共同使用。"""
        self._set_focused_action(action)
        w = self._window
        if w and hasattr(w, "_refresh"):
            w._refresh()
        QTimer.singleShot(0, lambda: self.go_to_row.emit(ordinal))

    # ── 文档摘要 ──

    def set_summary_chapter(self, chapter: str = ""):
        """设置章节进度标签。"""
        if hasattr(self, "_summary_chapter"):
            self._summary_chapter.setText(chapter if chapter else "")
            self._summary_chapter.setVisible(bool(chapter))

    def set_summary_paths(self, src_path: str, tgt_path: str):
        """设置文档 A/B 路径摘要（完整文件名 + 超链接）。"""
        import os.path as _osp

        src_name = _osp.basename(src_path) if src_path else "—"
        tgt_name = _osp.basename(tgt_path) if tgt_path else "—"
        if hasattr(self, "_summary_src"):
            self._summary_src.setText(
                '<span style="color:palette(text);">文档 A：</span>'
                f'<a href="file:///{src_path}" style="color:palette(link);'
                f'text-decoration:none;">{src_name}</a>'
            )
            self._summary_src.setToolTip(src_path)
        if hasattr(self, "_summary_tgt"):
            self._summary_tgt.setText(
                '<span style="color:palette(text);">文档 B：</span>'
                f'<a href="file:///{tgt_path}" style="color:palette(link);'
                f'text-decoration:none;">{tgt_name}</a>'
            )
            self._summary_tgt.setToolTip(tgt_path)

    def set_summary_cells(self, *cells):
        """设置 6 格摘要文本，按 (row0col0, row0col1, row0col2, row1col0, row1col1, row1col2) 顺序。
        缺省值重置为「—」。
        """
        if hasattr(self, "_sc"):
            for i, lbl in enumerate(self._sc):
                val = cells[i] if i < len(cells) else None
                lbl.setText(val if val is not None else "—")

    # ── UI 构建 ──

    # ═══════════════════════════════════════════════════════════
    # 面板构建
    # ═══════════════════════════════════════════════════════════

    def _build_ui(self):
        """主构建入口：文档摘要 → 筛选面板 → 校订操作 → 文档操作 + 章节导航。

        全屏时整体纵向居中，对侧无面板时剩余空间在 dock 内均匀分配。
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 2)
        layout.setSpacing(2)

        # 顶部弹性空间（全屏时向下推）
        layout.addStretch()
        # 内容
        self._build_summary(layout)
        layout.addWidget(self._filter_panel)
        self._add_review_panel(layout)
        # 底部弹性空间（全屏时向上推，达成纵向居中）
        layout.addStretch()

    def _build_summary(self, layout: QVBoxLayout):
        """文档摘要（4 行 × 3 列等距网格）。

        row0: 文档 A：fullname（超链接，跨 3 列）
        row1: 文档 B：fullname（超链接，跨 3 列）
        row2: 文档 A 块数 | 文档 B 块数 | 关系均分
        row3: 单调脚手架 | 顺序链外 | 分歧区
        末尾：章节进度
        """
        g = QGroupBox("文档摘要")
        sg = QGridLayout()
        sg.setContentsMargins(6, 4, 6, 6)
        sg.setSpacing(2)

        # row 0: 原文链接（跨 3 列，可选中）
        self._summary_src = QLabel("—")
        self._summary_src.setTextFormat(Qt.TextFormat.RichText)
        self._summary_src.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._summary_src.setStyleSheet(
            "font-size:11px;border:none;background:transparent;font-weight:600;"
        )
        self._summary_src.linkActivated.connect(self._on_summary_link)
        sg.addWidget(self._summary_src, 0, 0, 1, 3)

        # row 1: 译文链接（跨 3 列，可选中）
        self._summary_tgt = QLabel("—")
        self._summary_tgt.setTextFormat(Qt.TextFormat.RichText)
        self._summary_tgt.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._summary_tgt.setStyleSheet(
            "font-size:11px;border:none;background:transparent;font-weight:600;"
        )
        self._summary_tgt.linkActivated.connect(self._on_summary_link)
        sg.addWidget(self._summary_tgt, 1, 0, 1, 3)

        # row 2-3: 6 格指标
        self._sc: list[QLabel] = []
        for ri in range(2):
            for ci in range(3):
                lbl = QLabel("—")
                lbl.setStyleSheet("font-size:11px;border:none;background:transparent;")
                lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                sg.addWidget(lbl, ri + 2, ci)
                self._sc.append(lbl)

        # 章节进度（末尾，跨 3 列）
        self._summary_chapter = QLabel("")
        self._summary_chapter.setStyleSheet(
            "font-size:11px;color:palette(mid);border:none;background:transparent;"
        )
        self._summary_chapter.setVisible(False)
        self._summary_chapter.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        sg.addWidget(self._summary_chapter, 4, 0, 1, 3)

        for _ci in range(3):
            sg.setColumnStretch(_ci, 1)
        g.setLayout(sg)
        layout.addWidget(g)

    def _on_summary_link(self, url: str):
        QDesktopServices.openUrl(QUrl(url))

    # ── 校订操作 ──

    def _add_review_panel(self, layout: QVBoxLayout):
        """构建审校面板主体：文档操作 → 异常导航 → 校订操作 → AI 审校。"""

        # ── 文档操作（4 列网格）──
        g_doc = QGroupBox("文档操作")
        cl = QVBoxLayout(g_doc)
        cl.setContentsMargins(4, 2, 4, 4)
        cl.setSpacing(2)
        self._doc_btns: dict[str, QPushButton] = {}
        dg = QGridLayout()
        dg.setSpacing(2)
        for ci, (key, lb, sig) in enumerate(
            [
                ("realign", "重新对齐", self.doc_realign_requested),
                ("auto_repair", "自动校订", self.doc_auto_repair_requested),
                ("reset_repair", "重置校订", self.doc_reset_repair_requested),
                ("overwrite", "固化修改…", self.doc_overwrite_requested),
            ]
        ):
            b = QPushButton(lb)
            b.clicked.connect(self._mk_emit(sig))
            dg.addWidget(b, 0, ci)
            self._doc_btns[key] = b
        # 策略选择只占一列；剩余两列用于章节级工作流选项。
        dg.addWidget(QLabel("对齐策略："), 1, 0)
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(["最小信息量", "文档A为准", "文档B为准"])
        self._strategy_combo.setCurrentIndex(1)
        self._strategy_combo.currentIndexChanged.connect(self.strategy_changed.emit)
        self._strategy_combo.setMinimumContentsLength(6)
        self._strategy_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        dg.addWidget(self._strategy_combo, 1, 1)
        self._auto_next_chapter_cb = QCheckBox("校订完成后跳转下一章")
        self._auto_next_chapter_cb.setChecked(False)
        self._auto_next_chapter_cb.toggled.connect(self.auto_next_chapter_changed.emit)
        dg.addWidget(self._auto_next_chapter_cb, 1, 2, 1, 2)
        for ci, (key, lb, handler) in enumerate(
            [
                ("undo", "撤销", self._on_undo),
                ("redo", "恢复", self._on_redo),
            ],
            start=0,
        ):
            b = QPushButton(lb)
            b.clicked.connect(handler)
            b.setEnabled(False)
            dg.addWidget(b, 2, ci * 2, 1, 2)
            self._doc_btns[key] = b
        for _ci in range(4):
            dg.setColumnStretch(_ci, 1)
        cl.addLayout(dg)
        layout.addWidget(g_doc)

        # ── 章节和文本对定位 ──
        g_nav = QGroupBox("章节和文本对定位")
        nl = QVBoxLayout(g_nav)
        nl.setContentsMargins(4, 4, 4, 4)

        from dualign.gui.panels import RelationIndicator

        self._relation_indicator = RelationIndicator()
        self._relation_indicator.go_prev.connect(self._go_prev)
        self._relation_indicator.go_next.connect(self._go_next)
        self._relation_indicator.prev_chapter.connect(self.prev_chapter_requested.emit)
        self._relation_indicator.next_chapter.connect(self.next_chapter_requested.emit)
        nl.addWidget(self._relation_indicator)
        layout.addWidget(g_nav)

        # ── 校订操作（4 列网格，2 行，按钮带彩色操作标记）──
        g_rep = QGroupBox("校订操作")
        rl = QVBoxLayout(g_rep)
        rl.setContentsMargins(4, 2, 4, 4)
        rl.setSpacing(2)
        rg = QGridLayout()
        rg.setSpacing(2)

        _MARKER_TAG = {
            "merge": " [M]",
            "split": " [S]",
            "edit": " [E]",
            "ok": " [OK]",
            "flag": " [F]",
            "delete": " [D]",
            "placeholder": " [P]",
        }
        _BTN_COLOR = {
            "merge": "#42A5F5",
            "split": "#26A69A",
            "edit": "#7E57C2",
            "ok": "#4CAF50",
            "flag": "#FF8A65",
            "delete": "#e53935",
            "placeholder": "#90A4AE",
        }

        for ci, (key, label, handler) in enumerate(
            [
                ("merge", "合并", self._on_merge),
                ("split", "拆分", self._on_split),
                ("edit", "校订", self._on_edit),
                ("ok", "通过", self._on_ok),
            ]
        ):
            btn = QPushButton(label + _MARKER_TAG.get(key, ""))
            btn.clicked.connect(handler)
            color = _BTN_COLOR.get(key, "#000")
            btn.setStyleSheet(
                f"QPushButton{{color:{color};}}QPushButton:disabled{{color:{disabled_fg()};}}"
            )
            btn.setToolTip(f"{label}（快捷键：{REVIEW_SHORTCUTS[key]}）")
            rg.addWidget(btn, 0, ci)
            self._btn_refs[key] = btn
        for ci, (key, label, handler) in enumerate(
            [
                ("flag", "标记", self._on_flag),
                ("delete", "删除", self._on_delete),
                ("placeholder", "占位", self._on_placeholder),
                ("reset", "重置", self._on_reset_current),
            ]
        ):
            if key == "reset":
                btn = QPushButton(label)
                btn.clicked.connect(handler)
                btn.setToolTip(f"{label}（快捷键：{REVIEW_SHORTCUTS[key]}）")
                rg.addWidget(btn, 1, ci)
                self._btn_refs[key] = btn
            else:
                btn = QPushButton(label + _MARKER_TAG.get(key, ""))
                btn.clicked.connect(handler)
                color = _BTN_COLOR.get(key, "#000")
                btn.setStyleSheet(
                    f"QPushButton{{color:{color};}}QPushButton:disabled{{color:{disabled_fg()};}}"
                )
                btn.setToolTip(f"{label}（快捷键：{REVIEW_SHORTCUTS[key]}）")
                rg.addWidget(btn, 1, ci)
                self._btn_refs[key] = btn
        for _ci in range(4):
            rg.setColumnStretch(_ci, 1)
        rl.addLayout(rg)
        layout.addWidget(g_rep)
        self._g_rep = g_rep  # 预览模式隐藏

        # ── AI 审校（4 列等距网格）──
        g_ai = QGroupBox("AI 审校")
        ag = QGridLayout(g_ai)
        ag.setContentsMargins(4, 2, 4, 4)
        ag.setSpacing(2)

        # row 0: 操作按钮
        self._btn_refs["suggest"] = QPushButton("审校本条")
        self._btn_refs["suggest"].clicked.connect(self._on_ai_analyze)
        ag.addWidget(self._btn_refs["suggest"], 0, 0)
        self._ai_review_btn = QPushButton("一键审校")
        self._ai_review_btn.clicked.connect(
            lambda: self.doc_ai_chapter_requested.emit()
        )
        ag.addWidget(self._ai_review_btn, 0, 1)
        self._apply_all_btn = QPushButton("一键应用")
        self._apply_all_btn.clicked.connect(self._apply_all_pending)
        ag.addWidget(self._apply_all_btn, 0, 2)
        self._ai_clear_btn = QPushButton("清除建议")
        self._ai_clear_btn.clicked.connect(self.clear_all_suggestions)
        ag.addWidget(self._ai_clear_btn, 0, 3)

        # row 1: 建议导航 + 采纳/拒绝/撤销（三按钮合并在一个容器，撤销替换未用位置）
        self._prev_suggestion_btn = QPushButton("◀ 上一建议")
        self._prev_suggestion_btn.clicked.connect(self._on_prev_suggestion)
        ag.addWidget(self._prev_suggestion_btn, 1, 0)
        self._next_suggestion_btn = QPushButton("下一建议 ▶")
        self._next_suggestion_btn.clicked.connect(self._on_next_suggestion)
        ag.addWidget(self._next_suggestion_btn, 1, 1)

        # 应用/拒绝/撤销 合并容器（占 2 列）
        self._action_btns_wrap = QWidget()
        action_layout = QHBoxLayout(self._action_btns_wrap)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)

        self._ai_accept_btn = QPushButton("✅ 应用")
        self._ai_accept_btn.clicked.connect(self._on_ai_accept_focused)
        action_layout.addWidget(self._ai_accept_btn, 1)

        self._ai_reject_btn = QPushButton("❌ 拒绝")
        self._ai_reject_btn.clicked.connect(self._on_ai_reject_focused)
        action_layout.addWidget(self._ai_reject_btn, 1)

        self._ai_restore_btn = QPushButton("↩ 撤销")
        self._ai_restore_btn.clicked.connect(self._on_ai_restore_focused)
        self._ai_restore_btn.setVisible(False)  # 默认隐藏，应用/拒绝后替换未用按钮位置
        action_layout.addWidget(self._ai_restore_btn, 1)

        ag.addWidget(self._action_btns_wrap, 1, 2, 1, 2)  # row 1, col 2, 占 1 行 2 列

        for _ci in range(4):
            ag.setColumnStretch(_ci, 1)
        layout.addWidget(g_ai)
        self._g_ai = g_ai  # 预览模式隐藏

        # 文档摘要已移至 WorkspacePanel（文件管理面板）首位

    # ═══════════════════════════════════════════════════════════
    # 公开方法
    # ── 文档操作辅助方法与控权（从 WorkspacePanel 移入）──

    @staticmethod
    def _mk_emit(sig):
        return lambda: sig.emit()

    def set_gating(
        self,
        ollama_ok: bool = True,
        model_ok: bool = True,
        ai_ok: bool = True,
        data_loaded: bool = False,
    ):
        """根据环境能力启用/禁用文档操作按钮。"""
        can_align = ollama_ok and model_ok
        can_edit = data_loaded
        gating = {
            "auto_repair": can_edit,
            "reset_repair": can_edit,
            "realign": can_align and data_loaded,
            "overwrite": can_edit,
        }
        for key, enabled in gating.items():
            btn = self._doc_btns.get(key)
            if btn:
                btn.setEnabled(enabled)

    def set_strategy_index(self, idx: int):
        if self._strategy_combo is not None:
            self._strategy_combo.setCurrentIndex(idx)

    def get_strategy_index(self) -> int:
        if self._strategy_combo is not None:
            return self._strategy_combo.currentIndex()
        return 1

    def set_auto_next_chapter(self, enabled: bool):
        self._auto_next_chapter_cb.setChecked(enabled)

    def auto_next_chapter(self) -> bool:
        return self._auto_next_chapter_cb.isChecked()

    def set_history_enabled(self, can_undo: bool, can_redo: bool):
        """历史按钮只由主窗口的撤销/恢复栈控制。"""
        self._doc_btns["undo"].setEnabled(can_undo)
        self._doc_btns["redo"].setEnabled(can_redo)

    def _sync_menu_actions(self):
        sync = (
            getattr(self._window, "_sync_review_menu_actions", None)
            if self._window is not None
            else None
        )
        if sync is not None:
            sync()

    # ── 预览模式 ──

    def set_preview_mode(self, active: bool):
        """预览模式：禁用依赖关系投影的控件组（灰显），不隐藏。

        预览模式按原始行平坦排列，无关系投影，
        校订操作 / AI 审校 / 导航 / 筛选全部不可用。
        """
        enabled = not active
        # 校订操作组（stylesheets 已含 :disabled 规则，禁用即灰显）
        for key in (
            "merge",
            "split",
            "edit",
            "ok",
            "flag",
            "delete",
            "placeholder",
            "reset",
        ):
            btn = self._btn_refs.get(key)
            if btn:
                btn.setEnabled(enabled)
        # 章节和文本对导航（文本对按钮在 RelationIndicator 内已处理）
        if hasattr(self, "_relation_indicator"):
            self._relation_indicator.set_preview_mode(active)
        # AI 审校组
        for ref in (
            "_ai_review_btn",
            "_apply_all_btn",
            "_ai_clear_btn",
            "_prev_suggestion_btn",
            "_next_suggestion_btn",
            "_ai_accept_btn",
            "_ai_reject_btn",
            "_ai_restore_btn",
        ):
            w = getattr(self, ref, None)
            if w is not None:
                w.setEnabled(enabled)
        btn = self._btn_refs.get("suggest")
        if btn:
            btn.setEnabled(enabled)
        # 禁用 QGroupBox 使内部所有控件灰显（保留 undo/redo 等）
        if hasattr(self, "_g_rep"):
            self._g_rep.setEnabled(enabled)
        if hasattr(self, "_g_ai"):
            self._g_ai.setEnabled(enabled)
        # 筛选面板：禁用显示选项和筛选组
        fp = getattr(self, "_filter_panel", None)
        if fp:
            if hasattr(fp, "_filter_group"):
                fp._filter_group.setEnabled(enabled)
            if hasattr(fp, "_display_group"):
                fp._display_group.setEnabled(enabled)
        self._sync_menu_actions()

    # ═══════════════════════════════════════════════════════════
    def set_anomalies(
        self, anomalies: List[RelationAnomaly], preserve_position: bool = True
    ):
        old_ordinal = self._current_ordinal()
        self._anomalies = anomalies

        if preserve_position and old_ordinal is not None:
            for i, anomaly in enumerate(anomalies):
                if old_ordinal in anomaly.ordinals:
                    self._current_idx = i
                    break
            else:
                self._current_idx = 0 if anomalies else -1
        else:
            self._current_idx = 0 if anomalies else -1

        self._update_display()

    def show_browsing(self, ordinals: List[int]):
        """进入浏览模式：更新关系位置，不触发表格滚动。"""
        self._current_idx = -1
        sb = getattr(self._window, "_status_bar", None) if self._window else None
        if sb:
            pos_text = (
                "—"
                if not ordinals
                else "-/" + str(len(self._anomalies) if self._anomalies else 0)
            )
            sb.set_pos(pos_text)
        if ordinals:
            self._update_browse_button_states(ordinals[0])

    # ═══════════════════════════════════════════════════════════
    # 撤销/恢复（委托给主窗口）
    # ═══════════════════════════════════════════════════════════

    def _on_undo(self):
        if self._window:
            self._window._on_undo()

    def _on_redo(self):
        if self._window:
            self._window._on_redo()

    # ── 浏览模式按钮状态 ──

    def _update_browse_button_states(self, ordinal: int):
        """浏览模式下基于关系内容动态启用操作按钮。"""
        w = self._window
        if w is None or w._repair_state is None:
            self._disable_all_buttons()
            return
        snapshot = w._repair_state.snapshot
        if ordinal >= len(snapshot.original_ops):
            self._disable_all_buttons()
            return
        s_idx, t_idx, _ = snapshot.original_ops[ordinal]
        ls, lt = len(s_idx), len(t_idx)

        # 同一份选择投影同时驱动工具栏、菜单和服务层校验。
        from dualign.services.repair import RepairService

        selected = self._selected_ordinals() or [ordinal]
        capabilities = RepairService.valid_selection_operations(
            w._repair_state, selected
        )

        predicted = self._predict_auto_action(ls, lt, getattr(w, "_strategy", "src"))

        for key, btn in self._btn_refs.items():
            if key in capabilities:
                enabled = capabilities[key]
            elif key == "suggest":
                enabled = predicted is not None  # 有自动修复建议时可用
            else:
                enabled = False

            btn.setEnabled(enabled)
        self._sync_menu_actions()

    def go(self, idx: int, scroll_to: bool = True):
        if 0 <= idx < len(self._anomalies):
            self._current_idx = idx
            self._update_display()
            if scroll_to and self._anomalies:
                anomaly = self._anomalies[idx]
                if anomaly.ordinals:
                    self.go_to_row.emit(anomaly.ordinals[0])

    # ═══════════════════════════════════════════════════════════
    # 内部辅助
    # ═══════════════════════════════════════════════════════════

    def _cur_anomaly(self) -> Optional[RelationAnomaly]:
        if 0 <= self._current_idx < len(self._anomalies):
            return self._anomalies[self._current_idx]
        return None

    def _current_ordinals(self) -> List[int]:
        a = self._cur_anomaly()
        if a is None:
            return []
        return list(a.ordinals)

    def _current_ordinal(self) -> Optional[int]:
        ordinals = self._current_ordinals()
        if ordinals:
            return ordinals[0]
        # 异常列表无对应行时回退到表格选中
        w = self._window
        if w is not None:
            sel = sorted(w.selected_ordinals)
            return sel[0] if sel else None
        return None

    def _selected_ordinals(self) -> List[int]:
        """读取窗口统一选择管理器中的关系序号。"""
        w = self._window
        if w is None:
            return []
        return sorted(w.selected_ordinals)

    # ── StatusBar 更新助手 ──

    def _update_status_bar(self):
        """将当前状态推送到 StatusBar。

        文件名和章节进度已移至文档摘要，此处仅更新关系定位区。
        """
        w = self._window
        if w is None or w._status_bar is None:
            return
        sb = w._status_bar

        # 当前关系 + 异常位置
        a = self._cur_anomaly()
        if a:
            sb.set_pos(f"{self._current_idx+1}/{len(self._anomalies)}")
        else:
            sb.set_pos("—")

    def _update_display(self):
        a = self._cur_anomaly()
        if a is None:
            self._relation_indicator.set_enabled(False, False)
            self._disable_all_buttons()
            self._update_status_bar()
            return

        total = len(self._anomalies)

        # ── RelationIndicator: 仅控制按钮启用 ──
        self._relation_indicator.set_enabled(
            self._current_idx > 0, self._current_idx < total - 1
        )

        # ── StatusBar → 推送到统一状态栏 ──
        self._update_status_bar()

        self._rebuild_ai_suggestions()
        self._update_button_states()

    # ═══════════════════════════════════════════════════════════
    # _compute_star — 委托给 base_table.relation_text_changes
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _compute_star(action, snapshot) -> tuple[bool, bool]:
        """计算该 action 的 src/tgt 侧是否应当标星。

        委托给 base_table 的 relation_text_changes，统一逻辑。
        """
        if action is None or snapshot is None:
            return False, False
        from dualign.gui.base_table import relation_text_changes

        ordinal = snapshot.operation_index(action.relation_ids[0])
        return relation_text_changes(ordinal, action, snapshot)

    def _rebuild_ai_suggestions(self):
        """重建 AI 建议表格。每条建议通过 replay 引擎计算执行后预览文本。"""
        w = self._window
        if w is None:
            return

        actions_to_show: list[tuple[RepairAction, str]] = []

        # 全部从 ai_proposal_store 读取
        store = w._repair_state.ai_proposal_store if w._repair_state else None
        if store:
            for props in store.proposals.values():
                for p in props:
                    # accepted 的 auto-applied 建议显示为"已应用"
                    display_status = p.status
                    if display_status == "accepted":
                        display_status = "已应用"
                    actions_to_show.append((p.action, display_status))

        # 「显示已处理」筛选：未勾选时只显示 pending
        only_pending = (
            not self._window._inc_handled_cb.isChecked()
            if self._window and hasattr(self._window, "_inc_handled_cb")
            else False
        )
        if only_pending:
            actions_to_show = [(a, s) for a, s in actions_to_show if s == "pending"]

        # 预计算每条建议执行后的预览文本（通过 replay 引擎）
        snapshot = w._repair_state.snapshot if w._repair_state else None
        cur_repair_state = w._repair_state  # 保留当前状态（含已有操作标记）
        items = []
        for action, status in actions_to_show:
            ordinal = snapshot.operation_index(action.relation_ids[0])
            rows_data = self._compute_action_preview(action, snapshot, cur_repair_state)
            # 获取初始文本（action 前）— 从 snapshot 原始文本获取
            ini_src, ini_tgt = "", ""
            if snapshot and 0 <= ordinal < len(snapshot.original_ops):
                s_idx, t_idx, _ = snapshot.original_ops[ordinal]
                ini_src_lines = [snapshot.src_text(i) for i in s_idx]
                ini_tgt_lines = [snapshot.tgt_text(j) for j in t_idx]
                ini_src = (
                    "\n".join(ini_src_lines)
                    if len(ini_src_lines) > 1
                    else (ini_src_lines[0] if ini_src_lines else "")
                )
                ini_tgt = (
                    "\n".join(ini_tgt_lines)
                    if len(ini_tgt_lines) > 1
                    else (ini_tgt_lines[0] if ini_tgt_lines else "")
                )
            if rows_data is None:
                # 回退：从 action.data 读取原文/译文
                data = action.data or {}
                src_lines = data.get("new_src_lines", data.get("new_src", [])) or [""]
                tgt_lines = data.get("new_tgt_lines", data.get("new_tgt", [])) or [""]
                rows_data = []
                n = max(len(src_lines), len(tgt_lines))
                for i in range(n):
                    src = src_lines[i] if i < len(src_lines) else ""
                    tgt = tgt_lines[i] if i < len(tgt_lines) else ""
                    rows_data.append((src, tgt, "", "", 0.0, 0.0, 1, 1))
            # 每子行创建独立的 AiSuggestionItem，携带准确的 score/n_src/n_tgt
            sub_items = []
            for i, (
                src,
                tgt,
                init_type,
                cur_type,
                init_score,
                score,
                n_src,
                n_tgt,
            ) in enumerate(rows_data):
                sub_items.append(
                    AiSuggestionItem(
                        ordinal,
                        action,
                        status,
                        sub=i,
                        src_line=src,
                        tgt_line=tgt,
                        init_type=init_type,
                        cur_type=cur_type,
                        init_score=init_score,
                        score=score,
                        n_src=n_src,
                        n_tgt=n_tgt,
                        init_src_text=ini_src,
                        init_tgt_text=ini_tgt,
                    )
                )
            # ── 计算星标：与主表 relation_text_changes 统一逻辑 ──
            star_src, star_tgt = self._compute_star(action, snapshot)
            for si in sub_items:
                si.star_src = star_src
                si.star_tgt = star_tgt
            items.extend(sub_items)

        # 按当前关系序号升序排列，方便用户按顺序审阅
        items.sort(key=lambda x: x.ordinal)

        # 推送数据到预览表
        if hasattr(self, "_preview_table"):
            self._preview_table.set_items(items)

        # 空状态提示
        if not items and hasattr(self, "_ai_empty_lbl"):
            only_pending = (
                not self._window._inc_handled_cb.isChecked()
                if self._window and hasattr(self._window, "_inc_handled_cb")
                else False
            )
            if only_pending:
                self._ai_empty_lbl.setText(
                    "💡 所有 AI 建议已处理\n勾选「显示已处理」可查看历史建议"
                )
            else:
                self._ai_empty_lbl.setText(
                    "📭 暂无 AI 建议\n启动 AI 校订后建议将显示在此处"
                )
            self._ai_empty_lbl.setVisible(True)
            self._preview_table.table.setVisible(False)
        elif hasattr(self, "_ai_empty_lbl"):
            self._ai_empty_lbl.setVisible(False)
            self._preview_table.table.setVisible(True)

        # ── 更新标题栏③区建议统计（基于 action 数而非子行数）──
        if self._window and hasattr(self._window, "_ai_suggest_count"):
            n_pending = len(self._pending_action_list)
            n_total_actions = len(actions_to_show)
            if n_total_actions > 0:
                self._window._ai_suggest_count.setText(
                    f"\U0001f4a1 {n_pending}/{n_total_actions}"
                )
                self._window._ai_suggest_count.setToolTip(
                    f"{n_pending} 条待审建议 / 共 {n_total_actions} 条"
                )
            else:
                self._window._ai_suggest_count.setText("")
                self._window._ai_suggest_count.setToolTip("")

        # 延迟同步列宽（等主表渲染完成后再对齐）
        if (
            self._window
            and hasattr(self._window, "table")
            and hasattr(self._window, "_filter_panel")
        ):
            from PySide6.QtCore import QTimer as _QT

            _QT.singleShot(50, lambda: self._sync_suggestion_widths())

        self._suggestions = items

        # 重建后恢复高亮：从 FocusManager.focused_ordinal 恢复，
        # 而非 self._focused_action（后者可能来自旧建议而非当前点击的关系）。
        w = self._window
        if w and hasattr(w, "_focus") and w._focus.focused_ordinal is not None:
            self.focus_relation_ai(w._focus.focused_ordinal)

    def _sync_suggestion_widths(self):
        """同步预览表和 AI 建议表的列宽与主对齐表一致。"""
        w = self._window
        if w is None or not hasattr(w, "table") or not hasattr(w, "_filter_panel"):
            return
        fp = w._filter_panel
        if hasattr(self, "_preview_table"):
            self._preview_table.sync_from_main_table(w.table, fp)

    @staticmethod
    def _compute_action_preview(
        action: RepairAction,
        snapshot,
        repair_state=None,
    ) -> list[tuple[str, str, str, str, float, float, int, int]] | None:
        """通过 replay 引擎计算单条建议执行后的预览数据。

        返回: [(src, tgt, init_type, cur_type, init_score, score, n_src, n_tgt), ...]
        每子行一条。从当前 repair_state 开始（保留已有操作标记），再叠加预览 action。
        repair_state 为 None 时仅从原始快照计算。
        """
        if snapshot is None:
            return None

        from dualign.services.repair import RepairState, make_table_view

        base = repair_state if repair_state else RepairState(snapshot)
        temp_state = base.apply(action)
        view = make_table_view(temp_state)
        ordinal = base.action_ordinal(action)
        relation_rows = [r for r in view.rows if r.ordinal == ordinal]
        if not relation_rows:
            return None
        return [
            (
                r.src_text,
                r.tgt_text,
                r.init_type,
                r.cur_type,
                r.orig_score,
                r.score,
                r.n_src,
                r.n_tgt,
            )
            for r in relation_rows
        ]

    @staticmethod
    def _predict_auto_action(ls: int, lt: int, strategy: str) -> Optional[str]:
        """预测自动修复会执行的操作 key。匹配 _btn_refs 的 key。"""
        from dualign.services.repair_policy import choose_auto_repair

        # This is the deterministic auto-repair preview, not the AI review
        # policy.  In particular ``minimal`` intentionally differs between the
        # two paths and must remain a deletion for 1:0 / 0:1 relations here.
        plan = choose_auto_repair(ls, lt, strategy)
        if plan is None:
            return None
        if plan.kind.startswith("placeholder_"):
            return "placeholder"
        return plan.kind

    def _update_button_states(self):
        """动态启用/禁用按钮。文字色由创建时一次性设定，不被覆盖。"""
        w = self._window
        if w is None or w._repair_state is None:
            self._disable_all_buttons()
            return
        ordinal = self._current_ordinal()
        if ordinal is None:
            self._disable_all_buttons()
            return

        from dualign.services.repair import RepairService

        ops = RepairService.valid_operations(w._repair_state, ordinal)

        for key, btn in self._btn_refs.items():
            if key == "split":
                enabled = ops.get("split_tgt", False) or ops.get("split_src", False)
            elif key == "suggest":
                enabled = True
            elif key == "merge":
                sel = self._selected_ordinals()
                enabled = ops.get(key, False) or len(sel) > 1
            else:
                enabled = ops.get(key, False)
            btn.setEnabled(enabled)
        self._sync_menu_actions()

    def _disable_all_buttons(self):
        for btn in self._btn_refs.values():
            btn.setEnabled(False)
        self._sync_menu_actions()

    def _all_handled(self) -> bool:
        """所有异常都已被处理（approval 不再是 unreviewed）。"""
        return bool(self._anomalies) and all(
            anomaly.approval != "unreviewed" for anomaly in self._anomalies
        )

    # ── 导航 ──

    def _go_prev(self):
        if self._current_idx > 0:
            self.go(self._current_idx - 1)
        elif self._anomalies:
            self.go(len(self._anomalies) - 1)

    def _go_next(self):
        if self._current_idx < len(self._anomalies) - 1:
            self.go(self._current_idx + 1)
        elif self._anomalies:
            # 处理完末项时，仅在用户显式开启后切换章节。
            if self._all_handled() and self.auto_next_chapter():
                self.next_chapter_requested.emit()
            else:
                self.go(0)

    # ── 操作委托（含修复后自动跳转）──

    def _do_and_advance(self, action_fn):
        """执行操作，若勾选了修复后跳转则移至下一处。"""
        old_ordinal = self._current_ordinal()
        action_fn()
        # 操作可能刷新了 _anomalies，检查当前关系是否还在
        if (
            self._window
            and self._window._status_bar.is_auto_advance()
            and self._anomalies
        ):
            cur = self._current_ordinal()
            if cur is not None and cur == old_ordinal:
                # 未自动跳转，手动推进
                QTimer.singleShot(0, self._go_next)

    def _current_or_selected_ordinal(self) -> Optional[int]:
        """取当前异常关系，无对应时回退到表格选中项。"""
        ordinal = self._current_ordinal()
        if ordinal is not None:
            return ordinal
        sel = self._selected_ordinals()
        return sel[0] if sel else None

    def _on_merge(self):
        sel = self._selected_ordinals()
        if len(sel) > 1:
            if self._window:
                self._do_and_advance(lambda: self._window.do_bundle_relations(sel))
            return
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_merge(ordinal))

    def _on_split(self):
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_split(ordinal))

    def _on_edit(self):
        sel = self._selected_ordinals()
        if len(sel) > 1:
            self._window.do_edit_selected(sel)
            return
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_edit_single(ordinal))

    def _on_ok(self):
        sel = self._selected_ordinals()
        if len(sel) > 1 and self._window:
            self._do_and_advance(lambda: [self._window.do_ok(si) for si in sel])
            return
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_ok(ordinal))

    def _on_flag(self):
        sel = self._selected_ordinals()
        if len(sel) > 1 and self._window:
            self._do_and_advance(lambda: self._window.do_flag_selected(sel))
            return
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_flag(ordinal))

    def _on_delete(self):
        sel = self._selected_ordinals()
        if len(sel) > 1 and self._window:
            self._window._delete_selected_relations(sel)
            return
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_delete(ordinal))

    def _on_placeholder(self):
        sel = self._selected_ordinals()
        if len(sel) > 1 and self._window:
            self._do_and_advance(
                lambda: [self._window.do_placeholder(si) for si in sel]
            )
            return
        ordinal = self._current_or_selected_ordinal()
        if ordinal is not None and self._window:
            self._do_and_advance(lambda: self._window.do_placeholder(ordinal))

    def _on_reset_current(self):
        sel = self._selected_ordinals()
        if not sel:
            si = self._current_or_selected_ordinal()
            sel = [si] if si is not None else []
        if not sel or not self._window:
            return
        # 找出所有涉及选中关系的 actions（包括跨关系合并/编辑）
        state = self._window._repair_state
        target_ops = set()
        for a in state.repair_log:
            involved = set(state.action_ordinals(a))
            if involved & set(sel):
                target_ops.add(state.action_ordinal(a))
        for op_idx in sorted(target_ops):
            self._window.do_reset(op_idx)

    def _on_ai_analyze(self):
        """AI 分析当前选中的文本对（支持多选）。"""
        ordinals = self._selected_ordinals()
        if not ordinals:
            ordinal = self._current_ordinal()
            if ordinal is not None:
                ordinals = [ordinal]
        if ordinals:
            self.analyze_relations(ordinals)

    def _emit_log(self, message: str, role: str = "info"):
        """通过信号将日志消息路由到全局 LogPanel。"""
        self.log_message.emit(message, role)

    def _on_reset_all(self):
        if self._window:
            self._window._on_reset_all()

    # ═══════════════════════════════════════════════════════════
    # AI 建议焦点跟踪
    # ═══════════════════════════════════════════════════════════

    def _set_focused_action(self, action: Optional[RepairAction]):
        """设置当前聚焦的 AI 建议，更新按钮状态 + 通知 FocusManager。

        不触发表格刷新——由调用方按需触发。
        应用/拒绝/撤销 三按钮合用同一 HBox 容器，
        撤销总是在已用按钮的位置出现（替换未用按钮的空间）。
        """
        self._focused_action = action

        # 同步到 FocusManager（供跨筛选关系显示等使用）
        w = self._window
        if w and hasattr(w, "_focus"):
            ordinals = (
                w._repair_state.action_ordinals(action)
                if action and w._repair_state
                else ()
            )
            w._focus.focus_action(action, ordinals)

        has_focus = action is not None
        # ── 应用按钮样式（绿色边框）──
        self._ai_accept_btn.setStyleSheet(
            f"QPushButton{{color:{T.GREEN};"
            f"border:1px solid {T.GREEN};border-radius:3px;padding:2px 8px;}}"
            f"QPushButton:disabled{{color:{T.FG_MUTED};"
            f"border-color:{T.BORDER_DIM};}}"
        )
        # ── 拒绝按钮样式（红色边框）──
        self._ai_reject_btn.setStyleSheet(
            f"QPushButton{{color:{T.RED};"
            f"border:1px solid {T.RED};border-radius:3px;padding:2px 8px;}}"
            f"QPushButton:disabled{{color:{T.FG_MUTED};"
            f"border-color:{T.BORDER_DIM};}}"
        )
        # ── 撤销按钮样式（橙色边框，与应用/拒绝风格一致）──
        self._ai_restore_btn.setStyleSheet(
            f"QPushButton{{color:{T.ORANGE};"
            f"border:1px solid {T.ORANGE};border-radius:3px;padding:2px 8px;}}"
            f"QPushButton:disabled{{color:{T.FG_MUTED};"
            f"border-color:{T.BORDER_DIM};}}"
        )

        if has_focus:
            # 查询状态，决定按钮状态
            status = "pending"
            if self._window and self._window._repair_state:
                store = self._window._repair_state.ai_proposal_store
                if store:
                    s = store.get_status(action)
                    if s:
                        status = s

            if status == "accepted":
                # 应用已灰显；拒绝隐藏 → 撤销填入拒绝位置
                self._ai_accept_btn.setText("✅ 已应用")
                self._ai_accept_btn.setEnabled(False)
                self._ai_reject_btn.setVisible(False)
                self._ai_restore_btn.setVisible(True)
                self._ai_restore_btn.setEnabled(True)
            elif status == "rejected":
                # 拒绝已灰显；应用隐藏 → 撤销填入应用位置
                self._ai_reject_btn.setText("❌ 已拒绝")
                self._ai_reject_btn.setEnabled(False)
                self._ai_accept_btn.setVisible(False)
                self._ai_restore_btn.setVisible(True)
                self._ai_restore_btn.setEnabled(True)
            else:
                # pending: 应用 + 拒绝都可见，撤销隐藏
                self._ai_accept_btn.setText("✅ 应用")
                self._ai_accept_btn.setEnabled(True)
                self._ai_accept_btn.setVisible(True)
                self._ai_reject_btn.setText("❌ 拒绝")
                self._ai_reject_btn.setEnabled(True)
                self._ai_reject_btn.setVisible(True)
                self._ai_restore_btn.setVisible(False)
        else:
            # 无焦点：禁用全部
            self._ai_accept_btn.setText("✅ 应用")
            self._ai_accept_btn.setEnabled(False)
            self._ai_accept_btn.setVisible(True)
            self._ai_reject_btn.setText("❌ 拒绝")
            self._ai_reject_btn.setEnabled(False)
            self._ai_reject_btn.setVisible(True)
            self._ai_restore_btn.setVisible(False)

    def focus_relation_ai(self, ordinal: int):
        """表格聚焦某个关系 → AI 建议预览表高亮对应行。

        由 _on_go_to_row 调用。预览表中找到即设焦点，
        找不到则清除焦点 + 禁用应用/拒绝按钮。
        """
        preview_found = False
        if hasattr(self, "_preview_table"):
            preview_found = self._preview_table.focus_ordinal(ordinal)

        if preview_found:
            for item in self._suggestions:
                if item.ordinal == ordinal:
                    self._set_focused_action(item.action)
                    return
        # 当前关系无 AI 建议 → 清除焦点，应用/拒绝按钮变灰
        self._set_focused_action(None)

    # ── AI 建议操作（由侧边栏按钮触发）──

    def _on_ai_accept_focused(self):
        """应用当前聚焦的建议，并自动打上 [OK] 标签。

        统一方案：ToolExecutor 源头已将 ok 解析为正确 kind，
        不再区分是否存在拟修复，全部走 _apply_ai_action 流程。
        """
        action = self._focused_action
        if action is None:
            return

        self.action_requested.emit(action)

        w = self._window
        if w and w._repair_state:
            w._repair_state.ai_proposal_store.accept(action)
            from dualign.models.action import RepairAction

            # 追加 [OK] 确认标记
            ordinal = w._repair_state.action_ordinal(action)
            ok_action = w._repair_state.make_action("ok", ordinal)
            w._undo_stack.append(w._repair_state)
            w._repair_state = w._repair_state.apply(ok_action)
            w._refresh()
            w._save_session()
        self.actions_updated.emit()
        self._rebuild_ai_suggestions()
        self._set_focused_action(action)
        if self._window and self._window._status_bar.is_auto_advance():
            self._on_next_suggestion()

    def _on_ai_reject_focused(self):
        """拒绝当前聚焦的建议。"""
        action = self._focused_action
        if action is None:
            return
        w = self._window
        if w and w._repair_state:
            w._repair_state.ai_proposal_store.reject(action)
            relation_id = action.relation_ids[0]
            existing = w._repair_state.action_for_relation(relation_id)
            if existing and existing.kind == action.kind:
                new_state = w._repair_state.reset_relation(relation_id)
                w._repair_state = new_state
                w._refresh()
                w._save_session()
        self.actions_updated.emit()
        self._rebuild_ai_suggestions()
        # 拒绝后显示恢复按钮
        self._set_focused_action(action)
        if self._window and self._window._status_bar.is_auto_advance():
            self._on_next_suggestion()

    def _on_ai_restore_focused(self):
        """恢复当前聚焦的建议（撤销拒绝/已应用状态）。

        对已应用的建议：撤销修复状态中的 ok + AI 操作，
        并将 AiProposalStore 回退为 pending。
        """
        action = self._focused_action
        if action is None:
            return
        w = self._window
        if w and w._repair_state:
            store = w._repair_state.ai_proposal_store
            status = store.get_status(action) if store else None
            # 仅当建议已被接受时才回退修复状态
            if status == "accepted":
                # 从 repair_log 中移除该 AI 操作及其附属的 ok
                log = w._repair_state.repair_log
                new_log = []
                skip_ok = False
                for a in log:
                    if a.relation_ids == action.relation_ids and a.kind == action.kind:
                        skip_ok = True
                        continue
                    if (
                        skip_ok
                        and a.relation_ids == action.relation_ids
                        and a.kind == "ok"
                    ):
                        skip_ok = False
                        continue
                    new_log.append(a)
                from dualign.services.repair import RepairState

                w._repair_state = RepairState(
                    w._repair_state.snapshot,
                    new_log,
                    w._repair_state.ai_proposal_store,
                )
            store.restore(action)
            w._refresh()
            w._save_session()
        self._rebuild_ai_suggestions()
        # 恢复后重新聚焦使按钮恢复到 accept/reject 状态
        self._set_focused_action(action)

    # ═══════════════════════════════════════════════════════════
    # AI 校订 — Agent 模式
    # ═══════════════════════════════════════════════════════════

    def analyze_relations(self, ordinals: List[int]):
        """使用 AiRepairAgent 分析用户显式选中的文本对。

        拟修复在 AgentRunThread 的异步线程内自动构造。
        此处 skip_auto_repair=True 避免主线程阻塞。
        显式选择是权威待审集合，不受异常检测或当前筛选条件限制。
        """
        ctx = self._build_chapter_context(
            for_ordinals=ordinals,
            skip_auto_repair=True,
        )
        if ctx is None:
            return
        self._reviewed_count = 0
        n_meta = len(ctx.reviewable_infos)
        max_turns = min(12, n_meta * 2 + 2)
        self._start_agent(ctx, max_turns=max_turns)

    def analyze_chapter_batch(self):
        """使用 AiRepairAgent 校订全章异常。

        拟修复在 AgentRunThread 的异步线程内自动构造。
        此处 skip_auto_repair=True 避免主线程阻塞。
        """
        ctx = self._build_chapter_context(skip_auto_repair=True)
        if ctx is None:
            self.ai_error.emit("skipped")
            return

        self._batch_mode = True
        self._reviewed_count = 0
        w = self._window
        if w and w._repair_state:
            w._repair_state = w._repair_state.set_ai_proposal_store(AiProposalStore())

        n_meta = len(ctx.reviewable_infos)
        self._emit_log(f"开始审校 {n_meta} 异常对", "system")
        max_turns = min(12, n_meta * 2 + 2)
        self._start_agent(ctx, max_turns=max_turns)

    def clear_all_suggestions(self):
        w = self._window
        if w and w._repair_state:
            w._repair_state = w._repair_state.set_ai_proposal_store(AiProposalStore())
        self._rebuild_ai_suggestions()
        self.actions_updated.emit()
        if w:
            w._save_session()

    def _apply_all_pending(self):
        """一键应用所有待处理的 AI 建议。

        用户手动点击「应用全部」时的行为：
          - 保留 AI 操作痕迹（[AI][M] 等 marker）
          - 叠加 [OK] 标记表示用户审核通过 → [AI][M] [OK]
          - 区别：自动应用模式不叠加 [OK]，保持纯 [AI][M]
        """
        w = self._window
        if w is None:
            return
        actions = list(self._pending_action_list)
        if not actions:
            return
        from dualign.models.action import RepairAction

        for a in actions:
            # 先通过标准入口 apply（生成 [AI][M] 等 marker）
            self.action_requested.emit(a)
            if w._repair_state:
                a = w._repair_state.validate_action(a)
                w._repair_state.ai_proposal_store.add(a)
                w._repair_state.ai_proposal_store.accept(a)
                # 叠加 [OK] 标记用户审核通过
                ok_action = RepairAction.make_ok(a.relation_ids[0])
                w._repair_state = w._repair_state.apply(ok_action)
        if w._repair_state:
            w._refresh()
        self._rebuild_ai_suggestions()
        self.actions_updated.emit()

    def _build_chapter_context(
        self, for_ordinals: List[int] | None = None, skip_auto_repair: bool = False
    ):
        """从当前 RepairState 构造 ChapterContext。

        未指定 ``for_ordinals`` 时，使用 GUI 的异常列表构建全章待审集合；
        指定后则以用户显式选择为准，正常文本对也必须传入 AI。

        Args:
            skip_auto_repair: 为 True 时跳过内部 auto_repair（调用方已构造拟修复）。
        """
        w = self._window
        if w is None or w._repair_state is None:
            return None

        # 获取用户偏好的修复策略
        strategy = getattr(w, "_strategy", "src")

        explicitly_selected = for_ordinals is not None
        if explicitly_selected:
            target_ordinals = set(for_ordinals)
        else:
            target_ordinals = set()
            for anomaly in self._anomalies:
                target_ordinals.update(anomaly.ordinals)

        if not target_ordinals:
            return None

        ctx = build_chapter_context(
            w._repair_state,
            strategy=strategy,
            model=getattr(w, "_model", None),
            skip_auto_repair=skip_auto_repair,
            reviewable_ids=target_ordinals if explicitly_selected else None,
        )

        # 保留完整 relation_infos（供初始消息的 ±3 上下文按序号查找），
        # 全章审校只裁剪天然异常；显式选择已由构造器直接设为待审集合。
        # initial_* 已在 from_repair_state 中统一填充。
        if not explicitly_selected:
            ctx.reviewable_ids = [
                ordinal for ordinal in ctx.reviewable_ids if ordinal in target_ordinals
            ]

        if not ctx.reviewable_ids:
            return None
        return ctx

    def _start_agent(self, ctx: ChapterContext, max_turns: int = 20):
        """启动 AgentRunThread 并连接信号。"""
        self._disable_ai_buttons(True)

        w = self._window
        # 传递嵌入模型引用 + 策略偏好
        model = getattr(w, "_model", None) if w else None
        strategy = getattr(w, "_strategy", "src") if w else "src"
        # 从 provider 配置读取模型名和 base_url
        model_name = "deepseek-v4-flash"
        base_url = "https://api.deepseek.com"
        api_key = ""
        try:
            from dualign.providers import active_repair_agent

            cfg = active_repair_agent()
            if cfg:
                model_name = cfg.model_name or model_name
                base_url = cfg.base_url or base_url
                api_key = cfg.key_plain or api_key
        except Exception:
            pass

        # 确保 model 可供线程内构造拟修复时使用
        if model is None:
            try:
                from dualign.services.embedding import _try_lazy_load_model

                model = _try_lazy_load_model()
            except Exception:
                pass

        thread = AgentRunThread(
            ctx,
            backend=self._backend,
            max_turns=max_turns,
            model=model,
            strategy=strategy,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            repair_state=w._repair_state if w else None,
        )
        thread.event_occurred.connect(self._on_agent_event)
        thread.finished_actions.connect(self._on_agent_finished)
        thread.error_occurred.connect(self._on_agent_error)
        self._active_threads = [t for t in self._active_threads if t.isRunning()]
        self._active_threads.append(thread)
        thread.start()

    def _on_agent_event(self, evt: AgentEvent):
        """接收 Agent 事件 → 更新进度计数 + 日志面板。

        简化原则：
          - turn/tool 详情 → logging.debug（默认不显示，调试时切 DEBUG 级别可见）
          - review_done 审核结果 → LogPanel INFO
        """
        import logging

        ai_logger = logging.getLogger("dualign.ai")

        if evt.type == "error":
            self._on_agent_error(evt.error or "未知错误")
        elif evt.type == "llm_call":
            ai_logger.debug(f"Turn {evt.turn}: LLM 调用中")
        elif evt.type == "tool_start":
            # 工具调用详情 → DEBUG，避免刷屏
            args_str = str(evt.tool_args) if evt.tool_args else ""
            ai_logger.debug(f"Turn {evt.turn}: {evt.tool_name}({args_str})")
        elif evt.type == "review_done" and evt.review_action:
            # ── 逐量更新：Agent 每完成一处 review 就立即添加到界面 ──
            ra = evt.review_action
            self._reviewed_count = getattr(self, "_reviewed_count", 0) + 1
            if self._window and self._window._repair_state:
                ra = self._window._repair_state.validate_action(ra)
                store = self._window._repair_state.ai_proposal_store
                # 去重：若同一关系同 kind 已有 pending/accepted 建议则跳过
                existing = store.get(ra.relation_ids[0])
                already = any(
                    p.action.kind == ra.kind and p.status in ("pending", "accepted")
                    for p in existing
                )
                if not already:
                    store.add(ra)
                    self._rebuild_ai_suggestions()
            self.actions_updated.emit()

    # ═══════════════════════════════════════════════════════════
    # 建议导航 — 直接遍历当前 AI 建议表，不受异常筛选约束
    # ═══════════════════════════════════════════════════════════

    def _on_prev_suggestion(self):
        """定位上一条当前可见的 AI 建议。"""
        self._navigate_suggestion(-1)

    def _on_next_suggestion(self):
        """定位下一条当前可见的 AI 建议。"""
        self._navigate_suggestion(1)

    def _navigate_suggestion(self, step: int):
        current = (
            self._window._repair_state.action_ordinal(self._focused_action)
            if self._focused_action and self._window and self._window._repair_state
            else None
        )
        ordinal = _next_suggestion_ordinal(self._suggestions, current, step)
        if ordinal is None:
            return
        item = next(it for it in self._suggestions if it.ordinal == ordinal)
        self._focus_suggestion(item.action, ordinal)

    def _on_agent_finished(self, actions: List[RepairAction]):
        """Agent 完成 → 处理 actions。

        拟修复在 AgentRunThread 中已构造，w._repair_state 已包含 auto-repair 操作。
        对存在拟修复的关系，AI 的 "ok" 应转换为等效操作（如 split/merge）显示在建议表中。
        """
        self._disable_ai_buttons(False)

        if not actions:
            self._rebuild_ai_suggestions()
            if self._batch_mode:
                self._batch_mode = False
                self.batch_finished.emit()
            return

        w = self._window
        _auto_all = self._auto_approve_enabled

        safe_actions = []
        review_actions = []
        for a in actions:
            if _auto_all:
                safe_actions.append(a)
            else:
                review_actions.append(a)

        # 全部存入 ai_proposal_store（统一 action 管理入口）
        store = w._repair_state.ai_proposal_store if w and w._repair_state else None

        if safe_actions:
            for a in safe_actions:
                a = w._repair_state.validate_action(a)
                if store:
                    store.add(a)
                    store.accept(a)
                self.action_requested.emit(a)

        if review_actions:
            for a in review_actions:
                if store:
                    store.add(w._repair_state.validate_action(a))

        self._rebuild_ai_suggestions()
        self.actions_updated.emit()

        if w:
            w._save_session()

        if self._active_threads:
            thread = self._active_threads[-1]
            if hasattr(thread, "turn_log") and thread.turn_log:
                from dualign.services.ai_repair_agent import (
                    dump_agent_debug,
                    dump_agent_raw,
                )
                from dualign.config import get_cache_root

                entry_id = (
                    getattr(w, "_current_entry_id", "unknown") if w else "unknown"
                )
                log_dir = os.path.join(get_cache_root(), "logs", entry_id)
                os.makedirs(log_dir, exist_ok=True)
                dump_agent_debug(
                    thread.agent_ctx,
                    actions,
                    thread.turn_log,
                    os.path.join(log_dir, "agent.debug.md"),
                    prompt_tokens=thread.token_stats.get("prompt", 0),
                    cache_tokens=thread.token_stats.get("cache", 0),
                    completion_tokens=thread.token_stats.get("completion", 0),
                    elapsed=thread.elapsed,
                )
                dump_agent_raw(
                    thread.agent_ctx,
                    actions,
                    thread.turn_log,
                    os.path.join(log_dir, "agent.raw.json"),
                    prompt_tokens=thread.token_stats.get("prompt", 0),
                    cache_tokens=thread.token_stats.get("cache", 0),
                    completion_tokens=thread.token_stats.get("completion", 0),
                    elapsed=thread.elapsed,
                )

        if self._batch_mode:
            self._batch_mode = False
            self.batch_finished.emit()

    def _on_agent_error(self, error: str):
        self._disable_ai_buttons(False)
        self.ai_error.emit(error)

    def _disable_ai_buttons(self, loading: bool):
        for attr in (
            "_ai_clear_btn",
            "_prev_suggestion_btn",
            "_next_suggestion_btn",
            "_apply_all_btn",
        ):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(not loading)
