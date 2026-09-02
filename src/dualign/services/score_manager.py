"""
Dualign — ScoreManager: 统一评分管理器

评分粒度：每对 (ordinal, sub) 独立评分。
异步 + 防抖 + 轮询自愈 + 信号驱动局部刷新。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import Qt, QObject, QTimer, Signal, Slot

from dualign.services.similarity import SimilarityScorer

logger = logging.getLogger(__name__)

SCORE_STATE_PENDING = "pending"
SCORE_STATE_LOADING = "loading"
SCORE_STATE_READY = "ready"
SCORE_STATE_FAILED = "failed"

# ═══════════════════════════════════════════════════════════════
# 内部条目
# ═══════════════════════════════════════════════════════════════


class _ScoreEntry:
    __slots__ = ("score", "state", "timestamp", "request_seq")

    def __init__(
        self,
        score: Optional[float] = None,
        state: str = SCORE_STATE_PENDING,
        request_seq: int = 0,
    ):
        self.score = score
        self.state = state
        self.timestamp = time.time()
        self.request_seq = request_seq


# ═══════════════════════════════════════════════════════════════
# ScoreWorker
# ═══════════════════════════════════════════════════════════════


class ScoreWorker(QObject):
    finished = Signal(object, int)
    error = Signal(str, int)
    _trigger = Signal(object, int)

    def __init__(self, scorer: SimilarityScorer, parent=None):
        super().__init__(parent)
        self._scorer = scorer
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @Slot(object, int)
    def run(self, pairs: list, request_seq: int):
        """Execute one immutable queued request.

        The previous worker stored ``pairs`` and ``request_seq`` on itself.
        Assigning a new job while the old scorer was blocked could therefore
        relabel the old result as the new request.  Signal arguments are copied
        into the queued Qt event and cannot be overwritten by a later job.
        """

        if self._cancelled or not pairs:
            self.finished.emit({}, request_seq)
            return
        try:
            keys = [p[0] for p in pairs]
            src_texts = [p[1] for p in pairs]
            tgt_texts = [p[2] for p in pairs]

            scores = self._scorer.score_pairs(src_texts, tgt_texts)

            if self._cancelled:
                self.finished.emit({}, request_seq)
                return

            results = {}
            for i, k in enumerate(keys):
                results[k] = float(scores[i]) if i < len(scores) else 0.0
            self.finished.emit(results, request_seq)
        except Exception as e:
            logger.error(f"ScoreWorker 评分失败: {e}", exc_info=True)
            self.error.emit(str(e), request_seq)


# ═══════════════════════════════════════════════════════════════
# ScoreManager
# ═══════════════════════════════════════════════════════════════


class ScoreManager(QObject):
    """以 (ordinal, sub) 为粒度的统一评分管理器。"""

    score_updated = Signal(int, int, float)  # (ordinal, sub, score)
    status_changed = Signal(int, int, str)  # (ordinal, sub, state)
    flat_batch_ready = Signal(int, object)

    _DEBOUNCE_MS = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict = {}  # (ordinal, sub) -> _ScoreEntry
        self._scorer: Optional[SimilarityScorer] = None
        self._text_provider = None  # callable(ordinal, sub) -> (src, tgt) or None

        self._worker: Optional[ScoreWorker] = None
        self._worker_thread = None
        self._request_seq: int = 0
        self._pending_req: dict = {}  # {(ordinal, sub): latest_seq}

        self._flat_requests: dict[int, int] = {}  # request_seq -> preview batch id

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(self._DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._flush_pending)
        self._debounced_pairs: list = []

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll)

        self._flush_in_progress = False

    # ═════════════════════════════════════════════════════════
    # 公开 API — 以 (ordinal, sub) 为参数
    # ═════════════════════════════════════════════════════════

    def set_scorer(self, scorer: Optional[SimilarityScorer]):
        self._scorer = scorer

    @property
    def has_scorer(self) -> bool:
        return self._scorer is not None

    def get_score_state(self, ordinal: int, sub: int = 0) -> tuple:
        """返回 (score_or_None, state_str)。"""
        key = (ordinal, sub)
        entry = self._cache.get(key)
        if entry is None:
            return (None, SCORE_STATE_PENDING)
        return (entry.score, entry.state)

    def set_ready_score(self, ordinal: int, sub: int, score: float):
        self._cache[(ordinal, sub)] = _ScoreEntry(score=score, state=SCORE_STATE_READY)

    def set_text_provider(self, provider):
        """provider(ordinal, sub) -> (src_text, tgt_text) or None"""
        self._text_provider = provider

    def start_polling(self):
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def poll_now(self):
        self._poll()

    def _poll(self):
        if not self._text_provider or not self.has_scorer:
            return
        for key, entry in list(self._cache.items()):
            if entry.state != SCORE_STATE_PENDING:
                continue
            si, sub = key
            texts = self._text_provider(si, sub)
            if texts is not None:
                self.request_score(si, sub, texts[0], texts[1])

    def invalidate(self, ordinal: Optional[int] = None, sub: Optional[int] = None):
        """失效。ordinal=None 清空，sub=None 失效该关系全部子行。

        与旧版不同：指定 sub 时即使 cache 中尚无该 key 也创建 PENDING
        条目。这是 split 等操作创建新子行所必需的——新子行必须出现在
        _cache 中，_poll 才能发现并申请评分。
        """
        if ordinal is None:
            self._cache.clear()
            self._pending_req.clear()
            self._debounced_pairs.clear()
            self._debounce_timer.stop()
            self._flat_requests.clear()
            return
        if sub is not None:
            key = (ordinal, sub)
            self._cache[key] = _ScoreEntry(state=SCORE_STATE_PENDING)
            self._pending_req.pop(key, None)
        else:
            keys = [k for k in self._cache if k[0] == ordinal]
            for k in keys:
                self._cache[k] = _ScoreEntry(state=SCORE_STATE_PENDING)
                self._pending_req.pop(k, None)
            if not keys:
                self._cache[(ordinal, 0)] = _ScoreEntry(state=SCORE_STATE_PENDING)

    def invalidate_ordinals(self, ordinals: list[int]):
        for ordinal in ordinals:
            self.invalidate(ordinal)

    def request_score(self, ordinal: int, sub: int, src_text: str, tgt_text: str):
        if self._scorer is None:
            return

        key = (ordinal, sub)
        seq = self._request_seq + 1
        self._request_seq = seq
        self._pending_req[key] = seq
        self._cache[key] = _ScoreEntry(state=SCORE_STATE_LOADING, request_seq=seq)
        self.status_changed.emit(ordinal, sub, SCORE_STATE_LOADING)

        self._debounced_pairs.append(((ordinal, sub), src_text, tgt_text))
        self._debounce_timer.start()

    # ═════════════════════════════════════════════════════════
    # 预览表扁平评分
    # ═════════════════════════════════════════════════════════

    def request_flat_batch(
        self, src_texts: list[str], tgt_texts: list[str], batch_id: int = 0
    ) -> int:
        if self._scorer is None or not src_texts or not tgt_texts:
            return batch_id

        n = max(len(src_texts), len(tgt_texts))
        src = list(src_texts) + [""] * (n - len(src_texts))
        tgt = list(tgt_texts) + [""] * (n - len(tgt_texts))

        pairs = [(-(i + 1), src[i], tgt[i]) for i in range(n)]
        seq = self._request_seq + 1
        self._request_seq = seq
        self._flat_requests[seq] = batch_id

        self._ensure_worker()
        self._worker._trigger.emit(pairs, seq)
        return batch_id

    # ═════════════════════════════════════════════════════════
    # 内部
    # ═════════════════════════════════════════════════════════

    def _flush_pending(self):
        if self._flush_in_progress or not self._debounced_pairs:
            return
        self._flush_in_progress = True
        try:
            queued = self._debounced_pairs
            self._debounced_pairs = []
            # Each worker job needs its own immutable sequence.  Reusing the
            # latest per-key request sequence can collide with a flat-preview
            # job queued between request_score() and this debounce callback.
            latest_by_key = {item[0]: item for item in queued}
            pairs = [
                item for key, item in latest_by_key.items() if key in self._pending_req
            ]
            if not pairs:
                return
            seq = self._request_seq + 1
            self._request_seq = seq
            for key, _source, _target in pairs:
                self._pending_req[key] = seq
            self._do_score_async(pairs, seq)
        finally:
            self._flush_in_progress = False

    def _do_score_async(self, pairs: list, seq: int):
        if not pairs:
            return
        self._ensure_worker()
        self._worker._trigger.emit(pairs, seq)

    def _ensure_worker(self):
        from PySide6.QtCore import QThread

        if self._worker_thread is not None and self._worker_thread.isRunning():
            return

        self._worker_thread = QThread(self)
        self._worker_thread.setObjectName("ScoreWorkerThread")

        scorer_copy = None
        if self._scorer is not None:
            from dualign.services.similarity import SimilarityScorer

            scorer_copy = SimilarityScorer(
                entry_id=self._scorer.entry_id,
                cache_dir=getattr(self._scorer, "_cache_dir", ""),
            )

        self._worker = (
            ScoreWorker(scorer_copy) if scorer_copy else ScoreWorker(self._scorer)
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker._trigger.connect(
            self._worker.run, Qt.ConnectionType.QueuedConnection
        )
        self._worker_thread.finished.connect(self._worker.deleteLater)
        self._worker_thread.start()

    def _on_worker_finished(self, results: dict, seq: int):
        # ── 扁平批次 ──
        batch_id = self._flat_requests.pop(seq, None)
        if batch_id is not None:
            if not results:
                self.flat_batch_ready.emit(batch_id, None)
                return
            if not all(isinstance(key, int) and key < 0 for key in results):
                logger.warning("丢弃键类型异常的扁平评分结果 (seq=%s)", seq)
                self.flat_batch_ready.emit(batch_id, None)
                return
            import numpy as np

            n_positions = max(abs(key) for key in results)
            scores = np.zeros(n_positions, dtype=np.float64)
            for neg_pos, score in results.items():
                scores[abs(neg_pos) - 1] = score
            self.flat_batch_ready.emit(batch_id, scores)
            return

        # ── 子行评分 ──
        for worker_key, score in results.items():
            if not (isinstance(worker_key, tuple) and len(worker_key) == 2):
                continue
            ordinal, sub = worker_key
            key = (ordinal, sub)
            pending_seq = self._pending_req.get(key)
            # Missing means the relation/document was invalidated while this
            # worker was running.  A different sequence belongs to another
            # immutable queued job for the same key.
            if pending_seq != seq:
                continue

            self._cache[key] = _ScoreEntry(
                score=score, state=SCORE_STATE_READY, request_seq=seq
            )
            self._pending_req.pop(key, None)
            self.score_updated.emit(ordinal, sub, score)
            self.status_changed.emit(ordinal, sub, SCORE_STATE_READY)

    def _on_worker_error(self, error_msg: str, seq: int):
        logger.error(f"ScoreWorker 错误 (seq={seq}): {error_msg}")

        # 扁平批次错误：仅当 worker 处理的是扁平批次时发送 None
        batch_id = self._flat_requests.pop(seq, None)
        if batch_id is not None:
            self.flat_batch_ready.emit(batch_id, None)

        for key, request_seq in list(self._pending_req.items()):
            if request_seq != seq:
                continue
            ordinal, sub = key
            entry = self._cache.get(key)
            if entry is not None and entry.state == SCORE_STATE_LOADING:
                self._cache[key] = _ScoreEntry(state=SCORE_STATE_FAILED)
                self._pending_req.pop(key, None)
                self.status_changed.emit(ordinal, sub, SCORE_STATE_FAILED)

    def cleanup(self):
        if self._worker is not None:
            self._worker.cancel()
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
            self._worker_thread = None
            self._worker = None
