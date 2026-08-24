"""
Dualign — RelationStatus: 对齐关系的派生审阅状态

Layer 1: 原始对齐事实 — 写入后只读
Layer 2: 当前文本状态 — 随修复更新
Layer 3: 处理历史 — 随操作追加
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dualign.models.state import AlignmentSnapshot, MISSING
from dualign.models.action import RepairAction
from dualign.models.marker import is_merge
from dualign.core import detect_language_mix, _smart_join_lines

# ── approval 四态管线 ──
# none → proposed → agent → user（递进，flag 不推进管线）
#
# 持久化值仍保留为 "auto"，以兼容旧 report 和筛选设置；它的审批
# 语义是“机器已提出拟修复，尚未审核”，不是“已自动批准”。
APPROVAL_NONE = "none"
APPROVAL_PROPOSED = "auto"
APPROVAL_AGENT = "agent"
APPROVAL_USER = "user"

ALL_APPROVAL_STATES = [
    APPROVAL_NONE,
    APPROVAL_PROPOSED,
    APPROVAL_AGENT,
    APPROVAL_USER,
]

APPROVAL_LABELS = {
    APPROVAL_NONE: "未处理",
    APPROVAL_PROPOSED: "拟修复",
    APPROVAL_AGENT: "AI 审校",
    APPROVAL_USER: "用户审校",
}


# ═══════════════════════════════════════════════════════════════
# auto_repair_note — 生成 AI 可见的 auto_note 文本
# ═══════════════════════════════════════════════════════════════


def auto_repair_note(n_src: int, n_tgt: int, strategy: str, approval: str = "") -> str:
    """返回结构化 auto_note：`策略名 | 机器动作 | 补充`

    strategy: "minimal" | "src" | "tgt"
    当 snap 已自动修复 (approval=auto_repaired) 时动作表示已完成的操作；
    当 snap 未处理时动作为 would_*，表示「如果自动修复会怎么做」。

    输出示例:
      "src-first | merged | 合并3行原文→1行"
      "src-first | would_merge | 可合并3行原文→1行（待确认）"
    """
    strategy_name = {"minimal": "minimal", "src": "src-first", "tgt": "tgt-first"}.get(
        strategy, "src-first"
    )
    is_repaired = approval == APPROVAL_PROPOSED

    if n_src == 1 and n_tgt == 1:
        return ""

    if n_src > 1 and n_tgt == 1:
        # N:1 → src: split tgt, tgt: merge src
        if is_repaired:
            if strategy == "tgt":
                return f"{strategy_name} | merged | 合并{n_src}行原文→1行"
            return f"{strategy_name} | split | 拆分1行译文为{n_src}行匹配原文"
        if strategy == "minimal":
            return f"{strategy_name} | unrepaired | {n_src}:1 未自动处理（minimal 不自动合并）"
        if strategy == "tgt":
            return f"{strategy_name} | would_merge | 可合并{n_src}行原文→1行（语义优先，不强制）"
        return (
            f"{strategy_name} | would_split | 语义优先，拆分或合并均可（使用edit操作）"
        )

    if n_src == 1 and n_tgt > 1:
        # 1:M → src: merge tgt, tgt: split src
        if is_repaired:
            if strategy == "tgt":
                return f"{strategy_name} | split | 拆分1行原文为{n_tgt}行匹配译文"
            return f"{strategy_name} | merged | 合并{n_tgt}行译文→1行"
        if strategy == "minimal":
            return f"{strategy_name} | unrepaired | 1:{n_tgt} 未自动处理（minimal 不自动合并）"
        if strategy == "tgt":
            return f"{strategy_name} | would_split | 语义优先，拆分或合并均可（使用edit操作）"
        return f"{strategy_name} | would_merge | 可合并{n_tgt}行译文→1行（语义优先，不强制）"

    if n_src == 0 and n_tgt > 0:
        if is_repaired:
            action = "deleted" if strategy == "minimal" else "placeholder"
            return f"{strategy_name} | {action} | 已处理"
        if strategy == "minimal":
            return f"{strategy_name} | unrepaired | {n_tgt}行译文无对应原文（minimal 建议view后delete）"
        return f"{strategy_name} | would_delete | {n_tgt}行译文无对应原文（建议view确认后delete或保留）"

    if n_src > 0 and n_tgt == 0:
        if is_repaired:
            action = "deleted" if strategy == "minimal" else "placeholder"
            return f"{strategy_name} | {action} | 已处理"
        if strategy == "minimal":
            return f"{strategy_name} | unrepaired | {n_src}行原文无译文（minimal 建议edit补译）"
        return f"{strategy_name} | would_placeholder | 保留{n_src}行原文，译文需补⟢MISSING⟣"

    action = "processed" if is_repaired else "unrepaired"
    return f"{strategy_name} | {action} | {n_src}:{n_tgt} 未自动处理"


# ═══════════════════════════════════════════════════════════════
# parse_auto_note — 解析 auto_note 结构化字段（集中化入口）
# ═══════════════════════════════════════════════════════════════

WOULD_ACTIONS = frozenset(
    {"would_merge", "would_split", "would_delete", "would_placeholder"}
)


def parse_auto_note(auto_note: str) -> tuple[str, str, str]:
    """解析 auto_note 返回 (strategy, action, detail)。

    格式: `策略名 | 机器动作 | 补充说明`
    例如: `"src-first | would_split | 语义优先，拆分或合并均可"`

    返回:
      strategy: "src-first" / "tgt-first" / "minimal" / ""
      action:   "merged" / "split" / "would_merge" / "would_split" / "unrepaired" / "" 等
      detail:   补充文本
    """
    if not auto_note:
        return "", "", ""
    parts = auto_note.split("|", 2)
    strategy = parts[0].strip() if len(parts) > 0 else ""
    action = parts[1].strip() if len(parts) > 1 else ""
    detail = parts[2].strip() if len(parts) > 2 else ""
    return strategy, action, detail


def is_would_action(action: str) -> bool:
    """判断是否为 would_* 建议动作。"""
    return action in WOULD_ACTIONS


# ═══════════════════════════════════════════════════════════════
# compute_relation_preview — 为非 1:1 关系计算合并/修复预览
# ═══════════════════════════════════════════════════════════════


def compute_relation_preview(snapshot: AlignmentSnapshot, ordinal: int) -> str:
    """为非 1:1 关系计算将全部行连接为 1:1 后的文本预览。

    展示所有 src 行和所有 tgt 行分别拼接的结果。
    不修改任何实际状态。
    """
    s_idx, t_idx, _sc = snapshot.original_ops[ordinal]
    ls, lt = len(s_idx), len(t_idx)

    if ls == 0 and lt > 0:
        tgt_texts = [snapshot.tgt_text(j) for j in t_idx]
        merged_tgt = (
            _smart_join_lines(tgt_texts)
            if len(tgt_texts) > 1
            else (tgt_texts[0] if tgt_texts else "")
        )
        return f"0:{lt} 无原文 | 译文: {merged_tgt}"
    if ls > 0 and lt == 0:
        src_texts = [snapshot.src_text(i) for i in s_idx]
        merged_src = (
            _smart_join_lines(src_texts)
            if len(src_texts) > 1
            else (src_texts[0] if src_texts else "")
        )
        return f"{ls}:0 无译文 | 原文: {merged_src} | {MISSING}"
    if ls == 1 and lt == 1:
        return ""
    # N:1 / 1:M / N:M → 展示全部行拼接为 1:1 后的文本
    src_texts = [snapshot.src_text(i) for i in s_idx]
    tgt_texts = [snapshot.tgt_text(j) for j in t_idx]
    merged_src = _smart_join_lines([t for t in src_texts if t])
    merged_tgt = _smart_join_lines([t for t in tgt_texts if t])
    return f"1:1 预览\nsrc: {merged_src}\ntgt: {merged_tgt}"


# ═══════════════════════════════════════════════════════════════
# build_context_windows — 构建上下文窗口（集中化入口）
# ═══════════════════════════════════════════════════════════════


def build_context_windows(
    reviewable_ids: List[int],
    total: int,
    window_size: int = 3,
    merge_gap_threshold: int = 1,
) -> List[Tuple[int, int]]:
    """构建上下文窗口，相邻间距 ≤ merge_gap_threshold 时合并。

    Args:
        reviewable_ids: 待审的 snap 索引列表
        total: 总 snap 数
        window_size: 每侧上下文行数
        merge_gap_threshold: 窗口间距 ≤ 此值时合并。
                             默认 1：窗口间最多空 1 行时合并。
                             设为 0 则绝不合并。

    Returns:
        合并后的 (start, end) 窗口列表，已排序。
    """
    if not reviewable_ids:
        return []

    windows = [
        (max(0, sid - window_size), min(total - 1, sid + window_size))
        for sid in sorted(reviewable_ids)
    ]

    merged: List[Tuple[int, int]] = []
    for w in windows:
        if not merged or w[0] > merged[-1][1] + merge_gap_threshold + 1:
            merged.append(w)
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], w[1]))
    return merged


# ═══════════════════════════════════════════════════════════════
# RelationStatus
# ═══════════════════════════════════════════════════════════════


def _parse_type(pt: str) -> Tuple[int, int]:
    """解析 "N:M" → (N, M)。"""
    if ":" in pt:
        try:
            ls, lt = pt.split(":", 1)
            return int(ls), int(lt)
        except (ValueError, TypeError):
            pass
    return 1, 1


@dataclass
class RelationStatus:
    """单个文本对的三层状态。

    Layer 1 — 对齐完成后一次性写入，永不变化。
      消费者: 报告统计、GUI「原始非1:1」筛选

    Layer 2 — 每次文本内容变化后重新计算。
      消费者: AI 决策、GUI 渲染

    Layer 3 — 每次 repair 操作后更新。
      消费者: AI「需要验证吗」、GUI「操作记录」筛选
    """

    # ── Layer 1: 原始对齐事实（只读）──
    init_type: str = "1:1"  # 原始对齐类型
    init_score: float = 0.0  # 原始对齐评分
    is_low_score: bool = False  # 原始评分是否统计离群
    init_has_language_mix: bool = False  # 初始译文是否含中文（Layer 1 不可变）

    # ── Layer 2: 当前文本状态 ──
    n_src: int = 1  # 当前组内原文行数
    n_tgt: int = 1  # 当前组内译发行数
    has_missing: bool = False  # 当前文本含 ⟢MISSING⟣
    has_language_mix: bool = False  # 当前译文含中文（Layer 2 可变, 随编辑重新检测）
    is_deleted: bool = False  # 已被删除

    # ── Layer 3: 处理历史 ──
    approval: str = APPROVAL_NONE
    repair_count: int = 0
    last_source: str = ""  # "" / "auto" / "ai" / "user"
    last_operation: str = ""  # merge / split / edit / delete / ok / flag
    is_flagged: bool = False  # 用户手动标记需关注（异常类型 FLAGGED 的持久化状态）
    # ── 派生属性 ──

    @property
    def initial_anomaly_types(self) -> List[str]:
        """原始对齐事实（Layer 1）的异常分类——对齐器自动检测的结果，不可变。

        NON_1TO1 从 init_type 推导，MIX 从初始译文检测，LOW_SCORE 从 Z-score 判定。
        均不随修复操作变化。
        FLAGGED 不是对齐器检测的，不出现于此。
        """
        labels = []
        init_s, init_t = _parse_type(self.init_type)
        if init_s != 1 or init_t != 1:
            labels.append("NON_1TO1")
        if self.init_has_language_mix:
            labels.append("MIX")
        if self.is_low_score:
            labels.append("LOW_SCORE")
        return labels

    @property
    def current_anomaly_types(self) -> List[str]:
        """当前文本状态（Layer 2 + Layer 3）的异常分类——可变状态。

        NON_1TO1 基于两侧行数是否平衡（编辑/拆分产生 n:n 平衡结构时消失）。
        MIX 基于当前文本重新检测。
        FLAGGED 是用户动作。
        LOW_SCORE 是原始评分属性，不出现在此。
        """
        labels = []
        if self.n_src != self.n_tgt:
            labels.append("NON_1TO1")
        if self.has_language_mix:
            labels.append("MIX")
        if self.is_flagged:
            labels.append("FLAGGED")
        return labels

    @property
    def is_reviewable(self) -> bool:
        """用户已审校或已删除 → 不再需审校。GUI 和 AI 共用。"""
        if self.approval == APPROVAL_USER:
            return False
        if self.is_deleted:
            return False
        return bool(self.current_anomaly_types)

    @property
    def signals(self) -> List[str]:
        """自然语言状态信号（供 AI 和 GUI 展示）。"""
        signals = []
        if self.approval == APPROVAL_PROPOSED:
            signals.append("存在拟修复方案")
        if self.has_missing:
            signals.append("缺失待补")
        if self.has_language_mix:
            signals.append("译文含中文")
        if self.is_flagged:
            signals.append("标记待审")
        return signals


# ═══════════════════════════════════════════════════════════════
# RelationReviewInfo — AI 视图（只含 Layer 2 + Layer 3 部分）
# ═══════════════════════════════════════════════════════════════


@dataclass
class RelationReviewInfo:
    """AI 看到的 snap——不包含任何原始对齐事实。

    从 RelationStatus 的 Layer 2 + Layer 3 构建，供 AI Agent 使用。
    用 n_src_rows/n_tgt_rows 替代旧 cur_type 字符串。
    """

    ordinal: int
    # 当前文本（待审校状态）
    n_src_rows: int
    n_tgt_rows: int
    src_text: str
    tgt_text: str
    # 初始文本（对齐器原始输出，AI 操作基准）
    initial_n_src: int = 0
    initial_n_tgt: int = 0
    initial_src_text: str = ""
    initial_tgt_text: str = ""
    # 异常标记
    has_missing: bool = False
    has_language_mix: bool = False
    is_low_score: bool = False
    approval: str = ""
    proposal_kind: str = ""

    @property
    def signals(self) -> List[str]:
        signals = []
        if self.has_missing:
            signals.append("缺失待补")
        if self.has_language_mix:
            signals.append("译文含中文")
        if self.is_low_score:
            signals.append("离群低分")
        return signals

    @property
    def is_reviewable(self) -> bool:
        """基于当前审批与原始/当前异常判断是否需要审阅。"""
        if self.approval == APPROVAL_USER:
            return False
        if self.initial_n_src == 0 and self.initial_n_tgt == 0:
            return False
        return (
            self.initial_n_src != 1
            or self.initial_n_tgt != 1
            or self.has_missing
            or self.has_language_mix
            or self.is_low_score
        )

    def __str__(self) -> str:
        """生成 JSON 行格式，供 LLM 消费。

        src/tgt 以字符串数组形式输出，每元素一行——AI 可以直接在 JSON
        结构中看到每行的独立性，而非被 \\n 嵌入字符串模糊掉行边界。
        AI 从 src/tgt 数组长度即可推断行数，无需冗余的 n_src/n_tgt 字段。

        orig 字段标注初始类型的行数关系（如 "2:1"、"1:2"），
        AI 无需从 initial_* 推算即可知初始结构。
        initial_src/initial_tgt 始终展示（当存在时），使 AI 在 edit 决策时
        能直接参考初始文本——edit 操作的是初始文本，不是当前文本。
        """
        d = {"id": self.ordinal}
        sigs = self.signals
        if sigs:
            d["signals"] = sigs
        # 始终标注初始类型，AI 零推理成本获知初始行数关系
        d["orig"] = f"{self.initial_n_src}:{self.initial_n_tgt}"
        if self.approval == APPROVAL_PROPOSED:
            # 显式告诉 Agent 它正在审批什么，避免将 ok 理解为空泛的“语义正确”。
            d["proposal"] = self.proposal_kind or "pending"
        if self.src_text:
            d["src"] = [ln for ln in self.src_text.split("\n") if ln]
        else:
            d["src"] = []  # 显式空数组，表明原文不存在
        if self.tgt_text:
            d["tgt"] = [ln for ln in self.tgt_text.split("\n") if ln]
        else:
            d["tgt"] = []  # 显式空数组，表明译文不存在
        # 初始文本：仅当与当前文本不同时展示
        # orig 字段已提供初始类型信息，无需重复相同的文本内容
        if self.initial_src_text and self.initial_src_text != self.src_text:
            d["initial_src"] = [ln for ln in self.initial_src_text.split("\n") if ln]
        if self.initial_tgt_text and self.initial_tgt_text != self.tgt_text:
            d["initial_tgt"] = [ln for ln in self.initial_tgt_text.split("\n") if ln]
        return json.dumps(d, ensure_ascii=False)


@dataclass(frozen=True)
class RelationAnomaly:
    """Typed GUI projection for one reviewable current relation."""

    relation_ids: tuple[str, ...] = ()
    ordinals: tuple[int, ...] = ()
    src_text: str = ""
    tgt_text: str = ""
    init_type: str = ""
    cur_type: str = ""
    score: float = 0.0
    marker: str = ""
    resolution: str = ""
    note: str = ""
    approval: str = APPROVAL_NONE
    signals: tuple[str, ...] = ()
    anomaly_types: tuple[str, ...] = ()

    @property
    def ordinal(self) -> int | None:
        return self.ordinals[0] if self.ordinals else None


# ═══════════════════════════════════════════════════════════════
# 统一构建函数
# ═══════════════════════════════════════════════════════════════


def _calc_low_score(scores: List[float], score: float, k: float = 3.0) -> bool:
    """Z-score 离群检测（只用于对齐后的异常标记）。"""
    from dualign.services.anomaly_detection import is_statistical_low_score

    return is_statistical_low_score(score, scores, k=k)


def _derive_approval(action: Optional[RepairAction]) -> str:
    """从 RepairAction 推导四态管线 approval。

    none → proposed → agent → user（递进）。
    RepairAction.source="auto" 表示机器拟定的方案，并非审批完成。
    flag 不推进管线：返回 NONE（调用方需向上游查找有效状态）。
    """
    if action is None:
        return APPROVAL_NONE
    if action.kind == "flag":
        return APPROVAL_NONE  # flag 不推进管线（无论来源）
    s = action.source
    if s == "auto":
        return APPROVAL_PROPOSED
    if s == "ai":
        return APPROVAL_AGENT
    if s == "user":
        return APPROVAL_USER
    # 兼容旧 source=""（视为 auto）
    if not s:
        return APPROVAL_PROPOSED
    return APPROVAL_NONE


def _action_summary(
    actions: List[RepairAction],
) -> tuple[Optional[RepairAction], int, bool]:
    """Return the latest non-flag action, its count, and current flag state."""
    last_action = actions[-1] if actions else None
    non_flag_actions = [action for action in actions if action.kind != "flag"]
    return (
        non_flag_actions[-1] if non_flag_actions else None,
        len(non_flag_actions),
        last_action is not None and last_action.kind == "flag",
    )


def project_relation_statuses(repair_state, k: float = 3.0) -> List[RelationStatus]:
    """Project the sole repair state into immutable review statuses once."""

    snapshot = repair_state.snapshot
    chapter = repair_state.current
    repair_log = repair_state.repair_log
    scores_1to1 = [
        score
        for source, target, score in snapshot.original_ops
        if len(source) == 1 and len(target) == 1
    ]
    actions_by_ordinal: dict[int, list[RepairAction]] = {}
    for action in repair_log:
        for ordinal in action.operation_indices:
            actions_by_ordinal.setdefault(ordinal, []).append(action)

    statuses: list[RelationStatus] = []
    for ordinal, (source, target, score) in enumerate(snapshot.original_ops):
        initial_source_count = len(source)
        initial_target_count = len(target)
        initial_target_text = "\n".join(snapshot.tgt_text(index) for index in target)
        initial_has_mix = (
            detect_language_mix(initial_target_text)
            if initial_target_text.strip()
            else False
        )
        group = chapter.group(ordinal)
        current_source_text = (
            "\n".join(row.src_text for row in group.rows if row.src_text)
            if group is not None
            else ""
        )
        current_target_text = (
            "\n".join(row.tgt_text for row in group.rows if row.tgt_text)
            if group is not None
            else ""
        )
        if group is None:
            current_source_count = 0
            current_target_count = 0
        elif group.rows and is_merge(group.rows[0].marker):
            current_source_count = current_target_count = 1
        else:
            current_source_count = sum(bool(row.src_text.strip()) for row in group.rows)
            current_target_count = sum(bool(row.tgt_text.strip()) for row in group.rows)
            if current_source_count == 0 and current_target_count == 0:
                current_source_count = group.rows[0].n_src if group.rows else 1
                current_target_count = group.rows[0].n_tgt if group.rows else 1

        last_action, repair_count, is_flagged = _action_summary(
            actions_by_ordinal.get(ordinal, [])
        )
        statuses.append(
            RelationStatus(
                init_type=f"{initial_source_count}:{initial_target_count}",
                init_score=float(score),
                is_low_score=(
                    _calc_low_score(scores_1to1, float(score), k=k)
                    if initial_source_count == initial_target_count == 1
                    else False
                ),
                init_has_language_mix=initial_has_mix,
                n_src=current_source_count,
                n_tgt=current_target_count,
                has_missing=(
                    MISSING in current_source_text or MISSING in current_target_text
                ),
                has_language_mix=(
                    detect_language_mix(current_target_text)
                    if current_target_text.strip()
                    else False
                ),
                is_deleted=group is None
                or (last_action is not None and last_action.kind == "delete"),
                approval=_derive_approval(last_action),
                repair_count=repair_count,
                last_source=last_action.source if last_action else "",
                last_operation=last_action.kind if last_action else "",
                is_flagged=is_flagged,
            )
        )
    return statuses


def relation_status_to_info(
    state: RelationStatus, ordinal: int, src_text: str, tgt_text: str
) -> RelationReviewInfo:
    """Convert a projected relation status into the compact AI view."""

    return RelationReviewInfo(
        ordinal=ordinal,
        n_src_rows=state.n_src,
        n_tgt_rows=state.n_tgt,
        src_text=src_text,
        tgt_text=tgt_text,
        has_missing=state.has_missing,
        has_language_mix=state.has_language_mix,
        is_low_score=state.is_low_score,
        approval=state.approval,
        proposal_kind=(
            state.last_operation if state.approval == APPROVAL_PROPOSED else ""
        ),
        # initial_* 由调用方填充
    )
