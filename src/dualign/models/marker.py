"""Marker construction and legacy parsing.

Canonical markers express only repair/attention operations:

    [M]   — 合并（merge）
    [S]   — 拆分（split）
    [E]   — 校订（edit）
    [D]   — 删除（delete）
    [P]   — 占位（placeholder）
    [F]   — 标记异常（flag）

The current effective source lives in its own ``none/auto/ai/user`` field.
Parsing helpers continue to understand historical ``[AI]`` and ``[OK]``
forms so old data can be projected without making those strings domain truth.
"""

from __future__ import annotations

import re
from typing import Dict

# ═══════════════════════════════════════════════════════════════
# 常量 — kind → marker 映射（唯一来源）
# ═══════════════════════════════════════════════════════════════

KIND_MAP: Dict[str, str] = {
    "merge": "[M]",
    "split": "[S]",
    "edit": "[E]",
    "delete": "[D]",
    "flag": "[F]",
    "ok": "",
    "placeholder_src": "[P]",
    "placeholder_tgt": "[P]",
}


# ── marker 的三个正交语义轴 ──
CONTENT_TAGS = frozenset({"[M]", "[S]", "[E]", "[D]", "[P]"})
REVIEW_TAGS = frozenset({"[OK]", "[F]"})
PROVENANCE_TAGS = frozenset({"[AI]"})

# ── 使 marker 逻辑变为 1:1 的内容操作（审批本身不改变结构）──
_RESOLVE_TO_11_TAGS = frozenset({"[M]", "[S]", "[P]"})

# ── 需要 score=0 的操作标记 ──
_ZERO_SCORE_TAGS = frozenset({"[D]", "[P]"})

# 来源前缀
AI_PREFIX = "[AI]"
_MARKER_ATOM_RE = re.compile(
    r"(?:\[AI\]\[(?:OK|M|S|E|D|P|F)\]|\[(?:OK|M|S|E|D|P|F|AI)\])"
)


# ═══════════════════════════════════════════════════════════════
# 构造
# ═══════════════════════════════════════════════════════════════


def from_kind(kind: str) -> str:
    """Return the canonical operation marker for one action kind."""

    return KIND_MAP.get(kind, "")


# ═══════════════════════════════════════════════════════════════
# 语义查询（替代各处 `"[X]" in marker` 裸字符串匹配）
# ═══════════════════════════════════════════════════════════════


def marker_atoms(marker: str) -> tuple[str, ...]:
    """Parse source-qualified marker atoms, including compact legacy strings."""

    return tuple(_MARKER_ATOM_RE.findall(marker or ""))


def _base_tag(atom: str) -> str:
    """Strip a compact AI creator prefix without erasing standalone provenance."""

    if atom == AI_PREFIX:
        return atom
    return atom[len(AI_PREFIX) :] if atom.startswith(AI_PREFIX) else atom


def marker_tags(marker: str) -> tuple[str, ...]:
    """Return semantic tags without their optional source prefix."""

    return tuple(_base_tag(atom) for atom in marker_atoms(marker))


def tag_axis(tag: str) -> str:
    """Return the semantic axis occupied by one base tag."""

    if tag in CONTENT_TAGS:
        return "content"
    if tag in REVIEW_TAGS:
        return "review"
    if tag in PROVENANCE_TAGS:
        return "provenance"
    return ""


def without_source_prefixes(marker: str) -> str:
    """Render only semantic tags while retaining their axis structure."""

    return " ".join(tag for tag in marker_tags(marker) if tag != AI_PREFIX)


def mark_ai_reviewed(marker: str) -> str:
    """Attach AI review provenance without inventing a second OK decision."""

    return combine(marker, AI_PREFIX)


def has_tag(marker: str, tag: str) -> bool:
    """检查 marker 是否包含指定标记。

    替代 `"[M]" in marker`、`"[OK]" in marker` 等各处散落的匹配。
    """
    return tag in marker_tags(marker)


def is_merge(marker: str) -> bool:
    """是否为合并操作。"""
    return has_tag(marker, "[M]")


def is_split(marker: str) -> bool:
    """是否为拆分操作。"""
    return has_tag(marker, "[S]")


def is_edit(marker: str) -> bool:
    """是否为校订操作。"""
    return has_tag(marker, "[E]")


def is_deleted(marker: str) -> bool:
    """是否已删除。"""
    return has_tag(marker, "[D]")


def is_placeholder(marker: str) -> bool:
    """是否为占位符。"""
    return has_tag(marker, "[P]")


