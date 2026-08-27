"""
Dualign — DualignWindow: 主窗口

设计目标：GUI 层只做三件事：
  1. 展示数据 (_render_table)
  2. 响应用户操作 → _apply_action → RepairService
  3. 管理 UI 状态 (筛选/导航/历史)

不做：
  - 不直接操作 ChapterState
  - 不实现修复逻辑
  - 不计算文本输出
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Any, Set

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMessageBox,
    QAbstractItemView,
    QFileDialog,
    QApplication,
    QDialog,
)

from dualign.core import AlignmentResult
from dualign.common import content_hash, file_bytes_sha256, file_identity_changed
from dualign.models.state import AlignmentSnapshot
from dualign.models.action import CONTENT_ACTION_KINDS, RepairAction
from dualign.services.repair import (
    RepairState,
    RepairService,
    SPLIT_FAILURE_REALIGN,
)
from dualign.gui.dialogs import BlockEditDialog, FlagEditDialog
from dualign.gui.workspace import FileQueueItem
from dualign.gui.settings import (
    DualignConfig,
    KEY_LAST_OPEN_DIR,
)
from dualign.core.text import smart_join_lines as _join

# ═══════════════════════════════════════════════════════════════
# DualignWindow — 方法实现（被 dualign.gui.window 采纳为方法）
# ═══════════════════════════════════════════════════════════════


class WindowActionsMixin:
    """WindowActionsMixin — 通过多重继承为 DualignWindow 提供方法。"""

    def _invalidate_relation_scores(self, ordinals) -> None:
        """Invalidate runtime scores and remove persisted values for changed rows."""
        relation_ordinals = {int(ordinal) for ordinal in ordinals}
        score_manager = getattr(self, "_score_mgr", None)
        if score_manager is not None:
            score_manager.invalidate_ordinals(sorted(relation_ordinals))
        score_cache = getattr(self, "_score_cache", None)
        if score_cache is not None and self._repair_state is not None:
            for ordinal in relation_ordinals:
                score_cache.discard(self._repair_state.snapshot.relation_id(ordinal))

    def _set_known_relation_scores(self, ordinal: int, scores) -> None:
        """Seed scores already computed by split instead of scheduling them again."""
        self._invalidate_relation_scores([ordinal])
        score_manager = getattr(self, "_score_mgr", None)
        score_cache = getattr(self, "_score_cache", None)
        for sub, raw_score in enumerate(scores):
            score = float(raw_score)
            if score_manager is not None:
                score_manager.set_ready_score(ordinal, sub, score)
            if score_cache is not None:
                score_cache.set(
                    self._repair_state.snapshot.relation_id(ordinal), sub, score
                )

    def _on_open_demo(self):
        """打开 Demo 示例文件对的全新临时副本。

        路径解析委托给 dualign.demo.get_demo_paths()，
        与 demo_gui.py 逻辑完全一致。
        """
        try:
            from dualign.demo import get_demo_paths

            src, tgt, label = get_demo_paths()
            self.load_file_pair(src, tgt, label=label)
            self._safe_status("已创建并打开 Demo 临时副本；内置样例不会被覆写")
        except (ImportError, FileNotFoundError) as e:
            self._safe_status(f"Demo 文件不存在: {e}")
            self._on_open_files()

    def _on_workspace_pair_selected(self, item):
        """Load exactly once from a workspace selection event."""

        if item.entry is not None:
            self._on_entry_selected(item.entry)
            return
        self._current_entry = None
        self.load_file_pair(item.src_path, item.tgt_path, item.label)

    def _on_workspace_add_queue(self):
        """＋ 添加按钮回调：弹出文件选择器，加入队列。"""
        src_path, _ = QFileDialog.getOpenFileName(
            self, "选择文档 A", "", "Markdown (*.md);;Text (*.txt);;All (*)"
        )
        if not src_path:
            return
        tgt_path, _ = QFileDialog.getOpenFileName(
            self, "选择文档 B", "", "Markdown (*.md);;Text (*.txt);;All (*)"
        )
        if not tgt_path:
            return
        label = Path(src_path).stem.split(".")[0]
        fq = FileQueueItem(label=label, src_path=src_path, tgt_path=tgt_path)
        self._workspace.add_to_queue(fq)

    def _on_workspace_align_checked(self):
        """对齐当前选中的文件对。"""
        sel = self._workspace.selected_item()
        if sel:
            self._on_workspace_pair_selected(sel)

    def _on_workspace_remove_checked(self):
        """移除当前选中的文件对。"""
        self._workspace.remove_selected()

    def _on_workspace_nav(self, direction: int):
        """队列导航：-1=prev, 1=next。"""
        if direction < 0:
            self._workspace._nav_prev()
        else:
            self._workspace._nav_next()

    def _on_reset_current_relation(self):
        """重置当前选中文本对的修复。"""
        if self._repair_state is None:
            return
        ordinal = self._review._current_ordinal()
        if ordinal is None or ordinal < 0:
            self._safe_status("请先在审校面板中选中一个文本对")
            return
        self._undo_stack.append(self._repair_state)
        relation_id = self._repair_state.snapshot.relation_id(ordinal)
        self._repair_state = self._repair_state.reset_relation(relation_id)
        self._invalidate_relation_scores([ordinal])
        self._reset_accepted_proposals([ordinal])
        self._refresh()
        self._save_session()
        self._set_temp_status(f"已重置关系[{ordinal}] 的修复", "info")

    def load_file_pair(
        self,
        src_path: str,
        tgt_path: str,
        label: str = "",
        *,
        report_path: str = "",
        document_a_id: str = "",
        document_b_id: str = "",
        language_a: str = "",
        language_b: str = "",
    ):
        """加载文件对并启动对齐流水线。

        缓存命中 → 跳过编码和对齐。
        缓存未命中 → EncodeThread → _on_text_ready → _on_encoded → _on_align_done。
        每次调用自动取消前一次未完成操作（_load_op_id 防旧回调污染）。
        """
        # ── 文件存在性检查 ──
        missing = []
        if not os.path.isfile(src_path):
            missing.append(f"文档 A: {src_path}")
        if not os.path.isfile(tgt_path):
            missing.append(f"文档 B: {tgt_path}")
        if missing:
            from PySide6.QtWidgets import QMessageBox

            msg = "以下文件不存在，请检查路径是否已被移动或删除：\n\n" + "\n".join(
                missing
            )
            QMessageBox.warning(self, "文件不存在", msg)
            # 从最近列表移除并刷新欢迎页
            if hasattr(self, "_workspace"):
                self._workspace.remove_recent_pair(src_path, tgt_path)
                if hasattr(self, "_welcome") and self._welcome is not None:
                    self._welcome.set_recent_pairs(self._workspace.get_recent_pairs())
            return

        # ── 取消前一次未完成的操作（停止旧线程 + 递增操作 ID）──
        self._cancel_current_load()
        if hasattr(self, "_focus"):
            self._focus.clear()

        self._src_path = src_path
        self._tgt_path = tgt_path
        from dualign.services.cli_pipeline import default_report_path

        self._report_path = report_path or str(default_report_path(src_path))
        self._report_file_hash = file_bytes_sha256(self._report_path)
        self._report_file_present = os.path.isfile(self._report_path)
        self._pair_base_state = None
        self._document_a_id = document_a_id
        self._document_b_id = document_b_id
        self._language_a = language_a
        self._language_b = language_b

        # 同步路径到工作区面板
        if hasattr(self, "_workspace"):
            self._workspace.set_file_paths(src_path, tgt_path, label or "")

        from dualign import __version__ as _v

        self.setWindowTitle(f"Dualign v{_v} — {label}")

        # ── 先推导 entry_id（用于日志和 cache，在缓存命中前就必需）──
        _entry_id = ""
        if self._current_entry:
            _entry_id = getattr(self._current_entry, "entry_id", "") or ""
        if not _entry_id:
            _entry_id = Path(src_path).stem.split(".")[0]
        self._current_entry_id = _entry_id

        # ── 初始化 SimilarityScorer（实际模型仍按需延迟加载）──
        from dualign.services.similarity import SimilarityScorer

        self._scorer = SimilarityScorer(entry_id=self._current_entry_id)

        # 文本读取、哈希计算与 report 缓存探测均放到工作线程；GUI 先进入
        # 锁定预览态，避免大章节/网络模型准备期间冻结主事件循环。
        from dualign.gui.workers import EncodeThread
        from dualign.services.cli_pipeline import _provenance

        if hasattr(self, "_welcome") and self._welcome is not None:
            self._welcome.set_aligning("正在读取并检查缓存…")

        self._preview_active = True
        self._status_bar.set_view_mode(True)
        self._status_bar.set_view_mode_enabled(False)
        self._status_bar.set_preview_active(True, phase="正在读取…")
        self._status("正在读取并检查缓存…")

        self._enc_thread = EncodeThread(
            src_path,
            tgt_path,
            entry_id=_entry_id,
            report_path=self._report_path,
            expected_provenance=_provenance(None, self._align_config),
        )
        self._connect_encode_thread(self._enc_thread, self._load_op_id)
        self._enc_thread.start()

    def _connect_encode_thread(self, thread, generation: int):
        """Connect one encode job with its immutable load generation."""
        thread.status_signal.connect(
            lambda message, g=generation: (
                self._on_prepare_status(message) if g == self._load_op_id else None
            )
        )
        thread.text_ready_signal.connect(
            lambda src_hash, tgt_hash, src_lines, tgt_lines, g=generation: (
                self._on_text_ready(g, src_hash, tgt_hash, src_lines, tgt_lines)
            )
        )
        thread.cache_hit_signal.connect(
            lambda payload, g=generation: self._on_alignment_cache_hit(g, payload)
        )
        thread.finished_signal.connect(
            lambda se, te, sl, tl, sh, th, g=generation: self._on_encoded(
                g, se, te, sl, tl, sh, th
            )
        )
        thread.error_signal.connect(
            lambda context, traceback, g=generation: (
                self._on_worker_error(context, traceback)
                if g == self._load_op_id
                else None
            )
        )

    def _on_prepare_status(self, message: str):
        """同步后台准备阶段到日志和预览锁定提示。"""
        self._status(message)
        if not self._preview_active:
            return
        if "缓存命中" in message:
            phase = "正在恢复缓存…"
        elif "模型加载" in message:
            phase = "正在加载模型…"
        elif "编码完成" in message:
            phase = "正在对齐…"
        elif "编码" in message or "缓存" in message:
            phase = "正在编码…"
        else:
            phase = "正在准备…"
        self._status_bar.set_preview_active(True, phase=phase)

    def load_from_provider(self, entries: List[Any]):
        """从外部条目序列加载章节列表。"""
        self._entries = entries
        # 构建文件队列
        items = []
        for e in entries:
            label = getattr(e, "label", str(e))
            src = getattr(e, "document_a_path", "")
            tgt = getattr(e, "document_b_path", "")
            items.append(
                FileQueueItem(label=label, src_path=src, tgt_path=tgt, entry=e)
            )
        self._workspace.set_queue(items)
        if entries:
            self._on_entry_selected(entries[0])

    def _on_entry_selected(self, entry: Any):
        """章节选中（项目模式）。加载文件对并对齐。"""
        self._current_entry = entry
        src_path = getattr(entry, "document_a_path", "")
        tgt_path = getattr(entry, "document_b_path", "")
        label = getattr(entry, "label", "")
        if src_path and tgt_path:
            self._workspace.set_file_paths(src_path, tgt_path, label)
            self.load_file_pair(
                src_path,
                tgt_path,
                label,
                report_path=getattr(entry, "report_path", ""),
                document_a_id=getattr(entry, "document_a_id", ""),
                document_b_id=getattr(entry, "document_b_id", ""),
                language_a=getattr(entry, "language_a", ""),
                language_b=getattr(entry, "language_b", ""),
            )
        # 无需手动激活面板，原生 QTabBar 已处理

    def _release_retired_load_thread(self, thread):
        """Drop ownership once a superseded worker has actually stopped."""

        getattr(self, "_retired_load_threads", set()).discard(thread)

    def _retire_load_thread(self, attribute: str, wait_ms: int) -> None:
        """Stop one owned worker without destroying it while it is running."""

        thread = getattr(self, attribute, None)
        setattr(self, attribute, None)
        if thread is None or not thread.isRunning():
            return
        thread.stop()
        if wait_ms:
            thread.wait(wait_ms)
        if not thread.isRunning():
            return

        retired = getattr(self, "_retired_load_threads", None)
        if retired is None:
            retired = set()
            self._retired_load_threads = retired
        if thread not in retired:
            retired.add(thread)
            thread.finished.connect(
                lambda retired_thread=thread: self._release_retired_load_thread(
                    retired_thread
                )
            )

    def _cancel_current_load(self, *, drain_retired: bool = False) -> bool:
        """取消当前正在进行的加载操作。

        停止所有后台线程，递增操作 ID，使后续到达的旧回调被 _on_encoded / _on_align_done 忽略。
        超时后仍在运行的线程由窗口保留所有权，直到其 finished 信号到达。
        """
        self._load_op_id += 1
        # Never wait for an old encoder/aligner on the GUI thread. Generation
        # IDs already make late results harmless, while retained ownership
        # prevents QThread destruction until each worker finishes naturally.
        self._retire_load_thread("_enc_thread", 0)
        self._retire_load_thread("_worker", 0)

        retired = getattr(self, "_retired_load_threads", set())
        if drain_retired and retired:
            for thread in tuple(retired):
                thread.stop()
                if not thread.isRunning():
                    retired.discard(thread)
        return not any(thread.isRunning() for thread in retired)

    def _on_text_ready(self, generation, _src_hash, _tgt_hash, src_lines, tgt_lines):
        """文本就绪回调 — 立即进入预览模式展示原文/译文行。

        EncodeThread 读取文件后第一时间发射，此时编码尚未开始。
        用户可阅读文本，评分列暂显示灰色 "…"。
        """
        if generation != self._load_op_id:
            return
        self.src_lines, self.tgt_lines = src_lines, tgt_lines
        self._src_hash, self._tgt_hash = _src_hash, _tgt_hash
        self._preview_scores = None
        self._ensure_table_in_stacked()
        self._show_table()
        self._switch_table_mode(True)
        self._preview_active = True
        self._status_bar.set_view_mode_enabled(False)
        self._status_bar.set_preview_active(True, phase="正在检查缓存…")
        self._render_preview()

    def _on_alignment_cache_hit(self, generation, payload):
        """后台确认 report 缓存有效后，直接恢复校订态而不加载模型。"""
        if generation != self._load_op_id:
            return
        result, src_lines, tgt_lines, src_hash, tgt_hash = payload
        self.src_lines, self.tgt_lines = src_lines, tgt_lines
        self._src_hash, self._tgt_hash = src_hash, tgt_hash
        self._status_bar.set_preview_active(True, phase="正在恢复工作报告…")
        self._status("已加载工作报告", "success")
        self._ensure_table_in_stacked()
        self._show_table()
        self._on_align_done(generation, result)

    def _on_encoded(self, generation, se, te, sl, tl, sh, th):
        """EncodeThread 完成后回调（接收 6 个参数）。存到实例变量，启动对齐。

        如果 _load_op_id 已变更（即新的 load_file_pair 已启动），则丢弃此结果。
        """
        if generation != self._load_op_id:
            return

        try:
            self.src_emb, self.tgt_emb = se, te
            self.src_lines, self.tgt_lines = sl, tl
            self._src_hash, self._tgt_hash = sh, th

            # ── 预览模式: 用本地 dot 刷新评分列（零 API 调用）──
            if self._preview_active:
                import numpy as _np

                n = min(len(sl), len(tl))
                if n > 0:
                    diag = _np.sum(se[:n] * te[:n], axis=1).astype(_np.float64)
                    self._preview_scores = diag
                self._render_preview()
                self._status_bar.set_preview_active(True, phase="正在对齐…")

            self._status("对齐中...")
            QApplication.processEvents()
            self._start_align(generation)
        except Exception as e:
            self._show_error("编码完成回调", e)

    def _start_align(self, generation):
        """构造 AlignWorker 并启动对齐。"""
        from dualign.gui.workers import AlignWorker
        from dualign.services.embedding import _try_lazy_load_model

        if self.src_emb is None or self.tgt_emb is None:
            return

        # ── 停止前一次未完成的对齐线程 ──
        self._retire_load_thread("_worker", 3000)

        # EncodeThread 已在模型加载和编码之前统一探测报告缓存。能到达这里
        # 就必然是缓存未命中，无需再次读报告和重复计算内容哈希。
        # ── 清除旧修复会话（基于旧对齐结果，已失效）──
        # 但注意：report.json 中可能包含外部 AI 校订的 repair_log/ai_proposals/ai_review，
        # 使对齐缓存失效：清空 ops 和 stats，保留 AI 相关字段供新对齐后复用。
        self._invalidate_align_cache()

        model = _try_lazy_load_model()
        self._status("开始计算对齐方案...")
        QApplication.processEvents()

        self._worker = AlignWorker(
            self._align_config,
            self.src_emb,
            self.tgt_emb,
            self.src_lines,
            self.tgt_lines,
            encode_fn=model.encode if model else None,
            src_path=getattr(self, "_src_path", ""),
            tgt_path=getattr(self, "_tgt_path", ""),
            entry_id=getattr(self, "_current_entry_id", ""),
        )
        self._worker.finished_signal.connect(
            lambda result, g=generation: self._on_align_done(g, result)
        )
        self._worker.error_signal.connect(
            lambda context, traceback, g=generation: (
                self._on_worker_error(context, traceback)
                if g == self._load_op_id
                else None
            )
        )
        self._worker.start()

    def _on_align_done(self, generation: int, result: AlignmentResult):
        """对齐完成后初始化修复状态。尝试加载已有的修复会话。

        如果 _load_op_id 已变更（即新的 load_file_pair 已启动），则丢弃此结果。
        全方法 try/except 保护，防止未捕获异常导致窗口闪退。
        """
        try:
            if generation != self._load_op_id:
                return

            if result.status == "rejected":
                self._repair_state = None
                self._alignment_snapshot = None
                self._align_stats = result.stats
                self._alignment_gate = dict(result.gate or {})
                report_path = self._session_path()
                if result.stats.get("load_origin") != "report":
                    from dualign.core import alignment_payload
                    from dualign.core.calibration import (
                        resolve_alignment_calibration,
                    )
                    from dualign.services.cli_pipeline import _provenance
                    from dualign.services.embedding import _try_lazy_load_model
                    from dualign.services.report_io import build_report, save_report

                    model = _try_lazy_load_model()
                    resolved = resolve_alignment_calibration(
                        model,
                        calibration_id=getattr(
                            self._align_config, "calibration_id", ""
                        ),
                    )
                    calibration_id = (
                        resolved.calibration_id if resolved is not None else ""
                    )
                    report = build_report(
                        chapter_id=self._current_entry_id,
                        document_a_path=self._src_path,
                        document_b_path=self._tgt_path,
                        operations=[],
                        stats=result.stats,
                        quality={
                            "level": "diagnostic_only",
                            "rejections": [],
                            "indicators": {"alignment_status": "rejected"},
                        },
                        alignment=alignment_payload(
                            result, calibration_id=calibration_id
                        ),
                        provenance=_provenance(
                            model, self._align_config, calibration_id
                        ),
                    )
                    save_report(report, report_path)
                self._report_file_hash = file_bytes_sha256(report_path)
                self._report_file_present = os.path.isfile(report_path)
                reason_labels = {
                    "no_correspondence": "未检测到足够的双语对应关系",
                    "order_incompatible": "对应内容的顺序与单调对齐不兼容",
                    "order_unidentifiable": "无法识别稳定的对应顺序",
                    "calibration_unavailable": "当前嵌入模型没有匹配的校准资料",
                    "empty_document": "至少一侧文档为空",
                }
                self._status(
                    "对齐已拒绝：" + reason_labels.get(result.reason, result.reason),
                    "warning",
                )
                # A rejected result has no trustworthy relation projection,
                # but the raw line-by-line preview remains useful.  Re-enter
                # preview explicitly because cache hits do not emit text_ready.
                self._preview_active = False
                self._status_bar.set_view_mode(True)
                self._on_view_mode_toggled(True)
                self._status_bar.set_preview_only()
                self._update_feature_gating()
                return

            self._alignment_snapshot = AlignmentSnapshot.from_alignment(
                result.all_ops, self.src_lines, self.tgt_lines
            )
            self._align_stats = result.stats
            self._alignment_gate = dict(result.gate or {})
            if hasattr(self, "_score_cache"):
                self._score_cache.clear()

            # ── 尝试加载已有的修复会话 ──
            loaded = self._load_session()
            if loaded is not None:
                self._repair_state = loaded
                self._status("已恢复上次修复会话", "success")
            else:
                self._repair_state = RepairState.from_ops(
                    result.all_ops, self.src_lines, self.tgt_lines
                )

            # Loading an existing report must respect flags the user has
            # already edited or removed.  A freshly recomputed alignment gets
            # flags for its current disagreement islands; existing user flags
            # on the same operation take precedence over the generated note.
            if (
                result.status == "needs_review"
                and result.stats.get("load_origin") != "report"
            ):
                from dualign.services.repair import (
                    review_flags_for_uncertain_regions,
                )

                flagged_ops = {
                    self._repair_state.action_ordinal(action)
                    for action in self._repair_state.repair_log
                    if action.kind == "flag"
                }
                for action in review_flags_for_uncertain_regions(
                    result.all_ops,
                    result.uncertain_regions,
                    alternative_operations=result.alternative_ops,
                    relation_ids=self._repair_state.snapshot.relation_ids,
                ):
                    if self._repair_state.action_ordinal(action) not in flagged_ops:
                        self._repair_state = self._repair_state.apply(action)

            self._initialize_pair_editing_state(result)

            self._undo_stack.clear()
            self._redo_stack.clear()
            # The combo box is the user-visible source of truth.  Loading a new
            # pair must not silently reset the cached strategy while leaving the
            # displayed selection unchanged.
            self._on_strategy_changed(self._review.get_strategy_index())

            stats = result.stats
            quality_payload = {
                "level": "diagnostic_only",
                "rejections": [],
                "indicators": {"alignment_status": result.status},
            }

            if result.status == "needs_review":
                self._status(
                    f"对齐完成，{len(result.uncertain_regions)} 个分歧区域已用 [F] 标记",
                    "warning",
                )
            else:
                self._status("对齐完成", "success")

            _report_path = self._session_path()
            if stats.get("load_origin") != "report":
                from dualign.services.cli_pipeline import _provenance
                from dualign.services.embedding import _try_lazy_load_model
                from dualign.services.report_io import build_report, save_report
                from dualign.core import alignment_payload
                from dualign.core.calibration import resolve_alignment_calibration

                model = _try_lazy_load_model()
                resolved = resolve_alignment_calibration(
                    model,
                    calibration_id=getattr(self._align_config, "calibration_id", ""),
                )
                calibration_id = resolved.calibration_id if resolved is not None else ""

                _report = build_report(
                    chapter_id=self._current_entry_id,
                    document_a_path=self._src_path,
                    document_b_path=self._tgt_path,
                    operations=result.all_ops,
                    stats=stats,
                    quality=quality_payload,
                    alignment=alignment_payload(result, calibration_id=calibration_id),
                    provenance=_provenance(model, self._align_config, calibration_id),
                    repair_log=self._repair_state.repair_log,
                )
                save_report(_report, _report_path)
            self._report_file_hash = file_bytes_sha256(_report_path)
            self._report_file_present = os.path.isfile(_report_path)

            # ── 将初始分数载入 ScoreManager 缓存 ──
            if hasattr(self, "_score_mgr"):
                self._score_mgr.invalidate()
                self._load_initial_scores()
                # 对齐完成后注入 scorer（已由 load_file_pair 创建）
                if hasattr(self, "_scorer") and self._scorer is not None:
                    self._score_mgr.set_scorer(self._scorer)

            # ── 退出预览模式，恢复到标准 8 列表格 ──
            if self._preview_active:
                self._status_bar.set_preview_active(False)
                self._preview_active = False
                self._preview_scores = None
                self._switch_table_mode(False)
                # 恢复底部 AI 面板（预览模式入口折叠的）
                saved = getattr(self, "_preview_saved_bottom", None)
                if saved and self._bottom_collapsed:
                    self._toggle_bottom_panel(user_initiated=False)
                self._preview_saved_bottom = None
                # 同步视图模式开关
                self._status_bar.set_view_mode(False)

            self._status_bar.set_view_mode_enabled(True)

            self._ensure_table_in_stacked()
            self._show_table()
            self._refresh()
            self._focus_initial_text_pair()
            self._update_feature_gating()
            # 加载会话后重建 AI 建议表格
            if hasattr(self, "_review"):
                self._review._rebuild_ai_suggestions()
            # 同步底部面板展开/折叠状态
            self._sync_bottom_panel()
        except Exception as e:
            import traceback as _tb

            _tb.print_exc()
            self._show_error("对齐完成", e)
            self._safe_status("✗ 对齐完成时出错")

    def _on_realign(self):
        """重新对齐 — 清除缓存后重新编码 + 对齐（异步，不阻塞 GUI）。"""
        if not self.src_lines or not self.tgt_lines:
            return
        self._cancel_current_load()
        self._invalidate_align_cache()

        from dualign.gui.workers import EncodeThread
        from dualign.services.cli_pipeline import _provenance

        self._status("正在重新计算对齐…")
        QApplication.processEvents()

        src_path = getattr(self, "_src_path", "")
        tgt_path = getattr(self, "_tgt_path", "")
        if src_path and tgt_path:
            self._enc_thread = EncodeThread(
                src_path,
                tgt_path,
                entry_id=self._current_entry_id,
                expected_provenance=_provenance(None, self._align_config),
            )
            self._connect_encode_thread(self._enc_thread, self._load_op_id)
            self._enc_thread.start()
        else:
            self._status("错误: 无法找到源文件路径", "error")

    @staticmethod
    def _action_validation_error(state, action: RepairAction) -> str:
        """Return one user-facing validation error, or an empty string."""
        from dualign.services.repair import RepairService

        ordinal = state.action_ordinal(action)
        ops = RepairService.valid_operations(state, ordinal)
        kind = action.kind
        if kind == "merge" and not ops.get("merge", False):
            return f"关系[{ordinal}] 当前不可合并"
        if kind == "split" and not (
            ops.get("split_tgt", False) or ops.get("split_src", False)
        ):
            return f"关系[{ordinal}] 当前不可拆分"
        if kind in ("edit", "edit_tgt", "edit_src") and not ops.get("edit", False):
            return f"关系[{ordinal}] 当前不可校订"
        if kind == "delete" and not ops.get("delete", False):
            return f"关系[{ordinal}] 当前不可删除"
        if kind in ("placeholder_src", "placeholder_tgt") and not ops.get(
            "placeholder", False
        ):
            return f"关系[{ordinal}] 当前不可插占位符"
        if kind in ("ok", "flag") and not ops.get(kind, False):
            return f"关系[{ordinal}] 操作 {kind} 不可用"
        return ""

    def _apply_actions(
        self,
        actions,
        *,
        auto: bool = False,
        save: bool = True,
        refresh: bool = True,
        show_status: bool = True,
        rebuild_suggestions: bool = True,
    ) -> list[RepairAction]:
        """Apply a sequence as one GUI transaction and one undo step."""
        if self._repair_state is None:
            return []

        original_state = self._repair_state
        applied = []
        affected_ordinals = set()
        content_changed = False
        skipped = []

        for action in actions:
            error = self._action_validation_error(original_state, action)
            if error:
                skipped.append(error)
                continue
            action.data["approvals"] = {"auto"} if auto else {"manual"}
            if not auto and action.source == "auto":
                action.source = "user"
            action_ordinals = original_state.action_ordinals(action)
            applied.append(action)
            affected_ordinals.update(action_ordinals)
            content_changed = content_changed or action.kind in CONTENT_ACTION_KINDS

        if not applied:
            if skipped and show_status:
                self._status(f"⚠ 跳过: {skipped[0]}", "warning")
            return []

        self._undo_stack.append(original_state)
        self._redo_stack.clear()
        self._repair_state = original_state.apply_many(applied)
        self._invalidate_relation_scores(sorted(affected_ordinals))

        if content_changed:
            store = self._repair_state.ai_proposal_store
            for ordinal in affected_ordinals:
                store.reset(self._repair_state.snapshot.relation_id(ordinal))
            if rebuild_suggestions and hasattr(self, "_review"):
                self._review._rebuild_ai_suggestions()

        if save:
            self._save_session()
        if refresh:
            self._refresh()

        if show_status:
            if len(applied) == 1:
                action = applied[0]
                ordinal = self._repair_state.action_ordinal(action)
                labels = {
                    "merge": "已合并",
                    "split": "已拆分",
                    "edit": "已校订",
                    "delete": "已删除",
                    "flag": "已标记异常",
                    "ok": "已审核通过",
                    "placeholder_src": "已插占位符",
                    "placeholder_tgt": "已插占位符",
                }
                label = labels.get(action.kind, f"已{action.kind}")
                self._set_temp_status(f"{label} 关系[{ordinal}]", "success")
            else:
                detail = f"，跳过 {len(skipped)} 条" if skipped else ""
                self._set_temp_status(
                    f"已批量应用 {len(applied)} 条校订{detail}", "success"
                )

        if len(self._undo_stack) == self._undo_stack.maxlen:
            self._status("撤销栈已达上限 (50)，将覆盖最旧记录", "warning")
        return applied

    def _apply_action(self, action: RepairAction, auto: bool = False):
        """Apply one action through the same transaction boundary as batches."""
        return self._apply_actions([action], auto=auto)

    def do_merge(self, ordinal: int):
        """合并当前文本对。"""
        if self._repair_state is None:
            return
        s_idx, t_idx, _sc = self._repair_state.snapshot.original_ops[ordinal]
        self._apply_action(
            self._repair_state.make_action(
                "merge", ordinal, sub_count=max(len(s_idx), len(t_idx))
            )
        )

    def do_split(self, ordinal: int):
        """拆分文本对 — 自动拆分少行的一侧（按硬分割）。

        注意：拆分涉及模型编码，可能耗时。通过状态栏提示用户。
        """
        if self._repair_state is None:
            return
        if not self._ensure_model():
            self._status("拆分需要编码模型，请先完成一次对齐", "warning")
            return
        snapshot = self._repair_state.snapshot
        s_idx, t_idx, _sc = snapshot.original_ops[ordinal]
        ls, lt = len(s_idx), len(t_idx)

        side = "src" if ls <= lt else "tgt"
        self._status(f"拆分关系[{ordinal}] {side} 侧…")
        QApplication.processEvents()

        # 创建嵌入缓存，使 split 产生的新文本被缓存
        from dualign.config import get_embedding_cache_path
        from dualign.services.embedding_cache import EmbeddingCache

        ec = EmbeddingCache(get_embedding_cache_path())
        try:
            attempt = RepairService.try_split(
                self._repair_state, ordinal, side, self._model, cache=ec
            )
        except Exception as exc:
            self._set_flags([ordinal], f"拆分失败：{SPLIT_FAILURE_REALIGN}")
            self._status(
                f"拆分失败：{SPLIT_FAILURE_REALIGN}（{exc}），已标记 [F]",
                "warning",
            )
            return
        finally:
            ec.close()
        if not attempt.succeeded:
            prefix = "拆分需复核" if attempt.needs_review else "拆分失败"
            note = f"{prefix}：{attempt.failure_reason}"
            self._set_flags([ordinal], note)
            self._status(f"{note}，已标记 [F]", "warning")
            return
        self._undo_stack.append(self._repair_state)
        self._repair_state = attempt.state
        action = None
        if self._repair_state.repair_log:
            action = self._repair_state.repair_log[-1]
            action.source = "user"
            action.data["approvals"] = {"manual"}
        split_scores = action.data.get("split_scores", []) if action else []
        self._set_known_relation_scores(ordinal, split_scores)
        self._reset_accepted_proposals([ordinal])
        self._save_session()
        self._refresh()
        # 滚动到拆分后的文本对
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == ordinal:
                self.table.scrollToItem(
                    item, QAbstractItemView.ScrollHint.PositionAtCenter
                )
                break
        if (
            action is not None
            and action.kind == "merge"
            and action.data.get("normalization_plan") == "split"
        ):
            message = f"已归一化关系[{ordinal}] (无新边界，合并为 1:1)"
        else:
            message = f"已拆分关系[{ordinal}] ({side}侧)"
        self._set_temp_status(message, "success")

    def _ensure_model(self):
        """确保 self._model 已加载。返回 True 表示就绪。"""
        if self._model is not None:
            return True
        from dualign.services.embedding import (
            _try_lazy_load_model,
            load_model_for_provider,
        )

        m = _try_lazy_load_model()
        if m is None:
            try:
                m = load_model_for_provider()
            except Exception as e:
                self._status(f"模型加载失败: {e}", "error")
                return False
        self._model = m
        return True

    def do_edit_single(self, ordinal: int):
        """校订单个文本对。优先使用当前修复状态。"""
        if self._repair_state is None:
            return
        ch = self._repair_state.current
        g = ch.group(ordinal)
        snapshot = self._repair_state.snapshot

        # 跨关系合并/校订在当前表格中表现为一个锚点组；对话框的初始
        # 参考和后续编辑必须继承这个组的完整范围，不能退回到锚点关系。
        edit_ordinals = self._repair_state.current_relation_ordinals(ordinal)

        # 初始文本（原始对齐输出，始终不变）
        initial_src = self._repair_state.original_text_lines(edit_ordinals, "src")
        initial_tgt = self._repair_state.original_text_lines(edit_ordinals, "tgt")

        if g is not None and g.rows:
            from dualign.models.marker import is_merge

            if is_merge(g.rows[0].marker):
                # [M]: 当前文本在表格中显示为聚合行，对话框也应一致
                src_lines = [_join([r.src_text for r in g.rows if r.src_text])]
                tgt_lines = [_join([r.tgt_text for r in g.rows if r.tgt_text])]
            else:
                src_lines = [r.src_text for r in g.rows if r.src_text]
                tgt_lines = [r.tgt_text for r in g.rows if r.tgt_text]
        else:
            src_lines = list(initial_src)
            tgt_lines = list(initial_tgt)

        dlg = BlockEditDialog(
            src_lines,
            tgt_lines,
            self,
            initial_src_lines=initial_src,
            initial_tgt_lines=initial_tgt,
        )
        if dlg.exec() == BlockEditDialog.DialogCode.Accepted:
            new_src = dlg.result_src_lines
            new_tgt = dlg.result_tgt_lines
            # 不传 inherited_scores → _apply_info_full 用 osc 原始分 fallback
            action = self._repair_state.make_action(
                "edit",
                ordinal,
                ordinals=edit_ordinals,
                new_src_lines=new_src,
                new_tgt_lines=new_tgt,
            )
            self._apply_action(action)

    def do_ok(self, ordinal: int):
        """审核通过 — 认可当前可见关系组，不做任何文本修改。"""
        if self._repair_state is not None:
            scope = self._repair_state.current_relation_ordinals(ordinal)
            self._apply_action(
                self._repair_state.make_action("ok", ordinal, ordinals=scope)
            )

    def do_flag(self, ordinal: int):
        """打开单个文本对的标记编辑器。"""
        if self._repair_state is None:
            return
        self.do_flag_selected(
            list(self._repair_state.current_relation_ordinals(ordinal))
        )

    def do_flag_selected(self, ordinals: List[int]):
        """为一个或多个文本对编辑标记注释。"""
        if self._repair_state is None:
            return
        selected = list(self._repair_state.current_relation_selection(ordinals))
        flags = [
            self._repair_state.flag_for_relation(
                self._repair_state.snapshot.relation_id(si)
            )
            for si in selected
        ]
        notes = [flag.data.get("note", "") for flag in flags if flag is not None]
        initial_note = (
            notes[0]
            if len(notes) == len(selected) and notes and len(set(notes)) == 1
            else ""
        )
        dialog = FlagEditDialog(
            initial_note,
            self,
            can_delete=bool(notes),
            selection_count=len(selected),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.delete_requested:
            self._remove_flags(selected)
        else:
            self._set_flags(selected, dialog.note)

    def _set_flags(self, ordinals: List[int], note: str):
        """一次历史操作中设置一组标记。"""
        if self._repair_state is None:
            return
        selected = sorted(set(ordinals))
        if not selected:
            return
        self._undo_stack.append(self._repair_state)
        self._redo_stack.clear()
        state = self._repair_state
        for ordinal in selected:
            action = state.make_action("flag", ordinal, note=note, source="user")
            action.data["approvals"] = {"manual"}
            state = state.apply(action)
        self._repair_state = state
        self._save_session()
        self._refresh()
        self._set_temp_status(f"已标记 {len(selected)} 个文本对", "success")

    def _remove_flags(self, ordinals: List[int]):
        """删除一组标记，保留同文本对的其他修复。"""
        if self._repair_state is None:
            return
        selected = sorted(set(ordinals))
        state = self._repair_state
        for ordinal in selected:
            relation_id = state.snapshot.relation_id(ordinal)
            state = state.without_relation_flag(relation_id)
        if state.repair_log == self._repair_state.repair_log:
            return
        self._undo_stack.append(self._repair_state)
        self._redo_stack.clear()
        self._repair_state = state
        self._save_session()
        self._refresh()
        self._set_temp_status(f"已删除 {len(selected)} 个文本对的标记", "info")

    def do_delete(self, ordinal: int):
        """删除文本对。"""
        if self._repair_state is not None:
            scope = self._repair_state.current_relation_ordinals(ordinal)
            self._apply_action(
                self._repair_state.make_action("delete", ordinal, ordinals=scope)
            )

    def _delete_selected_relations(self, ordinals: List[int]):
        """逐个删除选中的关系。"""
        if self._repair_state is None or len(ordinals) < 1:
            return
        ordinals = list(self._repair_state.current_relation_selection(ordinals))
        self._undo_stack.append(self._repair_state)
        self._redo_stack.clear()
        state = self._repair_state
        for si in sorted(ordinals, reverse=True):
            action = state.make_action("delete", si, source="user")
            action.data["approvals"] = {"manual"}
            state = state.apply(action)
        self._repair_state = state
        self._invalidate_relation_scores(ordinals)
        self._reset_accepted_proposals(ordinals)
        self._save_session()
        self._refresh()
        self._set_temp_status(f"已删除 {len(ordinals)} 个文本对", "success")

    def do_placeholder(self, ordinal: int):
        """占位符 — 自动判断方向（1:0 → tgt, 0:1 → src）。"""
        if self._repair_state is None:
            return
        s_idx, t_idx, _sc = self._repair_state.snapshot.original_ops[ordinal]
        ls, lt = len(s_idx), len(t_idx)
        if ls > 0 and lt == 0:
            self._apply_action(
                self._repair_state.make_action("placeholder_tgt", ordinal)
            )
        elif ls == 0 and lt > 0:
            self._apply_action(
                self._repair_state.make_action("placeholder_src", ordinal)
            )

    def do_edit_selected(self, ordinals: List[int]):
        """跨关系手动校订。所有选中文本对合并编辑。"""
        if self._repair_state is None or len(ordinals) < 1:
            return
        selected = list(self._repair_state.current_relation_selection(ordinals))
        capabilities = RepairService.valid_selection_operations(
            self._repair_state, selected
        )
        if not capabilities["edit"]:
            self._status("跨关系校订要求选择连续文本对", "warning")
            return
        ch = self._repair_state.current
        snapshot = self._repair_state.snapshot
        from dualign.models.marker import is_merge

        # 收集所有原文/译文行（优先从当前状态读取）
        all_src: List[str] = []
        all_tgt: List[str] = []
        # 初始文本（原始对齐输出，始终不变）
        init_src: List[str] = []
        init_tgt: List[str] = []
        for si in selected:
            g = ch.group(si)
            s_idx, t_idx, _sc = snapshot.original_ops[si]

            if g is not None and g.rows:
                if is_merge(g.rows[0].marker):
                    all_src.append(_join([r.src_text for r in g.rows if r.src_text]))
                    all_tgt.append(_join([r.tgt_text for r in g.rows if r.tgt_text]))
                else:
                    for r in g.rows:
                        if r.src_text:
                            all_src.append(r.src_text)
                        if r.tgt_text:
                            all_tgt.append(r.tgt_text)
            else:
                for i in s_idx:
                    t = snapshot.src_text(i)
                    if t:
                        all_src.append(t)
                for j in t_idx:
                    t = snapshot.tgt_text(j)
                    if t:
                        all_tgt.append(t)

            # 收集该关系的初始文本（始终从不可变基线读取）
            for i in s_idx:
                t = snapshot.src_text(i)
                if t:
                    init_src.append(t)
            for j in t_idx:
                t = snapshot.tgt_text(j)
                if t:
                    init_tgt.append(t)

        dlg = BlockEditDialog(
            all_src,
            all_tgt,
            self,
            initial_src_lines=init_src,
            initial_tgt_lines=init_tgt,
        )
        if dlg.exec() == BlockEditDialog.DialogCode.Accepted:
            new_src = dlg.result_src_lines
            new_tgt = dlg.result_tgt_lines
            if len(selected) == 1:
                # 不传入 inherited_scores → _apply_info_full 用 osc 原始分 fallback
                # 轮询自动触发异步评分
                action = self._repair_state.make_action(
                    "edit",
                    selected[0],
                    new_src_lines=new_src,
                    new_tgt_lines=new_tgt,
                )
                self._apply_action(action)
            else:
                # 多关系校订：不传 scores，轮询自动评分
                self._undo_stack.append(self._repair_state)
                self._redo_stack.clear()
                self._repair_state = RepairService.repair_multi_edit(
                    self._repair_state,
                    selected,
                    new_src,
                    new_tgt,
                )
                self._invalidate_relation_scores(selected)
                self._reset_accepted_proposals(selected)
                self._save_session()
                self._refresh()

    def _reset_accepted_proposals(self, ordinals: list[int]):
        """重置指定关系中已采纳的 AI 建议为 pending。"""
        if self._repair_state is None or not ordinals:
            return
        store = self._repair_state.ai_proposal_store
        changed = False
        for si in ordinals:
            relation_id = self._repair_state.snapshot.relation_id(si)
            for p in store.get(relation_id):
                if p.status == "accepted":
                    p.reset()
                    changed = True
        if changed and hasattr(self, "_review"):
            self._review._rebuild_ai_suggestions()

    def do_bundle_relations(self, ordinals: List[int]):
        """跨关系合并：将多个关系捆绑为一个文本对。两侧文本均合并。"""
        if self._repair_state is None or len(ordinals) < 2:
            return
        selected = list(self._repair_state.current_relation_selection(ordinals))
        capabilities = RepairService.valid_selection_operations(
            self._repair_state, selected
        )
        if not capabilities["merge"]:
            self._status("跨关系合并要求选择连续文本对", "warning")
            return
        self._undo_stack.append(self._repair_state)
        self._redo_stack.clear()
        self._repair_state = RepairService.repair_bundle_relations(
            self._repair_state, selected
        )
        self._invalidate_relation_scores([selected[0]])
        self._reset_accepted_proposals([selected[0]])
        self._save_session()
        self._refresh()
        self._set_temp_status(
            f"已合并 {len(selected)} 个文本对 → 关系[{selected[0]}]", "success"
        )

    def do_reset(self, ordinal: int):
        """重置当前文本对的修复。"""
        if self._repair_state is None:
            return
        self._undo_stack.append(self._repair_state)
        self._redo_stack.clear()
        scope = self._repair_state.current_relation_ordinals(ordinal)
        relation_ids = [
            self._repair_state.snapshot.relation_id(value) for value in scope
        ]
        self._repair_state = self._repair_state.reset_relations(relation_ids)
        self._invalidate_relation_scores(list(scope))
        self._reset_accepted_proposals(list(scope))
        self._save_session()
        self._refresh()
        self._set_temp_status(f"已重置关系[{ordinal}]", "info")

    def _apply_ai_action(self, action: RepairAction):
        """建议动作的受控入口：按其最终责任来源执行修复。

        人工点击应用时，ReviewController 已把动作采纳为 user source；
        自动应用时则保留 ai/auto source。内容动作本身即构成审批。
        """
        if self._repair_state is None:
            return
        ordinal = self._repair_state.action_ordinal(action)
        self._apply_action(action, auto=action.source != "user")
        self._set_temp_status(
            f"校订建议已应用: 关系[{ordinal}] {action.kind}", "success"
        )

    def _on_ai_repair_chapter(self):
        """菜单项：AI 一键校订当前章节。"""
        try:
            if hasattr(self, "_review"):
                if not getattr(self, "_batch_connected", False):
                    self._review.batch_finished.connect(self._on_ai_batch_finished)
                    self._review.ai_error.connect(self._on_ai_review_status)
                    self._batch_connected = True
            self._review.analyze_chapter_batch()
            self._status("AI 校订中...", "info")
        except Exception as e:
            self._show_error("AI 校订本章", e)

    def _on_ai_batch_finished(self, result):
        """Persist the Agent's explicit completion state and refresh the GUI."""
        note = result.note
        if result.pending_ids:
            progress = (
                f"已审 {len(result.reviewed_ids)}，"
                f"剩余 {len(result.pending_ids)}: {list(result.pending_ids[:15])}"
            )
            note = f"{progress}；{note}" if note else progress
        self._set_ai_review(
            result.status,
            note,
            details={
                "reviewed_count": len(result.reviewed_ids),
                "pending_count": len(result.pending_ids),
                "pending_ids": list(result.pending_ids),
                "turns": result.turns,
                "forced": result.forced,
                "model": result.model_name,
                "prompt_sha256": result.prompt_sha256,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
            },
        )
        self._save_session()
        if result.status == "cancelled":
            self._status("AI 校订已停止", "info")
        elif result.is_complete:
            self._status("AI 校订完成", "success")
        else:
            self._status(f"AI 校订未完成：{note}", "warning")
        # 刷新主表格以反映修复后的最新状态
        self._refresh()
        self._sync_bottom_panel()

    def _on_ai_review_status(self, status_or_error: str):
        """AI 校订异常/跳过 → 写入 ai_review 状态。"""
        if status_or_error == "skipped":
            self._set_ai_review("skipped", "无待审核异常")
        else:
            self._set_ai_review("error", status_or_error)

    def _set_ai_review(self, status: str, note: str = "", details=None):
        """写入 AI 审校状态到 report.json 的 ai_review 字段。"""
        try:
            from dualign.services.report_io import set_ai_review

            self._write_report(
                lambda path: set_ai_review(
                    path, status=status, note=note, details=details
                )
            )
        except Exception:
            import traceback as _tb

            _tb.print_exc()

    def _on_batch_discover(self):
        """批量文件对发现 — 对话框 → FilePairMatcher → 导入队列。"""
        from dualign.gui.batch_discovery import BatchDiscoveryDialog

        dlg = BatchDiscoveryDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.selected_pairs()
        if not selected:
            return

        added = 0
        for pair in selected:
            self._workspace.add_to_queue(
                FileQueueItem(
                    label=pair.label or pair.entry_id,
                    src_path=pair.src_path,
                    tgt_path=pair.tgt_path,
                )
            )
            added += 1

        self._safe_status(f"已导入 {added} 个文件对")
        # 自动加载第一个
        if selected and self._workspace._queue:
            first = self._workspace._queue[0]
            self.load_file_pair(first.src_path, first.tgt_path, first.label)

    def _on_welcome_recent(self, label: str, src_path: str, tgt_path: str):
        """欢迎页最近文件对点击 → 加载。"""
        if not src_path or not tgt_path:
            return
        self._workspace.add_to_queue(
            FileQueueItem(label=label, src_path=src_path, tgt_path=tgt_path)
        )
        self.load_file_pair(src_path, tgt_path, label)

    def _on_open_agent_config(self):
        """打开 Agent 配置对话框。"""
        from dualign.gui.dialogs import AgentConfigDialog

        dlg = AgentConfigDialog(self)
        dlg.config_changed.connect(self._on_agent_config_changed)
        dlg.exec()

    def _on_agent_config_changed(self):
        """Agent 配置变更后刷新 AI 面板和状态指示灯。"""
        from dualign.providers import active_repair_agent

        agent = active_repair_agent()
        if agent and agent.agent_id == "ollama_local":
            self._review.set_backend("ollama")
        else:
            self._review.set_backend("deepseek")
        # 刷新状态和功能阶梯
        self._refresh_status_dots()
        self._safe_status("Agent 配置已更新")

    def _on_reset_all(self):
        """重置所有修复。"""
        if self._repair_state is None:
            return
        self._safe_status("重置修复中…")
        QApplication.processEvents()
        self._undo_stack.append(self._repair_state)
        self._repair_state = self._repair_state.reset()
        all_ordinals = [g.ordinal for g in self._repair_state.current.groups]
        self._invalidate_relation_scores(all_ordinals)
        self._reset_accepted_proposals(all_ordinals)
        self._refresh()
        self._save_session()
        self._safe_status("已重置所有修复")

    def _on_strategy_changed(self, idx: int):
        strategies = ["minimal", "src", "tgt"]
        self._strategy = strategies[idx] if 0 <= idx < 3 else "src"

    def _on_auto_repair(self):
        """一键修复 — 通过后台线程执行，避免阻塞主线程。"""
        if self._repair_state is None:
            return

        # Re-read the visible selection at the execution boundary.  This keeps
        # the strategy matrix correct even if a report reload or settings
        # restore occurred without emitting currentIndexChanged.
        self._on_strategy_changed(self._review.get_strategy_index())

        if self._strategy == "src" and not self._ensure_model():
            self._safe_status("该策略需要编码模型，请先完成一次对齐")
            return

        # 文档适用性已由 mdl-v1 在生成路径前判断；自动修复不得再用
        # legacy 锚点密度、gap 比例或合并上限推翻该决定。
        self._safe_status("一键修复中…")
        QApplication.processEvents()

        from dualign.gui.workers import AutoRepairWorker

        running_worker = getattr(self, "_auto_repair_worker", None)
        if running_worker is not None and running_worker.isRunning():
            self._safe_status("自动修复仍在进行中")
            return

        # 预先保存当前状态用于撤销
        self._undo_stack.append(self._repair_state)

        # 创建嵌入缓存，使自动修复中的 split 产生的新文本被缓存
        from dualign.config import get_embedding_cache_path
        from dualign.services.embedding_cache import EmbeddingCache

        ec = EmbeddingCache(get_embedding_cache_path())

        self._auto_repair_worker = AutoRepairWorker(
            self._repair_state, self._strategy, model=self._model, cache=ec
        )
        self._auto_repair_worker.status_signal.connect(lambda msg: self._status(msg))
        self._auto_repair_worker.finished_signal.connect(self._on_auto_repair_done)
        self._auto_repair_worker.error_signal.connect(self._on_worker_error)
        worker = self._auto_repair_worker
        worker.finished.connect(
            lambda finished_worker=worker: self._release_auto_repair_worker(
                finished_worker
            )
        )
        self._auto_repair_worker.start()

    def _release_auto_repair_worker(self, worker):
        if getattr(self, "_auto_repair_worker", None) is worker:
            self._auto_repair_worker = None

    def _on_auto_repair_done(self, result):
        """一键修复完成 → 更新状态并刷新 UI。"""
        self._repair_state = result
        all_ordinals = [g.ordinal for g in self._repair_state.current.groups]
        self._invalidate_relation_scores(all_ordinals)
        self._save_session()
        self._refresh()
        n_actions = len(result.repair_log)
        self._status(f"一键修复完成 ({n_actions} 个操作)", "success")

    def _recover_pair_save_transactions(self):
        """Roll back any interrupted native save before files are opened."""
        from dualign.services.pair_save import recover_pending_pair_saves

        messages = recover_pending_pair_saves()
        for message in messages:
            self._status(message, "warning")

    def _alignment_provenance(self) -> dict:
        """Return reproducibility metadata, deliberately excluding secrets."""
        from dualign import __version__
        from dualign.core import ALIGN_CORE_VERSION
        from dualign.providers import ProviderManager
        from dualign.services.alignment_io import build_alignment_provenance

        ProviderManager.load()
        provider = ProviderManager.active()
        return build_alignment_provenance(
            tool_version=__version__,
            algorithm_version=ALIGN_CORE_VERSION,
            align_config=getattr(self, "_align_config", None),
            embedding_provider=getattr(provider, "provider_id", ""),
            embedding_model=getattr(provider, "model_name", ""),
            embedding_instruction=getattr(provider, "instruction_text", ""),
            alignment_origin=getattr(self, "_align_stats", {}).get(
                "alignment_origin", "algorithm"
            ),
        )

    def _snapshot_alignment_pair(self, result=None):
        """Create the native baseline represented by the current GUI snapshot."""
        if self._repair_state is None:
            raise ValueError("请先加载并对齐两个文档")
        from dualign import __version__
        from dualign.services.alignment_io import create_alignment_pair

        stats = getattr(result, "stats", {}) if result is not None else {}
        confirmed = set(stats.get("formal_confirmed_ops", ()))
        pair_id = self._current_entry_id or Path(self._report_path).stem
        return create_alignment_pair(
            pair_id=pair_id,
            document_a_path=self._src_path,
            document_b_path=self._tgt_path,
            report_path=self._report_path,
            operations=self._repair_state.snapshot.original_ops,
            relation_ids=self._repair_state.snapshot.relation_ids,
            document_a_id=getattr(self, "_document_a_id", ""),
            document_b_id=getattr(self, "_document_b_id", ""),
            language_a=getattr(self, "_language_a", ""),
            language_b=getattr(self, "_language_b", ""),
            confirmed_operations=confirmed,
            tool_version=__version__,
            provenance=self._alignment_provenance(),
        )

    def _initialize_pair_editing_state(self, result):
        """Bind the immutable report snapshot to the internal editing graph."""
        from dualign.models.pair_editing import PairEditingState

        pair = self._snapshot_alignment_pair(result)
        text_a = Path(self._src_path).read_text(encoding="utf-8-sig")
        text_b = Path(self._tgt_path).read_text(encoding="utf-8-sig")
        self._pair_base_state = PairEditingState.from_alignment_pair(
            pair, text_a, text_b
        )

    def _reload_current_pair(self):
        label = getattr(getattr(self, "_current_entry", None), "label", "")
        self.load_file_pair(
            self._src_path,
            self._tgt_path,
            label,
            report_path=self._report_path,
            document_a_id=getattr(self, "_document_a_id", ""),
            document_b_id=getattr(self, "_document_b_id", ""),
            language_a=getattr(self, "_language_a", ""),
            language_b=getattr(self, "_language_b", ""),
        )

    def _on_save_alignment(self):
        """Save the replayable work state without touching either document."""
        try:
            if not self._save_session(raise_on_error=True):
                raise ValueError("工作报告不存在，请先完成对齐")
            saved = self._report_path
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "保存工作报告失败", str(exc))
            return False
        self._set_temp_status(f"已保存工作报告: {saved}", "success")
        return True

    def _on_apply_confirmed_changes(self):
        """Review and atomically solidify configured effects."""
        if self._repair_state is None or self._pair_base_state is None:
            QMessageBox.information(self, "固化修改", "请先加载并对齐两个文档。")
            return
        if not self._on_save_alignment():
            return
        from dualign.services.solidify import build_solidification_plan

        plan = build_solidification_plan(
            self._pair_base_state,
            self._repair_state.repair_log,
            self._current_solidify_policy(),
        )
        if not plan.has_changes:
            QMessageBox.information(
                self,
                "没有待固化的修改",
                "当前配置没有选中可写入正文的修复；未选中的操作仍保留在工作报告中。",
            )
            return

        from dualign.gui.dialogs import SolidifyReviewDialog

        dialog = SolidifyReviewDialog(plan, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        from dualign.services.pair_save import save_pair_transaction
        from dualign.services.realignment import rebuild_alignment
        from dualign.services.report_io import load_report

        from dualign.gui.task_progress import TaskProgress, run_modal_task

        def solidify(token, progress):
            def report_progress(message, cancellable):
                progress(TaskProgress(message, cancellable=cancellable))

            return save_pair_transaction(
                plan.solidified,
                document_a_path=self._src_path,
                document_b_path=self._tgt_path,
                report_path=self._report_path,
                report=load_report(self._report_path),
                expected_report_sha256=self._report_file_hash,
                expected_report_exists=self._report_file_present,
                remaining_repair_log=plan.remaining_actions,
                solidification_policy=plan.policy.to_dict(),
                applied_repairs=plan.applied,
                changed_relation_ids=plan.changed_relation_ids,
                alignment_runner=lambda document_a, document_b: rebuild_alignment(
                    document_a,
                    document_b,
                    config=self._align_config,
                    cancellation_token=token,
                ),
                cancellation_token=token,
                progress_callback=report_progress,
            )

        outcome = run_modal_task(
            self,
            title="正在固化修改",
            message="正在准备固化后的文档…",
            operation=solidify,
        )
        if outcome.cancelled:
            self._set_temp_status("已停止固化，未开始的修改未写入", "info")
            return
        if outcome.error:
            QMessageBox.critical(self, "固化修改失败", outcome.error)
            return
        result = outcome.result

        self._report_file_hash = result.report_sha256
        self._report_file_present = True
        # ── 固化成功后立即同步内存修复状态与磁盘事务结果 ──
        # _reload_current_pair() 是异步加载，窗口期内任何 _save_session()
        # 都会用旧的 repair_log / ai_proposals 覆盖已清空的报告，导致
        # 已删除/已合并的行重新出现在 AI 建议列表中。
        # The report now belongs to a rebuilt baseline.  Do not leave the old
        # snapshot live during the asynchronous reload: an autosave in that
        # window could otherwise write old anchors back into the new report.
        self._repair_state = None
        self._score_cache.clear()
        QMessageBox.information(
            self,
            "已固化修改",
            "正文与重建后的工作报告已作为一个可恢复事务写入。\n"
            f"已固化 {len(plan.applied)} 条，工作报告保留 "
            f"{len(plan.remaining_actions)} 条，正在重新加载。",
        )
        self._reload_current_pair()

    def _current_solidify_policy(self):
        from dualign.gui.settings import KEY_SOLIDIFY_TYPES
        from dualign.services.solidify import DEFAULT_SOLIDIFY_TYPES, SolidifyPolicy

        enabled = DualignConfig.instance().get(
            KEY_SOLIDIFY_TYPES, list(DEFAULT_SOLIDIFY_TYPES)
        )
        return SolidifyPolicy(frozenset(enabled))

    def _on_solidify_settings(self):
        from dualign.gui.dialogs import SolidifyPolicyDialog
        from dualign.gui.settings import KEY_SOLIDIFY_TYPES

        dialog = SolidifyPolicyDialog(self._current_solidify_policy(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        cfg = DualignConfig.instance()
        cfg.set(KEY_SOLIDIFY_TYPES, dialog.policy.to_dict()["include"])
        cfg.save()
        self._set_temp_status("固化修改设置已保存", "info")

    def _batch_solidify_targets(self):
        from dualign.services.cli_pipeline import default_report_path
        from dualign.services.solidify import SolidifyTarget

        entries = getattr(self, "_entries", None)
        if isinstance(entries, list) and entries:
            candidates = [
                (
                    getattr(entry, "label", ""),
                    getattr(entry, "document_a_path", ""),
                    getattr(entry, "document_b_path", ""),
                    getattr(entry, "report_path", ""),
                )
                for entry in entries
            ]
        else:
            candidates = [
                (item.label, item.src_path, item.tgt_path, "")
                for item in self._workspace.queue_items()
            ]

        targets = []
        for label, path_a, path_b, report in candidates:
            if not path_a or not path_b:
                continue
            targets.append(
                SolidifyTarget(
                    label or Path(path_a).name,
                    path_a,
                    path_b,
                    report or str(default_report_path(path_a)),
                )
            )
        return targets

    def _on_batch_solidify(self):
        """Preview and solidify every file pair currently loaded in Dualign."""

        from dualign.services.solidify import (
            SOLIDIFY_TYPE_LABELS,
            apply_batch_solidification,
            plan_batch_solidification,
        )
        from dualign.gui.task_progress import TaskProgress, run_modal_task

        targets = self._batch_solidify_targets()
        if not targets:
            QMessageBox.information(self, "批量固化修改", "当前没有可处理的文件对。")
            return
        try:
            if self._repair_state is not None:
                self._save_session(raise_on_error=True)
            policy = self._current_solidify_policy()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "批量固化计划失败", str(exc))
            return

        def plan_operation(token, progress):
            return plan_batch_solidification(
                targets,
                policy,
                cancellation_token=token,
                progress_callback=lambda current, total, target: progress(
                    TaskProgress(f"正在检查 {target.label}", current, total)
                ),
            )

        plan_outcome = run_modal_task(
            self,
            title="准备批量固化",
            message="正在检查工作报告…",
            operation=plan_operation,
        )
        if plan_outcome.cancelled:
            self._set_temp_status("已停止准备批量固化", "info")
            return
        if plan_outcome.error:
            QMessageBox.critical(self, "批量固化计划失败", plan_outcome.error)
            return
        batch = plan_outcome.result

        if not batch.ready:
            errors = [issue for issue in batch.skipped if issue.error]
            detail = ""
            if errors:
                detail = "\n\n" + "\n".join(
                    f"{issue.target.label}: {issue.reason}" for issue in errors[:10]
                )
            QMessageBox.information(
                self,
                "没有可固化文件对",
                f"检查 {len(targets)} 对，均无匹配修改或报告无效。{detail}",
            )
            return

        labels = [
            SOLIDIFY_TYPE_LABELS[key]
            for key in SOLIDIFY_TYPE_LABELS
            if key in batch.policy.enabled
        ]
        effects = "\n".join(
            f"  · {SOLIDIFY_TYPE_LABELS[key]}：{count} 处"
            for key, count in batch.effect_counts.items()
            if count
        )
        reply = QMessageBox.question(
            self,
            "确认批量固化",
            "即将修改初始文档并重建工作报告。每个文件对使用独立的可恢复事务。\n\n"
            f"固化范围：{'、'.join(labels) or '无'}\n"
            f"可固化：{len(batch.ready)} 对\n"
            f"跳过：{len(batch.skipped)} 对\n"
            f"修复动作：{batch.action_count} 条\n"
            f"影响文档 A：{batch.document_a_count} 对\n"
            f"影响文档 B：{batch.document_b_count} 对\n\n"
            f"操作分布：\n{effects}\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def apply_operation(token, progress):
            def report_progress(current, total, target, phase, cancellable):
                message = (
                    f"正在固化 {target.label}"
                    if phase == "prepare"
                    else f"{target.label}：{phase}"
                )
                progress(TaskProgress(message, current - 1, total, cancellable))

            return apply_batch_solidification(
                batch,
                cancellation_token=token,
                progress_callback=report_progress,
            )

        apply_outcome = run_modal_task(
            self,
            title="正在批量固化",
            message="正在固化文档…",
            operation=apply_operation,
        )
        if apply_outcome.cancelled:
            self._set_temp_status("批量固化已停止；已完成的文件对保持有效", "info")
            return
        if apply_outcome.error:
            QMessageBox.critical(self, "批量固化失败", apply_outcome.error)
            return
        result = apply_outcome.result
        succeeded_reports = {
            os.path.normcase(str(Path(target.report_path).resolve()))
            for target in result.succeeded
        }
        current_report = os.path.normcase(str(Path(self._report_path).resolve()))
        if current_report in succeeded_reports:
            self._repair_state = None
            self._score_cache.clear()
            self._reload_current_pair()

        if result.cancelled:
            self._set_temp_status(
                f"批量固化已停止；已安全完成 {len(result.succeeded)} 对", "info"
            )
            return

        detail = ""
        if result.failed:
            detail = "\n\n失败：\n" + "\n".join(
                f"{issue.target.label}: {issue.reason}" for issue in result.failed[:10]
            )
        QMessageBox.information(
            self,
            "批量固化完成",
            f"成功 {len(result.succeeded)} 对；失败 {len(result.failed)} 对；"
            f"跳过 {len(result.skipped)} 对。{detail}",
        )

    def _on_undo(self):
        """撤销 — 恢复位置 + 同步 AiProposalStore。

        撤销一个操作时，对应关系的 AI 建议应从 accepted 回退到 pending，
        避免建议显示"已采纳"但修复已被回退的不一致状态。
        """
        if self._undo_stack:
            self._undo_ordinal_save = self._review._current_ordinal()
            # 找出将被撤销的操作涉及的关系
            old_state = self._repair_state
            self._redo_stack.append(old_state)
            self._repair_state = self._undo_stack.pop()
            # 同步 AiProposalStore：被撤销的操作回退为 pending
            undone_ordinals = self._sync_proposals_on_undo(
                old_state, self._repair_state
            )
            # 标记受影响的关系失效
            if undone_ordinals:
                self._invalidate_relation_scores(undone_ordinals)
            self._refresh()
            # 恢复撤销前的位置
            saved = self._undo_ordinal_save
            self._undo_ordinal_save = None
            if saved is not None:
                for i, anomaly in enumerate(self._anomalies):
                    if saved in anomaly.ordinals:
                        self._review.go(i, scroll_to=True)
                        break
            if undone_ordinals:
                self._review._rebuild_ai_suggestions()
            self._set_temp_status(
                f"已撤销 (共 {len(self._repair_state.repair_log)} 个操作)", "info"
            )
            self._save_session()

    def _sync_proposals_on_undo(
        self, old_state: RepairState, new_state: RepairState
    ) -> List[int]:
        """撤销后同步 AiProposalStore：找出被撤销操作对应的关系，回退为 pending。

        Returns: 被回退的关系序号列表。
        """
        undone_ordinals: Set[int] = set()
        old_log = old_state.repair_log
        new_log = new_state.repair_log
        # 找出 old 中有但 new 中没有的 action
        old_set = {(a.relation_ids, a.kind, a.timestamp) for a in old_log}
        new_set = {(a.relation_ids, a.kind, a.timestamp) for a in new_log}
        undone = old_set - new_set
        for relation_ids, kind, _ts in undone:
            if kind in (
                "edit",
                "edit_tgt",
                "edit_src",
                "merge",
                "merge_src",
                "merge_tgt",
                "split",
                "delete",
                "flag",
                "ok",
                "placeholder_src",
                "placeholder_tgt",
            ):
                store = new_state.ai_proposal_store
                for relation_id in relation_ids:
                    store.reset(relation_id)
                    undone_ordinals.add(new_state.snapshot.operation_index(relation_id))
        return list(undone_ordinals)

    def _on_redo(self):
        """恢复 — 重做被撤销的操作。"""
        if self._redo_stack:
            self._undo_stack.append(self._repair_state)
            self._repair_state = self._redo_stack.pop()
            all_ordinals = [g.ordinal for g in self._repair_state.current.groups]
            self._invalidate_relation_scores(all_ordinals)
            self._refresh()
            self._set_temp_status(
                f"已恢复 (共 {len(self._repair_state.repair_log)} 个操作)", "info"
            )

    def _on_open_files(self):
        """打开文件对（记忆上次打开的路径）。"""
        cfg = DualignConfig.instance()
        cfg.load()
        last_dir = cfg.get(KEY_LAST_OPEN_DIR, "")

        src_path, _ = QFileDialog.getOpenFileName(
            self, "选择文档 A", last_dir, "Markdown (*.md);;Text (*.txt);;All (*)"
        )
        if not src_path:
            return
        last_dir = str(Path(src_path).parent)
        tgt_path, _ = QFileDialog.getOpenFileName(
            self, "选择文档 B", last_dir, "Markdown (*.md);;Text (*.txt);;All (*)"
        )
        if tgt_path:
            self._save_last_open_dir(str(Path(tgt_path).parent))
            self.load_file_pair(src_path, tgt_path)

    def _save_last_open_dir(self, path: str):
        """将路径写入配置以供下次复用。"""
        try:
            cfg = DualignConfig.instance()
            cfg.load()
            cfg.set(KEY_LAST_OPEN_DIR, path)
            cfg.save()
        except Exception:
            import traceback as _tb

            _tb.print_exc()

    def _on_placeholder(self):
        ordinal = self._review._current_ordinal()
        if ordinal is not None:
            self.do_placeholder(ordinal)

    def _session_path(self) -> str:
        """Return the sole JSON work-report path."""
        return getattr(self, "_report_path", "")

    def _invalidate_align_cache(self):
        """Remove the complete stale report before an explicit realignment."""
        path = self._session_path()
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                import traceback as _tb

                _tb.print_exc()
        self._report_file_hash = ""
        self._report_file_present = False
        npy_path = path.replace(".report.json", ".sim.npy")
        if os.path.isfile(npy_path):
            try:
                os.remove(npy_path)
            except OSError:
                pass

    def _write_report(self, writer) -> bool:
        """Apply one guarded report update and refresh its observed identity."""

        path = self._session_path()
        if not path:
            return False
        present = os.path.isfile(path)
        expected_present = getattr(self, "_report_file_present", False)
        expected_hash = getattr(self, "_report_file_hash", "")
        if file_identity_changed(
            path,
            expected_exists=expected_present,
            expected_sha256=expected_hash,
        ):
            raise ValueError("工作报告在打开后被外部修改，已拒绝覆盖")
        if not present:
            return False
        writer(path)
        self._report_file_hash = file_bytes_sha256(path)
        self._report_file_present = True
        return True

    def _save_session(self, *, raise_on_error: bool = False) -> bool:
        """Autosave repair, AI and score state into the work report."""
        if self._repair_state is None:
            return False
        from dualign.services.report_io import update_report

        def mutate(report):
            report["repair_log"] = [
                action.to_dict() for action in self._repair_state.repair_log
            ]
            report["ai_proposals"] = self._repair_state.ai_proposal_store.to_dict()
            report["scores"] = self._score_cache.to_dict()

        try:
            return self._write_report(lambda path: update_report(path, mutate))
        except (OSError, ValueError) as exc:
            if raise_on_error:
                raise
            self._safe_status(f"工作报告未保存: {exc}")
            return False

    def _load_session(self) -> Optional[RepairState]:
        """Restore repair actions and AI state from the current report."""
        path = self._session_path()
        if not path or not os.path.isfile(path) or self._alignment_snapshot is None:
            return None
        from dualign.models.action import AiProposalStore, RepairAction
        from dualign.services.report_io import (
            ReportError,
            load_report,
            relation_ids_from_report,
            report_matches_documents,
        )

        try:
            data = load_report(path)
        except ReportError:
            return None
        if not report_matches_documents(data, self._src_path, self._tgt_path):
            return None
        try:
            self._alignment_snapshot = AlignmentSnapshot.from_alignment(
                self._alignment_snapshot.ops_list,
                self._alignment_snapshot.src_list,
                self._alignment_snapshot.tgt_list,
                relation_ids_from_report(data),
            )
        except (ReportError, ValueError):
            return None
        log = [RepairAction.from_dict(item) for item in data.get("repair_log", [])]
        store = AiProposalStore.from_dict(data.get("ai_proposals", {}))

        if hasattr(self, "_score_cache"):
            from dualign.models.score_cache import RelationScoreCache

            self._score_cache = RelationScoreCache.from_dict(
                data.get("scores"), self._alignment_snapshot.relation_ids
            )

        return RepairState(self._alignment_snapshot, log, store)

    def _show_error(self, context: str, error: Exception):
        """统一的异常报告：终端 traceback + 弹窗 + 状态栏。

        所有未捕获异常都通过此方法输出，方便用户反馈和开发者定位。
        """
        import traceback as _tb
        from dualign.diagnostics import write_crash_report

        tb = _tb.format_exc()
        crash_path = write_crash_report(context, tb)
        # 1) 终端输出完整 traceback
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[{context}] 未捕获异常:", file=sys.stderr)
        print(tb, file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)

        # 2) 弹窗显示摘要
        destination = (
            f"完整 traceback 已写入：\n{crash_path}"
            if crash_path
            else "完整 traceback 已输出到标准错误。"
        )
        msg = f"{context}\n\n{error}\n\n{destination}"
        QMessageBox.critical(self, f"异常 — {context}", msg)

        # 3) 状态栏
        self._safe_status(f"✗ {context}: {error}")

    def _safe_status(self, msg: str):
        """安全设置状态栏文本，忽略 C++ 对象已删除的 RuntimeError。

        同时推送到 StatusBar 的瞬态文本列。
        """
        try:
            if hasattr(self, "_status_bar") and self._status_bar is not None:
                self._status_bar.set_message(msg)
        except RuntimeError:
            pass

    def _set_temp_status(self, msg: str, role: str = "info"):
        """记录操作日志（仅写 LogPanel，不再推送 StatusBar）。"""
        if hasattr(self, "_log_panel") and self._log_panel is not None:
            self._log_panel.log(msg, role)

    def _on_worker_error(self, context: str, tb_str: str):
        """后台工作线程异常回调。已在终端输出完整 traceback，此处弹窗通知。"""
        from dualign.diagnostics import write_crash_report

        crash_path = write_crash_report(context, tb_str or context)
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[后台线程异常] {context}", file=sys.stderr)
        if tb_str:
            print(tb_str, file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        QMessageBox.critical(
            self,
            f"后台任务异常 — {context}",
            f"{context}\n\n"
            + (
                f"完整 traceback 已写入：\n{crash_path}"
                if crash_path
                else "完整 traceback 已输出到标准错误。"
            ),
        )
        self._safe_status(f"✗ 后台异常: {context}")
        if hasattr(self, "_status_bar") and self._status_bar is not None:
            self._status_bar.set_view_mode_enabled(True)
            self._status_bar.set_preview_active(True, phase="准备失败")

    def _on_show_all_relations(self):
        """空状态页的「查看全部文本对」按钮回调。

        取消勾选筛选面板的「仅显示异常文本对」复选框并触发刷新，
        使表格切换到显示所有文本对的模式。
        """
        if hasattr(self, "_filter_panel"):
            self._filter_panel._anomaly_only_cb.setChecked(False)
            self._filter_panel._sync_anomaly_only_controls()
            self._filter_panel.filter_changed.emit()
        if hasattr(self, "_table_stack"):
            self._table_stack.setCurrentIndex(0)

    # ═══════════════════════════════════════════════════════════════
    # 查看文件 — 用系统默认编辑器打开相关文件
    # ═══════════════════════════════════════════════════════════════

    def _view_file_safe(self, path: str, label: str) -> None:
        """安全地打开文件（存在时用系统默认程序，不存在时弹提示）。"""
        if not path or not os.path.isfile(path):
            QMessageBox.information(
                self,
                "文件未找到",
                f"文件不存在：{label}\n\n{path or '（路径为空）'}\n\n"
                f"请先加载文件对并完成对齐导出。",
            )
            return
        try:
            os.startfile(path)
            self._set_temp_status(f"已打开 {label}", "info")
        except Exception as e:
            QMessageBox.warning(
                self,
                "打开失败",
                f"无法打开文件：{label}\n\n{path}\n\n错误：{e}",
            )

    def _on_view_source(self):
        """打开文档 A。"""
        path = getattr(self, "_src_path", "")
        self._view_file_safe(path, "文档 A")

    def _on_view_target(self):
        """打开文档 B。"""
        path = getattr(self, "_tgt_path", "")
        self._view_file_safe(path, "文档 B")

    def _on_view_alignment(self):
        """打开当前工作报告。"""
        self._view_file_safe(getattr(self, "_report_path", ""), "工作报告")
