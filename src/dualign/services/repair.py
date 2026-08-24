"""
Dualign — RepairService: 修复操作统一入口

RepairState (不可变容器) = snapshot + repair_log
RepairService (纯函数集合) = replay + auto_repair + render_rows
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from dualign.models.state import AlignmentSnapshot, MISSING
from dualign.models.action import (
    AiProposalStore,
    RepairAction,
    project_action_to_relation_order,
)
from dualign.models.marker import (
    is_merge,
    is_deleted,
    is_approved,
    is_placeholder,
    is_edit,
    is_split,
    is_flagged,
    combine,
    needs_zero_score,
)
from dualign.models.state import ChapterState, RelationGroup, RelationRow
from dualign.core.text import op_type_str, smart_join_lines as _smart_join_lines
from dualign.services.embedding_cache import EmbeddingCache
from dualign.services.repair_policy import choose_auto_repair
from dualign.services.table_projection import (
    current_relation_is_group_scoped,
    project_table_cells,
)

SPLIT_FAILURE_UNSPLITTABLE = "文本无法进一步拆分"
SPLIT_FAILURE_REALIGN = "文本重对齐失败"
SPLIT_FAILURE_AMBIGUOUS = "拆分后的局部对齐无法唯一确定"


def review_flags_for_uncertain_regions(
    operations: list,
    regions: tuple[tuple[tuple[int, int], tuple[int, int]], ...] | list,
    *,
    alternative_operations: list | None = None,
) -> list[RepairAction]:
    """Attach review flags only to relations whose assignment is disputed.

    Region coordinates are half-open vertices in the monotone alignment lattice.
    Gap-vs-semantic changes identify the narrowest useful review locus.  If both
    paths keep every line semantic but change its counterpart, pair incidence is
    compared instead.  Older reports without an alternative path conservatively
    retain the whole-island behavior.  Flags are advisory: they neither change
    text nor choose between the paths.
    """

    def line_range(start: int, end: int) -> str:
        if start == end:
            return "无"
        if end == start + 1:
            return str(start + 1)
        return f"{start + 1}–{end}"

    def index_path(path: list):
        indexed = []
        cursor = (0, 0)
        for ordinal, operation in enumerate(path):
            source_indices, target_indices, _score = operation
            end = (
                cursor[0] + len(source_indices),
                cursor[1] + len(target_indices),
            )
            indexed.append((ordinal, cursor, end, operation))
            cursor = end
        return indexed

    def inside_region(indexed, start, end):
        return [
            item
            for item in indexed
            if start[0] <= item[1][0]
            and start[1] <= item[1][1]
            and item[2][0] <= end[0]
            and item[2][1] <= end[1]
            and item[1] != item[2]
        ]

    def matchedness(path: list):
        source = {}
        target = {}
        for source_indices, target_indices, _score in path:
            for index in source_indices:
                source[index] = bool(target_indices)
            for index in target_indices:
                target[index] = bool(source_indices)
        return source, target

    def pair_incidence(path: list):
        return {
            (source, target)
            for source_indices, target_indices, _score in path
            for source in source_indices
            for target in target_indices
        }

    indexed_ops = index_path(operations)
    alternative_indexed = (
        index_path(alternative_operations) if alternative_operations else []
    )
    current_matched = matchedness(operations)
    alternative_matched = (
        matchedness(alternative_operations) if alternative_operations else None
    )
    current_pairs = pair_incidence(operations)
    alternative_pairs = (
        pair_incidence(alternative_operations) if alternative_operations else set()
    )

    actions: list[RepairAction] = []
    for region_index, (start, end) in enumerate(regions, start=1):
        current_region = inside_region(indexed_ops, start, end)
        alternative_region = inside_region(alternative_indexed, start, end)
        current_structure = "+".join(
            op_type_str(operation[0], operation[1])
            for _index, _start, _end, operation in current_region
        )
        alternative_structure = "+".join(
            op_type_str(operation[0], operation[1])
            for _index, _start, _end, operation in alternative_region
        )
        note = (
            f"组合证据分歧区 {region_index}（A 行 {line_range(start[0], end[0])}，"
            f"B 行 {line_range(start[1], end[1])}）：当前路径 "
            f"{current_structure or '未记录'}；备选路径 "
            f"{alternative_structure or '未记录'}。请人工复核。"
        )
        region_data = {
            "start": {"source": start[0], "target": start[1]},
            "end": {"source": end[0], "target": end[1]},
        }
        selected_indices = {item[0] for item in current_region}
        if alternative_matched is not None:
            changed_source = {
                index
                for index in range(start[0], end[0])
                if current_matched[0].get(index, False)
                != alternative_matched[0].get(index, False)
            }
            changed_target = {
                index
                for index in range(start[1], end[1])
                if current_matched[1].get(index, False)
                != alternative_matched[1].get(index, False)
            }
            if not changed_source and not changed_target:
                changed_pairs = current_pairs.symmetric_difference(alternative_pairs)
                changed_source = {source for source, _target in changed_pairs}
                changed_target = {target for _source, target in changed_pairs}
            focused = {
                ordinal
                for ordinal, _op_start, _op_end, operation in current_region
                if changed_source.intersection(operation[0])
                or changed_target.intersection(operation[1])
            }
            if focused:
                selected_indices = focused

        for ordinal in sorted(selected_indices):
            action = RepairAction.make_flag(ordinal, note)
            action.source = "auto"
            action.data["reason"] = "composition_disagreement"
            action.data["uncertain_region"] = region_data
            action.data["current_structure"] = current_structure
            action.data["alternative_structure"] = alternative_structure
            actions.append(action)
    return actions


# ═══════════════════════════════════════════════════════════════
# 1. 内部纯函数：重放辅助
# ═══════════════════════════════════════════════════════════════


def _expand_text_lines(texts: List[str]) -> List[str]:
    """Expand embedded newlines while preserving the original text values."""
    expanded: List[str] = []
    for text in texts:
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                expanded.append(line if line != stripped else stripped)
            else:
                expanded.append(line)
    return expanded


def _apply_info_free(state: ChapterState, ordinal: int, marker: str) -> ChapterState:
    """info-free 操作: 只设 marker。文本在渲染时从 snapshot 重建。

    [P] 是例外：它需要将 cur_type 改为 "1:1" 并填充空侧文本，
    否则后续 [OK] 叠加时占位符文本会丢失。
    """
    g = state.group(ordinal)
    if g is None:
        return state

    if is_placeholder(marker):
        # [P]: 生成包含 ⟢MISSING⟣ 文本的 1:1 行
        s_idx, t_idx, _sc = state.snapshot.original_ops[ordinal]
        ls, lt, _, missing_side = _placeholder_info(s_idx, t_idx)
        if missing_side is not None:
            # N:0 或 0:M → 每行一个 (原文/⟢MISSING⟣, ⟢MISSING⟣/译文) 对
            if missing_side == "src":
                texts = [
                    (
                        "\u27e2MISSING\u27e3",
                        state.snapshot.tgt_text(t_idx[j]),
                    )
                    for j in range(lt)
                ]
            else:
                texts = [
                    (
                        state.snapshot.src_text(s_idx[i]),
                        "\u27e2MISSING\u27e3",
                    )
                    for i in range(ls)
                ]
            return _apply_info_full(
                state, ordinal, [t[0] for t in texts], [t[1] for t in texts], [], marker
            )
        return state.replace_relation(ordinal, g.with_marker(marker))

    # [OK] / [F] 是元标记：叠加到现有操作标记上，保留修复信息与来源前缀。
    # 例如 [M] + [AI][OK] → "[M] [AI][OK]"（AI 认可了合并，而非覆盖它）。
    # 无先前操作时保持完整标记（[OK] / [AI][OK]）原样设置。
    if is_approved(marker) or is_flagged(marker):
        existing = g.rows[0].marker if g.rows else ""
        if existing:
            new = combine(existing, marker)
            return state.replace_relation(ordinal, g.with_marker(new))
        return state.replace_relation(ordinal, g.with_marker(marker))

    return state.replace_relation(ordinal, g.with_marker(marker))


def _apply_info_full(
    state: ChapterState,
    ordinal: int,
    new_src: List[str],
    new_tgt: List[str],
    scores: List[float],
    marker: str,
) -> ChapterState:
    """info-full 操作: 完整替换为新文本对 (edit/split)。

    自动将数组元素中的换行符按行展开，过滤空行后 1:1 配对，
    确保预览表格正确拆分。
    """
    g = state.group(ordinal)
    if g is None:
        return state

    # 单侧未传文本 → 从 snapshot 取原始内容作为默认值
    # 使 AI 的 edit(new_tgt=[...]) 无需传 new_src 也能保留原文。
    if not new_src and not new_tgt:
        return state
    if not new_src:
        s_idx, t_idx, _ = state.snapshot.original_ops[ordinal]
        if s_idx:
            new_src = [state.snapshot.src_text(i) for i in s_idx]
        else:
            new_src = []
    if not new_tgt:
        s_idx, t_idx, _ = state.snapshot.original_ops[ordinal]
        if t_idx:
            new_tgt = [state.snapshot.tgt_text(j) for j in t_idx]
        else:
            new_tgt = []

    # 展开每个元素中的换行符为独立行，1:1 配对
    expanded_src = _expand_text_lines(new_src)
    expanded_tgt = _expand_text_lines(new_tgt)

    # 1:1 配对，短侧补空字符串
    n = max(len(expanded_src), len(expanded_tgt))
    texts = [
        (
            expanded_src[k] if k < len(expanded_src) else "",
            expanded_tgt[k] if k < len(expanded_tgt) else "",
        )
        for k in range(n)
    ]
    return state.replace_relation(ordinal, g.with_text(texts, scores, marker))


def _apply_multi_relation_merge(
    state: ChapterState,
    action: RepairAction,
    ordinals: List[int],
) -> ChapterState:
    """跨关系合并：删除非锚点关系，在锚点处插入合并组。

    与单关系合并的视觉一致：每个子行显示对应关系的独立文本，
    子行之间用虚线分隔，不将全部文本合并到第一个单元格。
    """
    anchor = ordinals[0]

    # 删除非锚点关系
    for ordinal in ordinals[1:]:
        state = state.remove_relation(ordinal)

    # ── 收集所有捆绑关系的初始信息 ──
    init_types: List[str] = []
    init_scores: List[float] = []
    for ordinal in ordinals:
        s_idx, t_idx, _sc = state.snapshot.original_ops[ordinal]
        init_types.append(f"关系 {ordinal}\n{op_type_str(s_idx, t_idx)}")
        init_scores.append(float(_sc))
    total = len(ordinals)
    total_src = 0
    total_tgt = 0
    for ordinal in ordinals:
        s_idx, t_idx, _sc = state.snapshot.original_ops[ordinal]
        total_src += len(s_idx)
        total_tgt += len(t_idx)

    # 构建锚点组：保留每个被捆绑关系的原始 N:M 多行布局。
    # 不同于旧版将所有文本压缩到一个单元格，新版维护每个关系的子行结构，
    # 子行间用 is_divider 的虚线分隔。
    rows: List[RelationRow] = []
    sub = 0
    for k in range(total):
        ordinal = ordinals[k]
        s_idx, t_idx, _sc = state.snapshot.original_ops[ordinal]
        n = max(len(s_idx), len(t_idx))
        for r in range(n):
            src = state.snapshot.src_text(s_idx[r]) if r < len(s_idx) else ""
            tgt = state.snapshot.tgt_text(t_idx[r]) if r < len(t_idx) else ""
            rows.append(
                RelationRow(
                    ordinal=anchor,
                    sub=sub,
                    init_type=init_types[k] if r == 0 else "",
                    cur_type=f"{total_src}:{total_tgt}" if sub == 0 else "",
                    src_text=src,
                    tgt_text=tgt or "",
                    score=float(init_scores[k]),
                    orig_score=float(init_scores[k]),
                    # 当前关系的基数属于整个 bundle，而不是某个原始关系。
                    # 原始关系边界仍由 init_type 保存，供初始列分别显示。
                    n_src=total_src,
                    n_tgt=total_tgt,
                    marker="[M]",
                    init_score_text="",
                )
            )
            sub += 1
    return state.replace_relation(
        anchor,
        RelationGroup(
            relation_id=state.snapshot.relation_id(anchor),
            ordinal=anchor,
            rows=tuple(rows),
        ),
    )


def _apply_multi_relation_edit(
    state: ChapterState,
    action: RepairAction,
    ordinals: List[int],
) -> ChapterState:
    """跨关系校订：删除非 anchor 关系，合并到 anchor RelationGroup。

    锚点行的 init_type 换行拼接所有捆绑关系的初始类型，
    cur_type/score/text 独立对应每条校订后的 1:1 文本对。
    """
    d = action.data
    new_src: List[str] = d.get("new_src_lines", [])
    new_tgt: List[str] = d.get("new_tgt_lines", [])
    scores: List[float] = d.get("inherited_scores") or d.get("split_scores", [])

    anchor = ordinals[0]

    # ── 收集所有捆绑关系的初始信息 ──
    init_types: List[str] = []
    init_scores: List[float] = []
    init_scores_total = 0.0
    init_scores_n = 0
    for ordinal in ordinals:
        s_idx, t_idx, _sc = state.snapshot.original_ops[ordinal]
        init_types.append(f"关系 {ordinal}\n{op_type_str(s_idx, t_idx)}")
        init_scores.append(float(_sc))
        init_scores_total += float(_sc)
        init_scores_n += 1
    it = "\n---\n".join(init_types)
    osc = init_scores_total / init_scores_n if init_scores_n else 0.0
    # 平均分标 *，单个分数直接显示
    ist = ""
    if len(init_scores) > 1:
        ist = f"* {osc:.0%}"

    # ── 删除非锚点关系 ──
    for ordinal in ordinals[1:]:
        state = state.remove_relation(ordinal)

    # ── 构建 anchor group：每个新文本对一行 ──
    n = max(len(new_src), len(new_tgt))
    rows: List[RelationRow] = []
    for k in range(n):
        sc = scores[k] if k < len(scores) else (scores[0] if scores else osc)
        rows.append(
            RelationRow(
                ordinal=anchor,
                sub=k,
                init_type=it if k == 0 else "",
                cur_type="1:1",
                src_text=new_src[k] if k < len(new_src) else "",
                tgt_text=new_tgt[k] if k < len(new_tgt) else "",
                score=float(sc),
                orig_score=osc,
                n_src=n,
                n_tgt=n,
                marker=action.marker,
                init_score_text=ist if k == 0 else "",
            )
        )
    state = state.replace_relation(
        anchor,
        RelationGroup(
            relation_id=state.snapshot.relation_id(anchor),
            ordinal=anchor,
            rows=tuple(rows),
        ),
    )
    return state


def _placeholder_info(s_idx, t_idx):
    """返回 (ls, lt, type_str, missing_side)。

    type_str 是真实的类型名称，如 "1:0"、"3:0"、"0:2"。
    """
    ls, lt = len(s_idx), len(t_idx)
    if ls > 0 and lt == 0:
        return ls, lt, f"{ls}:{lt}", "tgt"
    if ls == 0 and lt > 0:
        return ls, lt, f"{ls}:{lt}", "src"
    return ls, lt, None, None


# ═══════════════════════════════════════════════════════════════
# 2. replay — 纯函数重放引擎
# ═══════════════════════════════════════════════════════════════


def replay(snapshot: AlignmentSnapshot, log: List[RepairAction]) -> ChapterState:
    """纯函数重放：snapshot × log → ChapterState。

    遍历所有 action，按 info-free / info-full 分类处理。
    """
    state = ChapterState.from_snapshot(snapshot)

    for act in log:
        ordinal = act.ordinal
        if ordinal < 0 or ordinal >= len(snapshot.original_ops):
            continue

        # ── marker 由 RepairAction.marker 统一构建（含来源前缀）──
        _marker = act.marker

        # 多关系操作
        operation_indices = list(act.operation_indices)
        if len(operation_indices) > 1:
            if act.kind == "merge":
                state = _apply_multi_relation_merge(state, act, operation_indices)
                continue
            elif act.kind == "edit":
                state = _apply_multi_relation_edit(state, act, operation_indices)
                continue

        # info-free: merge, delete, placeholder, flag, ok
        if act.kind in (
            "merge",
            "delete",
            "placeholder_src",
            "placeholder_tgt",
            "flag",
            "ok",
        ):
            state = _apply_info_free(state, ordinal, _marker)

        # info-full: split, edit
        elif act.kind in ("split", "edit"):
            d = act.data
            new_src: List[str] = d.get("new_src_lines", [])
            new_tgt: List[str] = d.get("new_tgt_lines", [])
            scores: List[float] = d.get("split_scores") or d.get("inherited_scores", [])
            state = _apply_info_full(state, ordinal, new_src, new_tgt, scores, _marker)

    return state


# ═══════════════════════════════════════════════════════════════
# 3. RepairState — 不可变状态容器
# ═══════════════════════════════════════════════════════════════


def normalize_repair_log(actions) -> list[RepairAction]:
    """Collapse an append-only action stream into its effective decisions.

    External AI runners and older reports may append a newer content action
    without removing the action it supersedes. Replaying both is ambiguous and
    solidification can then try to edit a relation already deleted by the older
    action. This applies the same replacement semantics as ``RepairState.apply``
    while retaining compatible meta actions (``ok`` and ``flag``).
    """

    def targets(action: RepairAction) -> set[tuple[str, object]]:
        if action.relation_ids:
            return {("relation", relation_id) for relation_id in action.relation_ids}
        return {("ordinal", ordinal) for ordinal in action.operation_indices}

    normalized: list[RepairAction] = []
    for action in actions:
        affected = targets(action)
        if action.kind in ("ok", "flag"):
            normalized = [
                previous
                for previous in normalized
                if not (targets(previous) & affected and previous.kind == action.kind)
            ]
        else:
            normalized = [
                previous for previous in normalized if not targets(previous) & affected
            ]
        normalized.append(action)
    return normalized


@dataclass
class RepairState:
    """不可变修复状态容器。

    _snapshot + _repair_log → replay → ChapterState

    每次 apply() 返回新 RepairState，旧实例不变（支持撤销）。
    ai_proposal_store 独立于 repair_log——重置修复不会丢失 AI 建议。
    """

    _snapshot: AlignmentSnapshot
    _repair_log: List[RepairAction] = field(default_factory=list)
    _ai_proposal_store: AiProposalStore = field(default_factory=AiProposalStore)
    _current_cache: Optional[ChapterState] = field(
        default=None, init=False, repr=False, compare=False
    )

    def _project_action(self, action: RepairAction) -> RepairAction:
        """Bind identity and derive the current ordinal projection."""

        return project_action_to_relation_order(action, self._snapshot.relation_ids)

    def __post_init__(self):
        bound_actions = [self._project_action(action) for action in self._repair_log]
        self._repair_log = normalize_repair_log(bound_actions)
        self._ai_proposal_store = self._ai_proposal_store.project_actions(
            self._project_action
        )

    # ── 属性 ──

    @property
    def snapshot(self) -> AlignmentSnapshot:
        return self._snapshot

    @property
    def original_ops(self) -> list:
        return self._snapshot.ops_list

    @property
    def original_src_lines(self) -> list:
        return self._snapshot.src_list

    @property
    def original_tgt_lines(self) -> list:
        return self._snapshot.tgt_list

    @property
    def repair_log(self) -> list:
        return list(self._repair_log)

    @property
    def current(self) -> ChapterState:
        """返回当前章节状态；RepairState 不可变，因此可安全复用 replay 结果。"""
        if self._current_cache is None:
            self._current_cache = replay(self._snapshot, self._repair_log)
        return self._current_cache

    @property
    def ai_proposal_store(self) -> AiProposalStore:
        return self._ai_proposal_store

    def bind_action(self, action: RepairAction) -> RepairAction:
        """Return an action whose stable identity and ordinal projection agree."""

        return self._project_action(action)

    def set_ai_proposal_store(self, store: AiProposalStore) -> RepairState:
        """返回一个替换了 AI 建议存储的新 RepairState 实例。

        用于批量清除/重置 AI 建议场景（不可变模式下替换 store）。
        """
        return RepairState(self._snapshot, self._repair_log, store)

    # ── 操作 ──

    def apply(self, action: RepairAction) -> RepairState:
        """应用操作，返回新 RepairState。

        动作进入状态时绑定稳定关系身份；统一规范化器负责替换冲突决策。
        """
        action = self._project_action(action)
        return RepairState(
            self._snapshot,
            [*self._repair_log, action],
            self._ai_proposal_store,
        )

    def reset(self) -> RepairState:
        """重置所有修复，保留 AI 建议。"""
        return RepairState(self._snapshot, [], self._ai_proposal_store)

    def reset_relation(self, relation_id: str) -> RepairState:
        """重置指定关系的修复，保留 AI 建议。"""
        self._snapshot.operation_index(relation_id)
        return RepairState(
            self._snapshot,
            [
                action
                for action in self._repair_log
                if relation_id not in action.relation_ids
            ],
            self._ai_proposal_store,
        )

    def action_for_relation(self, relation_id: str) -> Optional[RepairAction]:
        """查找指定稳定关系身份的最新动作。"""
        self._snapshot.operation_index(relation_id)
        for action in reversed(self._repair_log):
            if relation_id in action.relation_ids:
                return action
        return None

    def relation_text_changed(self, relation_id: str) -> bool:
        """Whether current row texts/layout differ from the immutable baseline."""
        ordinal = self._snapshot.operation_index(relation_id)
        current = self.current.group(ordinal)
        if current is None:
            return True
        baseline = RelationGroup.from_snapshot(ordinal, self._snapshot)
        current_text = tuple((row.src_text, row.tgt_text) for row in current.rows)
        baseline_text = tuple((row.src_text, row.tgt_text) for row in baseline.rows)
        return current_text != baseline_text

    def flag_for_relation(self, relation_id: str) -> Optional[RepairAction]:
        """返回指定文本对当前的标记动作。"""
        self._snapshot.operation_index(relation_id)
        for action in reversed(self._repair_log):
            if relation_id in action.relation_ids:
                return action if action.kind == "flag" else None
        return None

    def without_relation_flag(self, relation_id: str) -> RepairState:
        """删除指定文本对的标记，保留正文修复和 AI 建议。"""
        self._snapshot.operation_index(relation_id)
        return RepairState(
            self._snapshot,
            [
                action
                for action in self._repair_log
                if not (relation_id in action.relation_ids and action.kind == "flag")
            ],
            self._ai_proposal_store,
        )

    # ── 构造器 ──

    @classmethod
    def from_ops(
        cls,
        original_ops: list,
        src_lines: list,
        tgt_lines: list,
        log: Optional[list] = None,
        ai_proposal_store: Optional[AiProposalStore] = None,
    ) -> RepairState:
        """从对齐结果构造 RepairState。"""
        return cls(
            AlignmentSnapshot.from_alignment(original_ops, src_lines, tgt_lines),
            list(log) if log else [],
            ai_proposal_store or AiProposalStore(),
        )


# ═══════════════════════════════════════════════════════════════
# 4. TableViewModel
# ═══════════════════════════════════════════════════════════════


@dataclass
class TableViewModel:
    """表视图数据 + 单元格合并规则。"""

    rows: List[RelationRow]
    spans: Dict[Tuple[int, int], Tuple[int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class SplitAttempt:
    """拆分尝试的结构化结果。"""

    state: RepairState
    failure_reason: str = ""

    @property
    def succeeded(self) -> bool:
        return not self.failure_reason

    @property
    def needs_review(self) -> bool:
        return self.failure_reason == SPLIT_FAILURE_AMBIGUOUS


# ═══════════════════════════════════════════════════════════════
# 5. make_table_view — 构建表视图
# ═══════════════════════════════════════════════════════════════


def current_score_slot_exists(group: RelationGroup, sub: int) -> bool:
    """Whether ``sub`` owns a visible current-score cell."""
    if sub < 0 or sub >= len(group.rows):
        return False
    if current_relation_is_group_scoped(group.rows):
        return sub == 0
    return True


def current_score_texts(group: RelationGroup, sub: int):
    """返回可编码评分槽的文本；固定分或被覆盖的子行返回 ``None``。"""
    if not current_score_slot_exists(group, sub):
        return None
    if needs_zero_score(group.rows[sub].marker):
        return None
    if current_relation_is_group_scoped(group.rows):
        return (
            _smart_join_lines([r.src_text for r in group.rows if r.src_text]),
            _smart_join_lines([r.tgt_text for r in group.rows if r.tgt_text]),
        )
    row = group.rows[sub]
    return (row.src_text or "", row.tgt_text or "")


def make_table_view(state: RepairState) -> TableViewModel:
    """Project the replayed relation rows into table spans."""
    rows = [row for group in state.current.groups for row in group.rows]

    spans = project_table_cells(rows).spans
    return TableViewModel(rows=rows, spans=spans)


# ═══════════════════════════════════════════════════════════════
# 6. RepairService — 修复操作统一入口
# ═══════════════════════════════════════════════════════════════


class RepairService:
    """所有修复操作的统一入口。GUI 和 CLI 共享同一套逻辑。"""

    # ── 公开 API ──

    @staticmethod
    def auto_repair(
        state: RepairState,
        strategy: str = "src",
        model=None,
        cache: Optional[EmbeddingCache] = None,
        unresolved_only: bool = False,
    ) -> RepairState:
        """遍历所有非 1:1 关系，按策略一键修复。

        核心原则: 每种策略保持首选侧不动，修改另一侧。
          - src-first:  保持原文不动 → 修改译文侧
          - tgt-first:  保持译文不动 → 修改原文侧
          - minimal:    不引入新信息（只合并，不拆分/插入）

        策略矩阵:
          | Type   | src-first        | tgt-first        | minimal     |
          |--------|------------------|------------------|-------------|
          | N:1    | split tgt  [S]   | merge src  [M]   | merge src [M]|
          | 1:M    | merge tgt  [M]   | split src  [S]   | merge tgt [M]|
          | 1:0    | placeholder [P]  | delete     [D]   | delete    [D]|
          | 0:1    | delete     [D]   | placeholder [P]  | delete    [D]|

        拆分需要 model。无 model 时保留原生关系，不得静默换成相反动作。
        """
        result = state
        snapshot = result.snapshot

        protected: set[int] = set()
        flags_by_ordinal: Dict[int, List[RepairAction]] = {}

        def matches_current_auto_plan(action: RepairAction, ordinal: int) -> bool:
            """Whether an older automatic action is still valid for strategy."""

            if not 0 <= ordinal < len(snapshot.original_ops):
                return False
            source_indices, target_indices, _score = snapshot.original_ops[ordinal]
            expected = choose_auto_repair(
                len(source_indices), len(target_indices), strategy
            )
            if expected is None or action.kind != expected.kind:
                return False
            if expected.kind == "split":
                return str(action.data.get("side") or "") == expected.side
            return True

        if unresolved_only:
            for action in state.repair_log:
                affected = set(action.operation_indices)
                if action.kind == "flag":
                    for affected_index in affected:
                        flags_by_ordinal.setdefault(affected_index, []).append(action)
                elif action.source == "auto" and action.kind in {
                    "merge",
                    "split",
                    "delete",
                    "placeholder_src",
                    "placeholder_tgt",
                }:
                    # Automatic structure is a strategy-derived proposal, not a
                    # user decision.  Keep it only while it still agrees with
                    # the current matrix; otherwise the loop below replaces it.
                    protected.update(
                        affected_index
                        for affected_index in affected
                        if matches_current_auto_plan(action, affected_index)
                    )
                else:
                    # ok 是明确的人工接受；正文修复则已经解决了该关系。
                    protected.update(affected)

        for ordinal in range(len(snapshot.original_ops)):
            if ordinal in protected:
                continue
            s_idx, t_idx, _sc = snapshot.original_ops[ordinal]
            ls, lt = len(s_idx), len(t_idx)

            plan = choose_auto_repair(ls, lt, strategy)
            if plan is None:
                continue

            if plan.requires_model and model is None:
                continue
            if plan.kind == "split":
                result = RepairService.apply_split(
                    result, ordinal, plan.side, model, cache=cache
                )
            elif plan.kind == "merge":
                result = RepairService.repair_merge(result, ordinal)
            elif plan.kind == "delete":
                result = RepairService.repair_delete(result, ordinal)
            elif plan.kind == "placeholder_src":
                result = RepairService.repair_placeholder(result, ordinal, "src")
            elif plan.kind == "placeholder_tgt":
                result = RepairService.repair_placeholder(result, ordinal, "tgt")

            applied_action = result.action_for_relation(
                result.snapshot.relation_id(ordinal)
            )
            if applied_action is not None and applied_action.source == "auto":
                applied_action.data["strategy"] = strategy

            # flag 表示仍待关注，而不是阻止机器提出结构修复。自动修复会先
            # 替换同一关系的操作，因此在其后重新附加原标记，保留审阅意图。
            for flag in flags_by_ordinal.get(ordinal, []):
                result = result.apply(flag)

        return result

    # ── 单步修复 ──

    @staticmethod
    def repair_merge(state: RepairState, ordinal: int) -> RepairState:
        """合并文本对，仅设 marker。"""
        s_idx, t_idx, _sc = state.snapshot.original_ops[ordinal]
        sub_count = max(len(s_idx), len(t_idx))
        return state.apply(
            RepairAction.make_merge(ordinal, sub_count=sub_count, source="auto")
        )

    @staticmethod
    def repair_delete(state: RepairState, ordinal: int) -> RepairState:
        """删除文本对。"""
        return state.apply(RepairAction.make_delete(ordinal, source="auto"))

    @staticmethod
    def repair_placeholder(state: RepairState, ordinal: int, side: str) -> RepairState:
        """占位符：保留非空侧，空侧填 MISSING。"""
        if side == "src":
            action = RepairAction.make_placeholder_src(ordinal, source="auto")
        else:
            action = RepairAction.make_placeholder_tgt(ordinal, source="auto")
        return state.apply(action)

    # ── 拆分 ──

    @staticmethod
    def apply_split(
        state: RepairState,
        ordinal: int,
        side: str,
        model=None,
        cache: Optional[EmbeddingCache] = None,
    ) -> RepairState:
        """拆分文本对；失败时保持原状态。"""
        return RepairService.try_split(state, ordinal, side, model, cache).state

    @staticmethod
    def try_split(
        state: RepairState,
        ordinal: int,
        side: str,
        model=None,
        cache: Optional[EmbeddingCache] = None,
    ) -> SplitAttempt:
        """硬拆分一侧，再用完整覆盖的局部 MDL 重新对齐两侧。

        side: 要拆分的一侧 ("src" 或 "tgt")。通常是少行侧。

        局部语法只包含 1:1 / N:1 / 1:N。gap 和一般 N:M 不进入候选图；
        DLD/posterior 决定结构复杂度，同复杂度内由完整拼接路径决定边界。
        复杂度分歧或完整路径精确并列时保留原关系并请求复核。
        """
        from dualign.core.punctuation import UniversalSplitter
        from dualign.services.local_realign import (
            LOCAL_REALIGN_NEEDS_REVIEW,
            align_split_region,
            materialize_local_path,
        )

        snapshot = state.snapshot
        s_idx, t_idx, _sc = snapshot.original_ops[ordinal]

        raw_src = [snapshot.src_text(i) for i in s_idx]
        raw_tgt = [snapshot.tgt_text(j) for j in t_idx]

        # 1. 硬分割拆分侧
        if side == "src":
            parts: List[str] = []
            for line in raw_src:
                sub = UniversalSplitter.hard_split(line)
                parts.extend(sub if sub else [line])
            if len(parts) <= len(raw_src):
                return SplitAttempt(state, SPLIT_FAILURE_UNSPLITTABLE)
        else:
            parts: List[str] = []
            for line in raw_tgt:
                sub = UniversalSplitter.hard_split(line)
                parts.extend(sub if sub else [line])
            if len(parts) <= len(raw_tgt):
                return SplitAttempt(state, SPLIT_FAILURE_UNSPLITTABLE)

        if model is None:
            return SplitAttempt(state, SPLIT_FAILURE_REALIGN)

        # 始终通过 CachedEncoder 查缓存（如果 cache 可用），否则盲编码。
        if cache is not None and model is not None:
            from dualign.services.cached_encoder import CachedEncoder

            cenc = CachedEncoder(model, cache)
            encode_fn = cenc.encode
        else:
            encode_fn = model.encode

        # 2. 两侧共同进入局部无 gap 对齐；拆分动作不冻结另一侧。
        src_in = parts if side == "src" else raw_src
        tgt_in = raw_tgt if side == "src" else parts
        try:
            combined = encode_fn(src_in + tgt_in)
            src_emb = combined[: len(src_in)]
            tgt_emb = combined[len(src_in) :]
            decision = align_split_region(
                src_in,
                tgt_in,
                src_emb,
                tgt_emb,
                encode_fn,
            )
        except (RuntimeError, TypeError, ValueError):
            return SplitAttempt(state, SPLIT_FAILURE_REALIGN)
        if decision.status == LOCAL_REALIGN_NEEDS_REVIEW:
            return SplitAttempt(state, SPLIT_FAILURE_AMBIGUOUS)
        try:
            new_src, new_tgt, scores = materialize_local_path(
                decision.operations,
                src_in,
                tgt_in,
            )
        except RuntimeError:
            return SplitAttempt(state, SPLIT_FAILURE_REALIGN)

        # 3. 每条局部语义关系展平为一个双边非空输出行。
        action = RepairAction.make_split(
            ordinal,
            new_src_lines=new_src,
            new_tgt_lines=new_tgt,
            split_scores=scores,
            side=side,
            source="auto",
        )
        return SplitAttempt(state.apply(action))

    # ── 跨关系操作 ──

    @staticmethod
    def repair_bundle_relations(
        state: RepairState,
        ordinals: List[int],
    ) -> RepairState:
        """跨关系合并：将多个连续关系捆绑为一个文本对。

        ordinals 必须连续。非锚点关系被移除，原文/译文均合并到锚点关系。
        统一为 kind="merge"。

        自动消除占位、删除、拆分操作；但保留 edit 操作不撤销。
        """
        if len(ordinals) < 2:
            return state

        # 选择性重置：消除 placeholder/delete/split，保留 edit
        for ordinal in ordinals:
            relation_id = state.snapshot.relation_id(ordinal)
            action = state.action_for_relation(relation_id)
            if action is None:
                continue
            kind = action.kind
            # edit 操作保留，其余（placeholder_src/tgt, delete, split, ok, flag, merge）均重置
            if kind not in ("edit",):
                state = state.reset_relation(relation_id)

        action = RepairAction(
            kind="merge",
            operation_indices=tuple(ordinals),
        )
        return state.apply(action)

    @staticmethod
    def valid_operations(state: RepairState, ordinal: int) -> Dict[str, bool]:
        """返回该关系可用的操作集合。GUI 据此启用/禁用按钮和菜单项。

        规则（单关系）：
          N:1 (ls>1,lt==1): merge=Y, split=tgt, edit=Y
          1:M (ls==1,lt>1): merge=Y, split=src, edit=Y
          1:0 (ls>0,lt==0): merge=N, split=N, edit=Y
          0:1 (ls==0,lt>0): merge=N, split=N, edit=Y
          1:1:               merge=N, split=N, edit=Y

        多关系选中时 merge 始终可用（捆绑合并）。
        """
        snapshot = state.snapshot
        s_idx, t_idx, _sc = snapshot.original_ops[ordinal]
        ls, lt = len(s_idx), len(t_idx)

        is_non11 = ls != 1 or lt != 1
        is_10 = ls > 0 and lt == 0
        is_01 = ls == 0 and lt > 0

        # 已有操作时，某些操作被覆盖
        action = state.action_for_relation(snapshot.relation_id(ordinal))
        has_action = action is not None

        ch = state.current
        g = ch.group(ordinal)
        is_11_now = g is not None and all(r.cur_type == "1:1" for r in g.rows)
        marker = g.rows[0].marker if g else ""
        resolved_to_11 = is_merge(marker) or is_placeholder(marker)
        is_del = is_deleted(marker)
        already_ok = is_approved(marker)

        return {
            "merge": is_non11 and not is_10 and not is_01,
            "split_src": ls > 1 and lt == 1,
            "split_tgt": ls == 1 and lt > 1,
            "edit": True,
            "ok": (is_11_now or resolved_to_11 or is_del) and not already_ok,
            "flag": True,
            "delete": True,
            "placeholder": is_10 or is_01,
            "reset": has_action,
        }

    # ── 跨关系校订 ──

    @staticmethod
    def repair_multi_edit(
        state: RepairState,
        ordinals: List[int],
        new_src_lines: List[str],
        new_tgt_lines: List[str],
        scores: Optional[List[float]] = None,
    ) -> RepairState:
        """跨关系校订：将多个连续文本对捆绑为一个编辑组。

        ordinals 必须连续。非锚点关系被删除，锚点存放合并后的文本。
        """
        if len(ordinals) < 2:
            return state

        anchor = ordinals[0]
        action = RepairAction.make_edit(
            anchor,
            operation_indices=ordinals,
            new_src_lines=new_src_lines,
            new_tgt_lines=new_tgt_lines,
            inherited_scores=scores or [],
        )
        return state.apply(action)

    # ── 渲染/导出 ──

    @staticmethod
    def render_rows(
        state: RepairState,
    ) -> Tuple[List[str], List[str]]:
        """从 RepairState 重建 src/tgt 文本输出。

        规则:
          [D]: 跳过不输出
          [M]: 从 snapshot 取原始文本 + _smart_join 合并一侧
          [E]/[S]: 取 row.src_text / row.tgt_text
          [P]: 空侧输出 MISSING
          无标记: 从 snapshot 取原始文本
        """
        ch = state.current
        snapshot = state.snapshot

        src_out: List[str] = []
        tgt_out: List[str] = []

        for g in ch.groups:
            if not g.rows:
                # 空关系组（可能来自跨关系操作后的残留），跳过
                continue
            r0 = g.rows[0]
            marker = r0.marker
            s_idx, t_idx, _sc = snapshot.original_ops[g.ordinal]

            if is_deleted(marker):
                continue  # 跳过删除

            if is_merge(marker):
                # merge: 原文译文均合并为一行
                # 检查是否为跨关系合并（bundle merge）
                action = state.action_for_relation(g.relation_id)
                operation_indices = action.operation_indices if action else ()
                if len(operation_indices) > 1:
                    # 跨关系合并：收集所有被捆绑关系的文本再拼接
                    src_parts: List[str] = []
                    tgt_parts: List[str] = []
                    for si_int in operation_indices:
                        if si_int >= len(snapshot.original_ops):
                            continue
                        ss, tt, _ = snapshot.original_ops[si_int]
                        for i in ss:
                            t = snapshot.src_text(i)
                            if t:
                                src_parts.append(t)
                        for j in tt:
                            t = snapshot.tgt_text(j)
                            if t:
                                tgt_parts.append(t)
                    src_line = _smart_join_lines(src_parts) if src_parts else ""
                    tgt_line = _smart_join_lines(tgt_parts) if tgt_parts else ""
                else:
                    # 单关系合并：直接取当前关系的原始索引
                    src_line = _smart_join_lines([snapshot.src_text(i) for i in s_idx])
                    tgt_line = _smart_join_lines([snapshot.tgt_text(j) for j in t_idx])
                src_out.append(src_line)
                tgt_out.append(tgt_line)

            elif is_edit(marker) or is_split(marker) or is_placeholder(marker):
                # info-full / 占位符: 取内联文本，空侧显示 MISSING
                for row in g.rows:
                    src_out.append(row.src_text or MISSING)
                    tgt_out.append(row.tgt_text or MISSING)

            else:
                # 无标记: 直接从 group rows 输出（始终等行数，短侧补空）
                for row in g.rows:
                    src_out.append(row.src_text or "")
                    tgt_out.append(row.tgt_text or "")

        return src_out, tgt_out
