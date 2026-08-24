"""
Dualign — MarkerHelper: marker 字符串纯函数工具类

统一管理 marker 的构造、解析和语义查询。

Marker 格式:
  `[来源前缀][操作标记]`，多个标记以空格分隔。
  例如: `[M]`, `[AI][M]`, `[M] [OK]`, `[AI][S]`, `[OK]`

  来源前缀（可选）: 无 / [AI]
    - 无前缀 = 自动修复 或 用户手动操作
    - [AI]   = AI Agent 校订
  操作标记:
    [M]   — 合并（merge）
    [S]   — 拆分（split）
    [E]   — 校订（edit）
    [D]   — 删除（delete）
    [P]   — 占位（placeholder）
    [F]   — 标记异常（flag）
    [OK]  — 审核通过
"""

from __future__ import annotations

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
    "ok": "[OK]",
    "placeholder_src": "[P]",
    "placeholder_tgt": "[P]",
}


# ── 使 marker 逻辑变为 1:1 的操作标记（影响 n_src/n_tgt / cur_type）──
_RESOLVE_TO_11_TAGS = frozenset({"[M]", "[S]", "[P]", "[OK]"})

# ── 需要 score=0 的操作标记 ──
_ZERO_SCORE_TAGS = frozenset({"[D]", "[P]"})

# 来源前缀
AI_PREFIX = "[AI]"


# ═══════════════════════════════════════════════════════════════
# 构造
# ═══════════════════════════════════════════════════════════════


def from_kind(kind: str, source: str = "") -> str:
    """kind + source → marker 字符串。

    Args:
        kind:   操作类型（merge/split/edit/delete/flag/ok/placeholder_src/placeholder_tgt）
        source: 来源（"" / "ai"）

    Returns:
        marker 字符串，如 `[AI][M]`, `[M]`, `[OK]`
    """
    base = KIND_MAP.get(kind, "")
    if source == "ai":
        return f"{AI_PREFIX}{base}"
    return base


# ═══════════════════════════════════════════════════════════════
# 语义查询（替代各处 `"[X]" in marker` 裸字符串匹配）
# ═══════════════════════════════════════════════════════════════


def has_tag(marker: str, tag: str) -> bool:
    """检查 marker 是否包含指定标记。

    替代 `"[M]" in marker`、`"[OK]" in marker` 等各处散落的匹配。
    """
    return tag in marker if marker else False


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

    [M]/[S]/[P]/[OK] 都会使 cur_type → 1:1，n_src/n_tgt 调整。

    替代 `any(t in marker for t in ("[M]", "[S]", "[P]", "[OK]"))`。
    """
    if not marker:
        return False
    return any(t in marker for t in _RESOLVE_TO_11_TAGS)


def needs_zero_score(marker: str) -> bool:
    """操作是否需要将 score 设为 0。"""
    if not marker:
        return False
    return any(t in marker for t in _ZERO_SCORE_TAGS)


# ═══════════════════════════════════════════════════════════════
# 组合
# ═══════════════════════════════════════════════════════════════


def combine(existing: str, new_tag: str) -> str:
    """向现有 marker 叠加标记，保留每个标记自身的来源前缀。

    规则:
      - [OK] 与 [F] 互斥：叠加 [OK] 时移除 [F]，叠加 [F] 时移除 [OK]
      - 去重：如果 existing 中已有相同的标记，先移除旧的
      - 叠加：追加到末尾，空格分隔
    """
    if not existing:
        return new_tag
    is_ok = is_approved(new_tag)
    is_flag = is_flagged(new_tag)
    base = "[OK]" if is_ok else "[F]" if is_flag else new_tag
    tags_to_remove = {base}
    if is_ok:
        tags_to_remove.add("[F]")
    elif is_flag:
        tags_to_remove.add("[OK]")
    parts = [p for p in existing.split(" ") if not any(t in p for t in tags_to_remove)]
    clean = " ".join(p for p in parts if p).strip()
    return f"{clean} {new_tag}" if clean else new_tag


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
    for tag in _COLOR_PRIORITY:
        if tag in marker:
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