def is_flagged(marker: str) -> bool:
    """是否标记异常。"""
    return has_tag(marker, "[F]")


def is_approved(marker: str) -> bool:
    """是否审核通过。"""
    return has_tag(marker, "[OK]")


# ═══════════════════════════════════════════════════════════════
# 复合语义
# ═══════════════════════════════════════════════════════════════


def is_resolved_to_11(marker: str) -> bool:
    """操作是否使文本对逻辑上变为 1:1。

    [M]/[S]/[P] 会使 cur_type → 1:1，n_src/n_tgt 调整；[OK]
    只表达审阅结论，不改变内容结构。

    替代 `any(t in marker for t in ("[M]", "[S]", "[P]", "[OK]"))`。
    """
    if not marker:
        return False
    return bool(set(marker_tags(marker)) & _RESOLVE_TO_11_TAGS)


def needs_zero_score(marker: str) -> bool:
    """操作是否需要将 score 设为 0。"""
    if not marker:
        return False
    return bool(set(marker_tags(marker)) & _ZERO_SCORE_TAGS)


# ═══════════════════════════════════════════════════════════════
# 组合
# ═══════════════════════════════════════════════════════════════


def combine(existing: str, new_tag: str) -> str:
    """Combine marker atoms by replacing the decision on the same axis.

    A relation has at most one effective content decision, one review state,
    and one independent review-provenance tag.  The optional compact ``[AI]``
    prefix still belongs to the operation atom for AI-created decisions.  This
    covers content replacement, [OK]/[F] mutual exclusion, de-duplication, and
    compact legacy marker normalization.
    """

    result = list(marker_atoms(existing))
    for atom in marker_atoms(new_tag):
        base = _base_tag(atom)
        axis = tag_axis(base)
        replaced_axes = {axis}
        if axis in {"content", "review"}:
            # Standalone [AI] describes who confirmed the current decision;
            # replacing that decision/review invalidates the old confirmation.
            replaced_axes.add("provenance")
        result = [
            current
            for current in result
            if tag_axis(_base_tag(current)) not in replaced_axes
        ]
        result.append(atom)
    return " ".join(result)


# ═══════════════════════════════════════════════════════════════
# 颜色映射（纯数据，不依赖 Qt）
# ═══════════════════════════════════════════════════════════════

# 十六进制颜色值，供 UI 层使用
# 设计原则：每种操作使用饱和色，在明暗主题下都足够清晰
# 同一色系不跨域（操作色与异常色不共用色系）
MARKER_COLORS: Dict[str, str] = {
    "[M]": "#42A5F5",
    "[S]": "#26A69A",
    "[E]": "#7E57C2",
    "[D]": "#e53935",
    "[P]": "#90A4AE",
    "[F]": "#FF8A65",
    "[OK]": "#4CAF50",
}

# 优先级顺序（从高到低），`resolve_color` 依此选取
_COLOR_PRIORITY = ["[OK]", "[F]", "[D]", "[E]", "[M]", "[S]", "[P]"]


def resolve_hex_color(marker: str) -> str:
    """marker → 十六进制颜色值（不含 Qt 依赖）。

    按优先级: [OK]绿 > [F]橙 > [D]红 > 其他操作标记色 > "#B0B0B0"（灰色）
    """
    if not marker:
        return "#B0B0B0"
    tags = set(marker_tags(marker))
    for tag in _COLOR_PRIORITY:
        if tag in tags:
            return MARKER_COLORS[tag]
    return "#B0B0B0"


# ═══════════════════════════════════════════════════════════════
# 异常类型短标签 — 用于 GUI 表格「当前状态」列的 Layer 2 显示
# ═══════════════════════════════════════════════════════════════

ANOMALY_SHORT_LABELS: Dict[str, str] = {
    "NON_1TO1": "非1:1",
    "MIX": "语言杂糅",
    "LOW_SCORE": "低分",
    "FLAGGED": "标记待查",
}


def format_anomaly_line(anomaly_types: set[str]) -> str:
    """将异常类型集合格式化为一行短标签。

    注意：不依赖 marker 抑制逻辑。异常类型的判定已由调用方通过
    双模（初始/当前文本）完成，此处仅做纯标签格式化。
    """
    if not anomaly_types:
        return ""
    labels = []
    for t in sorted(anomaly_types):
        label = ANOMALY_SHORT_LABELS.get(t, t)
        if label not in labels:
            labels.append(label)
    return "/".join(labels)
