"""
Dualign — ChapterState: 重放后的章节状态

数据流: AlignmentSnapshot + RepairAction[] → replay() → ChapterState

核心原则:
  1. relation_id 是身份，ordinal 是 original_ops 中的当前顺序
  2. sub 仅在 RelationGroup.rows 内部有意义
  3. info-free 操作仅存 marker，文本在渲染时从 snapshot 重建
  4. info-full 操作存储完整新文本
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from typing import List, Optional, Tuple

from dualign.models.marker import (
    is_merge,
    is_resolved_to_11,
    needs_zero_score,
)
from dualign.core import op_type_str
from dualign.models.relation_identity import normalize_relation_ids

# ═══════════════════════════════════════════════════════════════
# AlignmentSnapshot — 不可变对齐快照
# ═══════════════════════════════════════════════════════════════

OpT = Tuple[Tuple[int, ...], Tuple[int, ...], float]
MISSING = "\u27e2MISSING\u27e3"


@dataclass(frozen=True)
class AlignmentSnapshot:
    """对齐完成时的不可变快照。

    original_ops:        对齐操作序列 [(src_indices, tgt_indices, score), ...]
    original_src_lines:  原始原文行
    original_tgt_lines:  原始译文行

    ordinal 始终指向 original_ops[ordinal]；relation_id 承担持久身份。
    """

    original_ops: Tuple[OpT, ...]
    original_src_lines: Tuple[str, ...]
    original_tgt_lines: Tuple[str, ...]
    relation_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relation_ids",
            normalize_relation_ids(len(self.original_ops), self.relation_ids),
        )

    @classmethod
    def from_alignment(
        cls,
        all_ops: list,
        src_lines: list,
        tgt_lines: list,
        relation_ids: Iterable[str] = (),
    ) -> AlignmentSnapshot:
        """从对齐结果构造快照。"""
        return cls(
            original_ops=tuple((tuple(s), tuple(t), float(sc)) for s, t, sc in all_ops),
            original_src_lines=tuple(src_lines),
            original_tgt_lines=tuple(tgt_lines),
            relation_ids=tuple(relation_ids),
        )

    def relation_id(self, operation_index: int) -> str:
        """Return the stable relation identity at the current ordered position."""

        return self.relation_ids[operation_index]

    def operation_index(self, relation_id: str) -> int:
        """Project a stable relation identity back to its current position."""

        try:
            return self.relation_ids.index(relation_id)
        except ValueError as exc:
            raise KeyError(f"未知关系 ID: {relation_id}") from exc

    @property
    def ops_list(self) -> list:
        return list(self.original_ops)

    @property
    def src_list(self) -> list:
        return list(self.original_src_lines)

    @property
    def tgt_list(self) -> list:
        return list(self.original_tgt_lines)

    def src_text(self, idx: int) -> str:
        if 0 <= idx < len(self.original_src_lines):
            return self.original_src_lines[idx].rstrip()
        return ""

    def tgt_text(self, idx: int) -> str:
        if 0 <= idx < len(self.original_tgt_lines):
            return self.original_tgt_lines[idx].rstrip()
        return ""


# ═══════════════════════════════════════════════════════════════
# RelationRow — 表格行数据载体
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RelationRow:
    """单个表格行（不可变数据载体）。

    ordinal:     当前关系序号（指向 snapshot.original_ops）
    sub:         内部相对索引（0, 1, 2...）
    init_type:   初始对齐类型 ("3:1", "1:2", "1:1" 等)
    cur_type:    当前类型（通常是 "1:1"）
    src_text:    原文文本
    tgt_text:    译文文本
    score:       当前评分
    orig_score:  初始评分（来自 snapshot）
    n_src:       原文行数
    n_tgt:       译文行数
    marker:      操作标记 ("" / "[M]" / "[S]" / "[E]" / "[D]" / "[P]" / "[F]" / "[OK]")
    """

    ordinal: int
    sub: int
    init_type: str
    cur_type: str
    src_text: str
    tgt_text: str
    score: float
    orig_score: float
    n_src: int
    n_tgt: int
    marker: str = ""
    init_score_text: str = ""  # 捆绑编辑时多行分数文本

    @property
    def is_divider(self) -> bool:
        """仅合并 [M] 的行之间需要虚线分隔。

        委托给 marker.py 的 is_divider() 统一管理。
        """
        from dualign.models.marker import is_divider as _is_divider

        return _is_divider(self.marker, self.sub)


# ═══════════════════════════════════════════════════════════════
# RelationGroup — 一个初始关系的当前状态
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RelationGroup:
    """一个初始对齐关系的当前状态。

    relation_id: 稳定关系身份。
    ordinal: 当前快照中的有序位置。
    rows:   内部子行 (sub=0,1,2...)。info-free 操作只改 marker。
    """

    relation_id: str
    ordinal: int
    rows: Tuple[RelationRow, ...]

    # ── 构造器 ──

    @classmethod
    def from_snapshot(cls, ordinal: int, snapshot: AlignmentSnapshot) -> RelationGroup:
        """从快照构建初始关系。"""
        s_idx, t_idx, sc = snapshot.original_ops[ordinal]
        it = op_type_str(s_idx, t_idx)
        n = max(len(s_idx), len(t_idx))
        rows: List[RelationRow] = []
        for sub in range(n):
            rows.append(
                RelationRow(
                    ordinal=ordinal,
                    sub=sub,
                    init_type=it if sub == 0 else "",
                    cur_type=it,
                    src_text=snapshot.src_text(s_idx[sub]) if sub < len(s_idx) else "",
                    tgt_text=snapshot.tgt_text(t_idx[sub]) if sub < len(t_idx) else "",
                    score=float(sc),
                    orig_score=float(sc),
                    n_src=len(s_idx),
                    n_tgt=len(t_idx),
                )
            )
        return cls(
            relation_id=snapshot.relation_id(ordinal),
            ordinal=ordinal,
            rows=tuple(rows),
        )

    # ── 修改器（返回新 RelationGroup） ──

    def with_marker(self, marker: str) -> RelationGroup:
        """对所有行设置相同的 marker。返回新 RelationGroup。

        兼容格式: "[M]", "[AI][OK]", "[M] [AI][OK]"
        cur_type 改为 1:1 的条件: marker 含 [M], [S], [P], [OK]
        """
        new_cur = "1:1" if is_resolved_to_11(marker) else self.rows[0].cur_type
        zero_score = needs_zero_score(marker)
        # [M]: 保留原始 n_src/n_tgt，让 _compute_spans 能正确判断少行侧的列跨行合并。
        #      例如 2:1 → 译文列跨行，第 2 行继承译文文本。
        # [S]/[P]/[OK]: 逻辑上变为 1:1，各子行独立显示。
        if is_merge(marker):
            logical_n_src = self.rows[0].n_src
            logical_n_tgt = self.rows[0].n_tgt
        elif is_resolved_to_11(marker):
            logical_n_src = 1
            logical_n_tgt = 1
        else:
            logical_n_src = self.rows[0].n_src
            logical_n_tgt = self.rows[0].n_tgt
        return RelationGroup(
            relation_id=self.relation_id,
            ordinal=self.ordinal,
            rows=tuple(
                RelationRow(
                    ordinal=r.ordinal,
                    sub=r.sub,
                    init_type=r.init_type,
                    cur_type=new_cur,
                    src_text=r.src_text,
                    tgt_text=r.tgt_text,
                    score=0.0 if zero_score else r.score,
                    orig_score=r.orig_score,
                    n_src=logical_n_src,
                    n_tgt=logical_n_tgt,
                    marker=marker,
                )
                for r in self.rows
            ),
        )

    def with_text(
        self, texts: List[tuple], scores: List[float], marker: str = "[E]"
    ) -> RelationGroup:
        """info-full 操作：用完整新文本对替换。texts = [(src, tgt), ...]"""
        it = self.rows[0].init_type
        osc = self.rows[0].orig_score
        n = len(texts)
        return RelationGroup(
            relation_id=self.relation_id,
            ordinal=self.ordinal,
            rows=tuple(
                RelationRow(
                    ordinal=self.ordinal,
                    sub=0,
                    init_type=it if k == 0 else "",
                    cur_type="1:1",
                    src_text=texts[k][0],
                    tgt_text=texts[k][1],
                    score=(
                        scores[k] if k < len(scores) else (scores[0] if scores else osc)
                    ),
                    orig_score=osc,
                    n_src=n,
                    n_tgt=n,
                    marker=marker,
                )
                for k in range(n)
            ),
        )


# ═══════════════════════════════════════════════════════════════
# ChapterState — 重放后的章节状态
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ChapterState:
    """整章状态：所有 RelationGroup 的有序集合。

    groups:   按 ordinal 排序的 RelationGroup 元组
    snapshot: 原始对齐快照（始终引用，不做拷贝）

    GUI 渲染统一入口: ChapterState.rows
    """

    groups: Tuple[RelationGroup, ...]
    snapshot: AlignmentSnapshot

    # ── 构造器 ──

    @classmethod
    def from_snapshot(cls, snapshot: AlignmentSnapshot) -> ChapterState:
        """从快照构建初始 ChapterState。"""
        return cls(
            groups=tuple(
                RelationGroup.from_snapshot(i, snapshot)
                for i in range(len(snapshot.original_ops))
            ),
            snapshot=snapshot,
        )

    # ── 属性 ──

    @property
    def rows(self) -> Tuple[RelationRow, ...]:
        """所有行（按 ordinal 排序）。GUI 渲染统一入口。"""
        result: List[RelationRow] = []
        for g in self.groups:
            result.extend(g.rows)
        return tuple(result)

    # ── 查询 ──

    def group(self, ordinal: int) -> Optional[RelationGroup]:
        """按当前 ordinal 查找关系组。"""
        # groups 始终按 ordinal 排序。逐项扫描会在评分轮询逐行查询时
        # 将大章节退化为 O(n²)，两千行即可让 GUI 停顿十余秒。
        lo, hi = 0, len(self.groups)
        while lo < hi:
            mid = (lo + hi) // 2
            group = self.groups[mid]
            if group.ordinal < ordinal:
                lo = mid + 1
            elif group.ordinal > ordinal:
                hi = mid
            else:
                return group
        return None

    # ── 结构操作（返回新 ChapterState） ──

    def replace_relation(self, ordinal: int, group: RelationGroup) -> ChapterState:
        """替换指定 ordinal 的关系组。"""
        return ChapterState(
            groups=tuple(
                group if existing.ordinal == ordinal else existing
                for existing in self.groups
            ),
            snapshot=self.snapshot,
        )

    def remove_relation(self, ordinal: int) -> ChapterState:
        """删除指定 ordinal 的关系组。"""
        return ChapterState(
            groups=tuple(group for group in self.groups if group.ordinal != ordinal),
            snapshot=self.snapshot,
        )
