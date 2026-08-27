"""Dualign editing, configuration, and solidification dialogs."""

from __future__ import annotations

from typing import List, Optional
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QRect, QSize, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextOption
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QDialogButtonBox,
    QGroupBox,
    QWidget,
    QDoubleSpinBox,
    QListWidget,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSplitter,
)

_DEFAULT_EMBEDDING_INSTRUCTION = (
    "Instruct: Identify parallel sentences across languages\nQuery: "
)

# ═══════════════════════════════════════════════════════════════
# AgentConfigDialog — 嵌入模型 + AI 修复 Agent 配置
# ═══════════════════════════════════════════════════════════════


class AgentConfigDialog(QDialog):
    """Agent 配置对话框 — 分 Tab 管理嵌入模型和 AI 修复 Agent。"""

    config_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模型与 Agent 配置")
        self.setMinimumWidth(520)
        self.setMinimumHeight(360)
        self._detected_models: list[str] = []
        self._build_ui()

    def _build_ui(self):
        from PySide6.QtWidgets import QTabWidget

        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # ── Tab 1: 嵌入模型 ──
        embed_tab = self._build_embedding_tab()
        tabs.addTab(embed_tab, "🔤 嵌入模型")

        # ── Tab 2: AI 修复 Agent ──
        ai_tab = self._build_ai_repair_tab()
        tabs.addTab(ai_tab, "🤖 AI 修复 Agent")

        layout.addWidget(tabs)

        # 底部按钮
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _build_embedding_tab(self) -> QWidget:
        """嵌入模型配置（复用 ProviderManager）。"""
        from dualign.providers import ProviderManager

        ProviderManager.load()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 提供方列表
        lay.addWidget(QLabel("<b>嵌入模型提供方</b>（用于对齐编码）"))
        self._embed_list = QListWidget()
        self._embed_list.setMaximumHeight(100)
        lay.addWidget(self._embed_list)

        # 详情编辑
        form = QFormLayout()
        self._embed_label_edit = QLineEdit()
        self._embed_label_edit.setPlaceholderText("显示名")
        form.addRow("名称:", self._embed_label_edit)

        self._embed_url_edit = QLineEdit()
        self._embed_url_edit.setPlaceholderText("http://localhost:11434")
        form.addRow("API 地址:", self._embed_url_edit)

        # 模型名：输入框 + 从检测结果选取的按钮
        model_row = QHBoxLayout()
        self._embed_model_edit = QLineEdit()
        self._embed_model_edit.setPlaceholderText("leoipulsar/harrier-0.6b")
        model_row.addWidget(self._embed_model_edit, 1)
        self._embed_model_picker = QPushButton("↕")
        self._embed_model_picker.setFixedSize(28, 28)
        self._embed_model_picker.setToolTip("从已检测的模型列表中选取")
        self._embed_model_picker.setEnabled(False)
        self._embed_model_picker.clicked.connect(self._on_pick_model)
        model_row.addWidget(self._embed_model_picker)
        form.addRow("模型名:", model_row)

        self._embed_key_edit = QLineEdit()
        self._embed_key_edit.setPlaceholderText("（可选）API Key")
        self._embed_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self._embed_key_edit)

        # ── Instruction 配置：启用开关 + 自定义文本 + 恢复默认 ──
        instr_header_row = QHBoxLayout()
        self._embed_instr_enabled_cb = QCheckBox("启用 Instruction 前缀")
        self._embed_instr_enabled_cb.setToolTip(
            "勾选后在编码时自动在每行文本前拼接 Instruction 前缀。\n"
            "仅 Qwen3-embedding 系列模型（含默认 harrier）原生支持，\n"
            "其他模型建议关闭或在验证后使用。"
        )
        self._embed_instr_enabled_cb.toggled.connect(self._on_instr_toggled)
        instr_header_row.addWidget(self._embed_instr_enabled_cb)
        instr_header_row.addStretch()
        form.addRow(instr_header_row)

        instr_text_row = QHBoxLayout()
        self._embed_instruction_edit = QLineEdit()
        self._embed_instruction_edit.setPlaceholderText(
            "Instruct: Identify parallel sentences across languages\\nQuery: "
        )
        instr_text_row.addWidget(self._embed_instruction_edit, 1)
        reset_instr_btn = QPushButton("恢复默认")
        reset_instr_btn.setFixedWidth(80)
        reset_instr_btn.setToolTip("重置为 Dualign 内置的默认 Instruction 文本")
        reset_instr_btn.clicked.connect(self._on_reset_instruction)
        instr_text_row.addWidget(reset_instr_btn)
        form.addRow("自定义文本:", instr_text_row)

        lay.addLayout(form)

        # 按钮行
        btn_row = QHBoxLayout()
        test_btn = QPushButton("⚡ 检测连接")
        test_btn.clicked.connect(self._on_test_embedding)
        btn_row.addWidget(test_btn)
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self._on_save_embedding)
        btn_row.addWidget(save_btn)
        default_btn = QPushButton("⭐ 设为默认")
        default_btn.setToolTip("将当前选中的提供方设为活跃提供方")
        default_btn.clicked.connect(self._on_set_active_embedding)
        btn_row.addWidget(default_btn)
        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self._on_reset_embedding)
        btn_row.addWidget(reset_btn)
        config_folder_btn = QPushButton("📁 打开配置文件夹")
        config_folder_btn.setToolTip(
            "在文件管理器中打开配置文件夹\n（可手动编辑 providers.json 以批量配置）"
        )
        config_folder_btn.clicked.connect(self._on_open_config_folder)
        btn_row.addWidget(config_folder_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._embed_status = QLabel("")
        self._embed_status.setWordWrap(True)
        lay.addWidget(self._embed_status)

        # 填充列表：先连接信号再选中首项，确保表单字段随初始选中填充
        self._embed_list.currentRowChanged.connect(self._on_embed_selected)
        self._refresh_embed_list()

        return w

    def _on_pick_model(self):
        """从检测到的模型列表中选择模型名。"""
        if not self._detected_models:
            return
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for m in self._detected_models:
            action = menu.addAction(m)
            action.triggered.connect(
                lambda checked, name=m: self._embed_model_edit.setText(name)
            )
        menu.exec(
            self._embed_model_picker.mapToGlobal(
                self._embed_model_picker.rect().bottomLeft()
            )
        )

    def _build_ai_repair_tab(self) -> QWidget:
        """AI 修复 Agent 配置。"""

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        lay.addWidget(QLabel("<b>AI 修复 Agent</b>（用于自动修复和对话）"))

        self._ai_list = QListWidget()
        self._ai_list.setMaximumHeight(80)
        lay.addWidget(self._ai_list)

        form = QFormLayout()

        self._ai_label_edit = QLineEdit()
        form.addRow("名称:", self._ai_label_edit)

        self._ai_url_edit = QLineEdit()
        self._ai_url_edit.setPlaceholderText("https://api.deepseek.com")
        form.addRow("API 地址:", self._ai_url_edit)

        self._ai_model_edit = QLineEdit()
        self._ai_model_edit.setPlaceholderText("deepseek-v4-flash")
        form.addRow("模型名:", self._ai_model_edit)

        self._ai_key_edit = QLineEdit()
        self._ai_key_edit.setPlaceholderText(
            "API Key（DeepSeek 可使用 DEEPSEEK_API_KEY 环境变量）"
        )
        self._ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self._ai_key_edit)

        temp_row = QHBoxLayout()
        self._ai_temp_spin = QDoubleSpinBox()
        self._ai_temp_spin.setRange(0.0, 1.0)
        self._ai_temp_spin.setSingleStep(0.1)
        self._ai_temp_spin.setValue(0.0)
        self._ai_temp_spin.setDecimals(1)
        temp_row.addWidget(QLabel("温度:"))
        temp_row.addWidget(self._ai_temp_spin)
        temp_row.addStretch()
        form.addRow("参数:", temp_row)

        self._ai_note_edit = QLineEdit()
        self._ai_note_edit.setPlaceholderText("备注/警告")
        form.addRow("备注:", self._ai_note_edit)
        lay.addLayout(form)

        # 警告标签
        self._ai_warning = QLabel(
            "⚠ 建议：自动修复请使用 <b>DeepSeek V4 Flash</b>（推荐）或同等能力的云端模型。<br>"
            "本地小模型（如 qwen3.5:4b）工具调用能力不足，<b>不建议用于自动修复</b>，仅适合对话交流。"
        )
        self._ai_warning.setWordWrap(True)
        self._ai_warning.setStyleSheet(
            "color: palette(windowtext);"
            "background: palette(midlight);"
            "border: 1px solid palette(mid);"
            "border-radius: 4px; padding: 4px;"
        )
        lay.addWidget(self._ai_warning)

        btn_row = QHBoxLayout()
        test_ai_btn = QPushButton("⚡ 检测连接")
        test_ai_btn.clicked.connect(self._on_test_ai_agent)
        btn_row.addWidget(test_ai_btn)
        save_btn = QPushButton("💾 保存")
        save_btn.clicked.connect(self._on_save_ai_agent)
        btn_row.addWidget(save_btn)
        delete_btn = QPushButton("🗑 删除配置")
        delete_btn.clicked.connect(self._on_delete_ai_agent)
        btn_row.addWidget(delete_btn)
        reset_ai_btn = QPushButton("🔄 恢复默认")
        reset_ai_btn.clicked.connect(self._on_reset_ai_agents)
        btn_row.addWidget(reset_ai_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._ai_status = QLabel("")
        self._ai_status.setWordWrap(True)
        lay.addWidget(self._ai_status)

        # 先连接信号再选中首项，确保初始选中触发表单填充
        self._ai_list.currentRowChanged.connect(self._on_ai_selected)
        self._refresh_ai_list()

        return w

    # ═══════════════════════════════════════════════════════════
    # 嵌入模型 Tab 回调
    # ═══════════════════════════════════════════════════════════

    def _refresh_embed_list(self):
        from dualign.providers import ProviderManager

        self._embed_list.clear()
        for p in ProviderManager.all_providers():
            active = " ★" if p.is_active else ""
            self._embed_list.addItem(
                f"{p.label}{active} — {p.model_name or '(未设置)'}"
            )
        if self._embed_list.count() > 0:
            self._embed_list.setCurrentRow(0)

    def _on_embed_selected(self, idx: int):
        from dualign.providers import ProviderManager

        providers = ProviderManager.all_providers()
        if 0 <= idx < len(providers):
            p = providers[idx]
            self._embed_label_edit.setText(p.label)
            self._embed_url_edit.setText(p.base_url)
            self._embed_model_edit.setText(p.model_name)
            self._embed_key_edit.setText(p.key_plain)
            # ── Instruction ──
            instr = getattr(p, "instruction_text", "") or ""
            self._embed_instr_enabled_cb.blockSignals(True)
            self._embed_instr_enabled_cb.setChecked(bool(instr))
            self._embed_instr_enabled_cb.blockSignals(False)
            self._embed_instruction_edit.setText(instr)
            self._embed_instruction_edit.setEnabled(bool(instr))

    def _on_instr_toggled(self, checked: bool):
        """Instruction 启用/禁用的联动。"""
        self._embed_instruction_edit.setEnabled(checked)
        if checked and not self._embed_instruction_edit.text().strip():
            # 用户刚打开开关但文本框为空 → 自动填入默认值
            self._embed_instruction_edit.setText(_DEFAULT_EMBEDDING_INSTRUCTION)

    def _on_reset_instruction(self):
        """恢复 Instruction 文本为内置默认值。"""
        self._embed_instruction_edit.setText(_DEFAULT_EMBEDDING_INSTRUCTION)
        self._embed_instr_enabled_cb.setChecked(True)

    def _on_test_embedding(self):
        from dualign.providers import ProviderManager, build_solution_guidance

        idx = self._embed_list.currentRow()
        providers = ProviderManager.all_providers()
        if 0 <= idx < len(providers):
            p = providers[idx]
            ok, detail, models = ProviderManager.health_check(p)
            guidance = build_solution_guidance(
                p.provider_id, detail, p.model_name, p.base_url
            )
            self._detected_models = models or []
            self._embed_model_picker.setEnabled(bool(self._detected_models))

            txt = f"{'✅' if ok else '❌'} {detail}<br>"
            if models:
                txt += f"可用模型: {', '.join(models[:10])}<br>"
                if self._embed_model_picker.isEnabled():
                    txt += "💡 点击 <b>↕</b> 从列表中选择模型名<br>"
            if guidance and not ok:
                txt += f"<br><pre style='color:gray;'>{guidance}</pre>"
            self._embed_status.setText(txt)

    def _on_save_embedding(self):
        from dualign.providers import ProviderManager

        idx = self._embed_list.currentRow()
        providers = ProviderManager.all_providers()
        if 0 <= idx < len(providers):
            p = providers[idx]
            p.label = self._embed_label_edit.text()
            p.base_url = self._embed_url_edit.text().strip()
            p.model_name = self._embed_model_edit.text().strip()
            key = self._embed_key_edit.text()
            if key:
                p.set_key_plain(key)
            # ── Instruction：禁用 → 空字符串 ──
            if self._embed_instr_enabled_cb.isChecked():
                p.instruction_text = self._embed_instruction_edit.text()
            else:
                p.instruction_text = ""
            ProviderManager.save()
            self._refresh_embed_list()
            self._embed_status.setText("✅ 已保存")
            self.config_changed.emit()

    def _on_reset_embedding(self):
        """恢复所有嵌入模型配置到默认值。"""
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "确认恢复默认",
            "恢复默认将重置所有嵌入模型配置到初始值，确定吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from dualign.providers import ProviderManager

        ProviderManager.reset_to_defaults()
        self._refresh_embed_list()
        self._embed_status.setText("✅ 已恢复默认配置")
        self.config_changed.emit()

    def _on_set_active_embedding(self):
        """将当前选中的提供方设为活跃。"""
        from dualign.providers import ProviderManager

        idx = self._embed_list.currentRow()
        providers = ProviderManager.all_providers()
        if 0 <= idx < len(providers):
            p = providers[idx]
            ProviderManager.set_active(p.provider_id)
            self._refresh_embed_list()
            self._embed_status.setText(f"✅ 已将「{p.label}」设为默认")

    def _on_open_config_folder(self):
        """在文件管理器中打开配置文件夹。"""
        import os as _os
        import subprocess as _subprocess

        try:
            from dualign.config import APP_DATA_DIR

            _os.makedirs(APP_DATA_DIR, exist_ok=True)
            if _os.name == "nt":
                _subprocess.Popen(["explorer", APP_DATA_DIR], shell=True)
            elif _os.name == "posix":
                _subprocess.Popen(["open", APP_DATA_DIR])
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "无法打开", f"无法打开配置文件夹: {e}")

    # ═══════════════════════════════════════════════════════════
    # AI 修复 Agent Tab 回调
    # ═══════════════════════════════════════════════════════════

    def _refresh_ai_list(self):
        from dualign.providers import load_repair_agents

        self._ai_list.clear()
        for a in load_repair_agents():
            active = " ★" if a.is_active else ""
            self._ai_list.addItem(f"{a.label}{active}")
        if self._ai_list.count() > 0:
            self._ai_list.setCurrentRow(0)

    def _on_ai_selected(self, idx: int):
        from dualign.providers import load_repair_agents

        agents = load_repair_agents()
        if 0 <= idx < len(agents):
            a = agents[idx]
            self._ai_label_edit.setText(a.label)
            self._ai_url_edit.setText(a.base_url)
            self._ai_model_edit.setText(a.model_name)
            self._ai_key_edit.setText(a.key_plain)
            self._ai_temp_spin.setValue(a.temperature)
            self._ai_note_edit.setText(a.note)

    def _on_test_ai_agent(self):
        """Test the same Responses tool-calling contract used by Agent runs."""
        url = self._ai_url_edit.text().strip().rstrip("/")
        model = self._ai_model_edit.text().strip()
        key = self._ai_key_edit.text().strip()

        if not url:
            self._ai_status.setText("⚠ 请先填写 API 地址")
            return
        if not model:
            self._ai_status.setText("⚠ 请先填写模型名")
            return

        try:
            from dualign.services.ai_repair_agent import DeepSeekNativeBackend

            backend = DeepSeekNativeBackend(
                temperature=0.0,
                max_tokens=32,
                model=model,
                base_url=url,
                api_key=key,
                reasoning_effort="none",
                request_timeout=15,
            )
            response = backend.chat(
                [
                    {
                        "role": "user",
                        "content": "Call the ping tool exactly once; do not answer in text.",
                    }
                ],
                thinking=False,
                tools=[
                    {
                        "type": "function",
                        "name": "ping",
                        "description": "Connection test.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    }
                ],
            )
            if any(call.name == "ping" for call in response.tool_calls):
                self._ai_status.setText(f"✅ Responses 工具调用可用！模型: {model}")
            else:
                self._ai_status.setText(
                    "⚠ 接口可响应，但未按要求产生工具调用；不宜用于 AI 审校"
                )
        except Exception as e:
            self._ai_status.setText(f"❌ 检测失败: {e}")

    def _on_save_ai_agent(self):
        from dualign.providers import (
            load_repair_agents,
            set_active_repair_agent,
        )

        idx = self._ai_list.currentRow()
        agents = load_repair_agents()
        if 0 <= idx < len(agents):
            a = agents[idx]
            a.label = self._ai_label_edit.text()
            a.base_url = self._ai_url_edit.text().strip()
            a.model_name = self._ai_model_edit.text().strip()
            key = self._ai_key_edit.text()
            if key:
                a.set_key_plain(key)
            a.temperature = self._ai_temp_spin.value()
            a.note = self._ai_note_edit.text()
            set_active_repair_agent(a.agent_id)
            self._refresh_ai_list()
            self._ai_status.setText("✅ 已保存")
            self.config_changed.emit()

    def _on_delete_ai_agent(self):
        """删除当前选中的 AI 修复 Agent 配置。"""
        from dualign.providers import load_repair_agents
        from PySide6.QtWidgets import QMessageBox

        idx = self._ai_list.currentRow()
        agents = load_repair_agents()
        if not (0 <= idx < len(agents)):
            return
        a = agents[idx]
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 Agent 配置「{a.label}」吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        agents.pop(idx)
        from dualign.providers import save_repair_agents

        save_repair_agents()
        self._refresh_ai_list()
        self._ai_status.setText(f"✅ 已删除「{a.label}」")
        self.config_changed.emit()

    def _on_reset_ai_agents(self):
        """恢复所有 AI 修复 Agent 配置到默认值。"""
        from PySide6.QtWidgets import QMessageBox
        from dualign.providers import load_repair_agents
        import dualign.providers as _providers_mod

        reply = QMessageBox.question(
            self,
            "确认恢复默认",
            "恢复默认将重置所有 AI 修复 Agent 配置到初始值，确定吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 清除缓存，下次 load_repair_agents() 自动从 DEFAULT_REPAIR_AGENTS 重建
        _providers_mod._repair_agents = None
        load_repair_agents()  # 触发重建
        self._refresh_ai_list()
        self._ai_status.setText("✅ 已恢复默认配置")
        self.config_changed.emit()

    def _on_accept(self):
        self.accept()


# ═══════════════════════════════════════════════════════════════
# LineNumberArea — 行号边栏
# ═══════════════════════════════════════════════════════════════


class LineNumberArea(QWidget):
    """行号边栏，配合 CodeEditor 绘制行号。"""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_line_numbers(event)


# ═══════════════════════════════════════════════════════════════
# CodeEditor — 带行号的编辑控件
# ═══════════════════════════════════════════════════════════════


class CodeEditor(QPlainTextEdit):
    """带行号的编辑区，自动换行，支持伙伴高度同步。"""

    def __init__(
        self, text: str = "", partner: Optional["CodeEditor"] = None, parent=None
    ):
        super().__init__(parent)
        self._partner = partner
        self._syncing = False

        self.setPlainText(text)
        self.setFont(QFont("Consolas", 10))
        self.setTabStopDistance(20)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

        self._line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_width()

        if self._partner:
            self.textChanged.connect(self._sync_height)

    # ── 行号宽度 ──

    def line_number_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 8 + 8 * digits

    def _update_line_number_width(self):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height()
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_width(), cr.height())
        )

    # ── 绘制行号 ──

    def _paint_line_numbers(self, event):
        p = QPainter(self._line_number_area)
        is_dark = self.palette().window().color().lightness() < 128
        p.fillRect(event.rect(), QColor("#2B2B2B" if is_dark else "#F0F0F0"))

        block = self.firstVisibleBlock()
        bn = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        w = self._line_number_area.width()

        p.setPen(QColor("#888888"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.drawText(
                    0,
                    top,
                    w - 4,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(bn + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            bn += 1
        p.end()

    # ── 伙伴高度同步 ──

    def _sync_height(self):
        if not self._partner or self._syncing or self._partner._syncing:
            return
        self._syncing = True
        h1 = self.document().documentLayout().documentSize().height()
        h2 = self._partner.document().documentLayout().documentSize().height()
        if h1 != h2:
            target = int(max(h1, h2)) + 4
            if h1 < h2:
                self.setMinimumHeight(target)
                self._partner.setMinimumHeight(0)
            else:
                self._partner.setMinimumHeight(target)
                self.setMinimumHeight(0)
        self._syncing = False


# ═══════════════════════════════════════════════════════════════
# FlagEditDialog — 标记注释
# ═══════════════════════════════════════════════════════════════


class FlagEditDialog(QDialog):
    """创建、编辑或删除人工标记。"""

    def __init__(
        self,
        note: str = "",
        parent=None,
        *,
        can_delete: bool = False,
        selection_count: int = 1,
    ):
        super().__init__(parent)
        self._delete_requested = False
        self.setWindowTitle("编辑标记" if can_delete else "添加标记")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        target = (
            f"将对 {selection_count} 个文本对设置同一条标记注释。"
            if selection_count > 1
            else "请记录该文本对需要后续处理的原因。"
        )
        layout.addWidget(QLabel(target))

        self._note_edit = QPlainTextEdit(note)
        self._note_edit.setPlaceholderText(
            "例如：拆分需复核：拆分后的局部对齐无法唯一确定"
        )
        self._note_edit.setMinimumHeight(100)
        layout.addWidget(self._note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存标记")
        self._delete_button = QPushButton("删除标记")
        self._delete_button.setEnabled(can_delete)
        buttons.addButton(
            self._delete_button, QDialogButtonBox.ButtonRole.DestructiveRole
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._delete_button.clicked.connect(self._delete_flag)
        layout.addWidget(buttons)

    @property
    def note(self) -> str:
        return self._note_edit.toPlainText().strip()

    @property
    def delete_requested(self) -> bool:
        return self._delete_requested

    def _delete_flag(self):
        self._delete_requested = True
        self.accept()


# ═══════════════════════════════
# BlockEditDialog — 手动校订
# ═══════════════════════════════


class BlockEditDialog(QDialog):
    """手动校订对话框 — 左右分栏、行号、同步高度、参考区。"""

    def __init__(
        self,
        src_lines: List[str],
        tgt_lines: List[str],
        parent=None,
        *,
        initial_src_lines: Optional[List[str]] = None,
        initial_tgt_lines: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("手动校订")
        self.setFixedSize(960, 540)

        self._src_lines = src_lines
        self._tgt_lines = tgt_lines
        self._init_src = initial_src_lines
        self._init_tgt = initial_tgt_lines
        self._result_src: List[str] = []
        self._result_tgt: List[str] = []

        self._build_ui()

    @property
    def result_src_lines(self) -> List[str]:
        return self._result_src

    @property
    def result_tgt_lines(self) -> List[str]:
        return self._result_tgt

    # ── 构建 UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ── ① 底部：统计 + 按钮（并排，最上方）──
        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet("font-weight:bold;")
        self._ok_btn = None
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(self._stats_lbl, 1)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        bottom_row.addWidget(btns)
        layout.addLayout(bottom_row)

        # ── ② 编辑区 ──
        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)

        src_group = QGroupBox("文档 A 校订")
        src_layout = QVBoxLayout(src_group)
        src_layout.setContentsMargins(4, 4, 4, 4)
        self._src_edit = CodeEditor("\n".join(self._src_lines))
        self._src_edit.textChanged.connect(self._on_text_changed)
        self._src_edit.installEventFilter(self)
        src_layout.addWidget(self._src_edit)
        edit_row.addWidget(src_group)

        tgt_group = QGroupBox("文档 B 校订")
        tgt_layout = QVBoxLayout(tgt_group)
        tgt_layout.setContentsMargins(4, 4, 4, 4)
        self._tgt_edit = CodeEditor("\n".join(self._tgt_lines), partner=self._src_edit)
        self._src_edit._partner = self._tgt_edit
        self._tgt_edit.textChanged.connect(self._on_text_changed)
        self._tgt_edit.installEventFilter(self)
        tgt_layout.addWidget(self._tgt_edit)
        edit_row.addWidget(tgt_group)

        layout.addLayout(edit_row)

        # ── ③ 初始参考区（在下，只用原生 palette，无背景色覆盖）──
        has_initial = bool(self._init_src) or bool(self._init_tgt)
        if has_initial:
            init_row = QHBoxLayout()
            init_row.setSpacing(8)
            for title, lines in [
                ("文档 A 初始内容（只读）", self._init_src),
                ("文档 B 初始内容（只读）", self._init_tgt),
            ]:
                g = QGroupBox(title)
                gl = QVBoxLayout(g)
                gl.setContentsMargins(4, 4, 4, 4)
                editor = CodeEditor("\n".join(lines or []))
                editor.setReadOnly(True)
                gl.addWidget(editor)
                init_row.addWidget(g)
            layout.addLayout(init_row)

        self._update_stats()

    # ── 事件过滤器：焦点转移时自动过滤空行 ──

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusOut:
            if obj is self._src_edit:
                self._filter_blank_lines(self._src_edit)
            elif obj is self._tgt_edit:
                self._filter_blank_lines(self._tgt_edit)
        return super().eventFilter(obj, event)

    # ── 统计 + OK 按钮状态 ──

    def _on_text_changed(self):
        self._update_stats()

    @staticmethod
    def _strip_blank_lines(lines: List[str]) -> List[str]:
        """去除首尾空行，保留内部空行。"""
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return [line for line in lines if line.strip()]

    def _filter_blank_lines(self, editor: CodeEditor) -> bool:
        """移除编辑器中的所有空行。返回是否有变更。"""
        lines = editor.toPlainText().split("\n")
        filtered = [line for line in lines if line.strip()]
        new_text = "\n".join(filtered)
        if new_text != editor.toPlainText():
            editor.blockSignals(True)
            editor.setPlainText(new_text)
            editor.blockSignals(False)
            return True
        return False

    def _update_stats(self):
        src_text = self._src_edit.toPlainText()
        tgt_text = self._tgt_edit.toPlainText()
        sl = [line for line in src_text.split("\n") if line.strip()]
        tl = [line for line in tgt_text.split("\n") if line.strip()]
        ls, lt = len(sl), len(tl)

        row_match = ls == lt
        status = "✓ 1:1" if row_match else f"✓ {ls}:{lt} 多块关系"
        color = "#4CAF50"

        self._stats_lbl.setText(
            f"<span style='color:{color};'>"
            f"文档 A {ls} 行 / 文档 B {lt} 行 → {status}"
            f"</span>"
            f"  ({len(src_text)} 字符 / {len(tgt_text)} 字符)"
        )

        # 双文档关系允许 N:M 以及一侧为空；仅禁止两侧同时为空。
        ok_enabled = ls > 0 or lt > 0
        if self._ok_btn:
            self._ok_btn.setEnabled(ok_enabled)

    # ── 确认 ──

    def _on_accept(self):
        raw_src = self._src_edit.toPlainText().split("\n")
        raw_tgt = self._tgt_edit.toPlainText().split("\n")

        self._result_src = self._strip_blank_lines(raw_src)
        self._result_tgt = self._strip_blank_lines(raw_tgt)
        self.accept()


class SolidifyPolicyDialog(QDialog):
    """Shared solidification policy editor for Dualign and integrating apps."""

    def __init__(self, policy=None, parent=None):
        super().__init__(parent)
        from dualign.services.solidify import (
            DEFAULT_SOLIDIFY_TYPES,
            SOLIDIFY_PRESETS,
            SOLIDIFY_TYPE_LABELS,
            SolidifyPolicy,
        )

        self.setWindowTitle("固化修改设置")
        self.setMinimumWidth(420)
        self._preset_values = [
            ("自定义", ""),
            ("仅校订文本", "edits"),
            ("行级兼容（全部）", "line-aligned"),
            ("仅文档 A", "document-a"),
            ("仅文档 B", "document-b"),
            ("全部关闭", "none"),
        ]
        self._checks = {}
        current = policy or SolidifyPolicy(DEFAULT_SOLIDIFY_TYPES)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "选中的修复会写入正文并从当前工作记录中移除；未选中的修复会重锚后继续保留。"
            "双侧结构操作须同时启用 A/B 对应类型；审核标记不会丢失。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        preset_combo = QComboBox()
        for label, name in self._preset_values:
            preset_combo.addItem(label, name)
        preset_combo.currentIndexChanged.connect(self._apply_preset)
        layout.addWidget(preset_combo)

        for key, label in SOLIDIFY_TYPE_LABELS.items():
            check = QCheckBox(label)
            check.setChecked(key in current.enabled)
            check.toggled.connect(self._mark_custom)
            layout.addWidget(check)
            self._checks[key] = check

        matching = next(
            (
                index
                for index, (_label, name) in enumerate(self._preset_values)
                if name and SOLIDIFY_PRESETS[name] == current.enabled
            ),
            0,
        )
        preset_combo.blockSignals(True)
        preset_combo.setCurrentIndex(matching)
        preset_combo.blockSignals(False)
        self._preset_combo = preset_combo

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def policy(self):
        from dualign.services.solidify import SolidifyPolicy

        return SolidifyPolicy(
            frozenset(key for key, check in self._checks.items() if check.isChecked())
        )

    def _apply_preset(self, index):
        from dualign.services.solidify import SolidifyPolicy

        name = self._preset_combo.itemData(index)
        if not name:
            return
        enabled = SolidifyPolicy.from_preset(name).enabled
        for key, check in self._checks.items():
            check.blockSignals(True)
            check.setChecked(key in enabled)
            check.blockSignals(False)

    def _mark_custom(self, _checked):
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)


class SolidifyReviewDialog(QDialog):
    """Preview selected effects and the report operations that will remain."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        from dualign.services.solidify import SOLIDIFY_TYPE_LABELS

        self.setWindowTitle("审查固化修改")
        self.resize(980, 680)
        layout = QVBoxLayout(self)
        enabled = [
            SOLIDIFY_TYPE_LABELS[key]
            for key in SOLIDIFY_TYPE_LABELS
            if key in plan.policy.enabled
        ]
        summary = (
            f"固化范围：{'、'.join(enabled) or '无'}；"
            f"写入 {len(plan.applied)} 条，保留 {len(plan.remaining_actions)} 条。"
        )
        label = QLabel(summary)
        label.setWordWrap(True)
        label.setStyleSheet("font-weight:600;color:#2E7D32;")
        layout.addWidget(label)

        self._change_table = QTableWidget(len(plan.changes), 4)
        self._change_table.setHorizontalHeaderLabels(
            ["关系", "操作", "文档 A 变化", "文档 B 变化"]
        )
        self._change_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._change_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._change_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._change_table.setAlternatingRowColors(True)
        self._change_table.setWordWrap(True)
        self._change_table.verticalHeader().setVisible(False)
        header = self._change_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        for row, change in enumerate(plan.changes):
            relation = "、".join(change.relation_ids)
            operation = self._operation_text(change, SOLIDIFY_TYPE_LABELS)
            document_a = self._side_change_text(
                change.document_a_before, change.document_a_after
            )
            document_b = self._side_change_text(
                change.document_b_before, change.document_b_after
            )
            for column, content in enumerate(
                (relation, operation, document_a, document_b)
            ):
                item = QTableWidgetItem(content)
                item.setToolTip(content)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                )
                self._change_table.setItem(row, column, item)
            self._change_table.setRowHeight(row, 76)
        layout.addWidget(self._change_table, 1)

        self._diff_details = QGroupBox("完整文档差异")
        self._diff_details.setCheckable(True)
        self._diff_details.setChecked(False)
        details_layout = QVBoxLayout(self._diff_details)
        self._diff_container = QWidget()
        container_layout = QVBoxLayout(self._diff_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        self._diff_splitter = QSplitter(Qt.Orientation.Vertical)
        self._diff_editors = []
        for title, content in (
            ("文档 A", plan.document_a_diff()),
            ("文档 B", plan.document_b_diff()),
        ):
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            panel_layout.addWidget(QLabel(title))
            editor = QPlainTextEdit(content or "（无变化）")
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            panel_layout.addWidget(editor, 1)
            self._diff_editors.append(editor)
            self._diff_splitter.addWidget(panel)
        container_layout.addWidget(self._diff_splitter)
        details_layout.addWidget(self._diff_container)
        self._diff_container.setVisible(False)
        self._diff_details.toggled.connect(self._diff_container.setVisible)
        layout.addWidget(self._diff_details)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        apply_button.setText("固化所选修改")
        apply_button.setEnabled(plan.has_changes)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _side_change_text(before, after) -> str:
        if tuple(before) == tuple(after):
            return "—"
        lines = [f"− {line}" for line in before]
        lines.extend(f"+ {line}" for line in after)
        return "\n".join(lines) or "—"

    @staticmethod
    def _operation_text(change, labels) -> str:
        kinds = {
            "merge": "合并 [M]",
            "split": "拆分 [S]",
            "edit": "校订 [E]",
            "delete": "删除 [D]",
        }
        effects = "、".join(labels[value] for value in change.effects)
        source = change.source or "auto"
        return f"{kinds.get(change.kind, change.kind)}\n{effects}\n来源：{source}"


# ═══════════════════════════════════════════════════════════════
# AboutDialog — 关于对话框（图标 + 标题比例与欢迎页一致）
# ═══════════════════════════════════════════════════════════════


class AboutDialog(QDialog):
    """关于 Dualign — 自定义对话框，布局比例与欢迎页保持一致。"""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 Dualign Studio")
        self.setMinimumSize(480, 380)
        self._build_ui(version)

    def _svg_path(self) -> str | None:
        """找到 SVG 图标路径（兼容 PyInstaller 打包）。"""
        import sys as _sys

        if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
            _c = Path(_sys._MEIPASS) / "assets" / "branding" / "dualign-outline.svg"
            if _c.is_file():
                return str(_c)
        _here = Path(__file__).parent
        _c = _here.parents[2] / "assets" / "branding" / "dualign-outline.svg"
        if _c.is_file():
            return str(_c)
        return None

    def _build_ui(self, version: str):
        root = QVBoxLayout(self)
        root.setSpacing(0)

        # ── 图标 + 标题区（与欢迎页一致的比例）──
        hero = QHBoxLayout()
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.setSpacing(14)

        _svg = self._svg_path()
        if _svg:
            icon_wrap = QVBoxLayout()
            icon_wrap.setContentsMargins(0, 0, 0, 0)
            icon_wrap.setSpacing(0)
            icon_wrap.addStretch()
            logo = QSvgWidget(_svg)
            logo.setFixedSize(56, 56)
            logo.setStyleSheet("background: transparent;")
            icon_wrap.addWidget(logo, 0, Qt.AlignmentFlag.AlignBottom)
            hero.addLayout(icon_wrap)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addStretch()

        title = QLabel(f"Dualign Studio v{version}")
        tf = QFont()
        tf.setPointSize(22)
        tf.setBold(True)
        title.setFont(tf)
        text_col.addWidget(title)

        subtitle = QLabel("双语平行文档对齐与 AI 辅助校验工具")
        sf = QFont()
        sf.setPointSize(11)
        subtitle.setFont(sf)
        text_col.addWidget(subtitle)

        hero.addLayout(text_col)
        root.addLayout(hero)
        root.addSpacing(12)

        # ── 详情区 ──
        detail = QLabel(
            "<h3>关于 Dualign Studio</h3>"
            "<p>Dualign Studio 是一款面向翻译工作者的双语对齐校验桌面工具，"
            "专注于建立两个平行文档之间的块级对应关系。它自动识别结构性错位"
            "（如合并、拆分、遗漏），同时接入大语言模型提供语义层面的审校建议，"
            "显著降低人工校对成本。</p>"
            "<hr>"
            "<p><b>核心依赖</b></p>"
            "<ul>"
            "<li>Ollama — 句子嵌入编码</li>"
            "<li>DeepSeek / Ollama — AI 语义审校</li>"
            "<li>PySide6 — 交互式 GUI 工作台</li>"
            "</ul>"
            "<hr>"
            "<p><b>项目主页</b> "
            '<a href="https://github.com/LoveElysia1314/Dualign">'
            "github.com/LoveElysia1314/Dualign</a></p>"
            "<p><b>问题反馈</b> "
            '<a href="https://github.com/LoveElysia1314/Dualign/issues">'
            "GitHub Issues</a></p>"
            "<p><b>联系作者</b> "
            '<a href="https://github.com/LoveElysia1314">LoveElysia1314</a> · '
            '<a href="mailto:dr.zqr@outlook.com">dr.zqr@outlook.com</a></p>'
            "<hr>"
            "<p><b>许可证</b> MIT</p>"
        )
        detail.setWordWrap(True)
        detail.setOpenExternalLinks(True)
        detail.setStyleSheet(
            "a {color: palette(link);} a:hover {color: palette(link);}"
        )
        root.addWidget(detail, 1)

        # ── 底部按钮 ──
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btn_box.accepted.connect(self.accept)
        root.addWidget(btn_box)
