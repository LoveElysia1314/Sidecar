# 对齐表单元格归属审查

本文审查主审校表、AI 建议七列表和无关系平坦预览。文件选择、批处理列表等普通控件不含
对齐关系语义，不在本文范围内。

## 1. 开发意图的重建

现有实现虽然以 `AlignedRow` 为物理载体，但界面实际同时展示三层事实：

1. **初始事实**：正式对齐器产生的原始关系、原始评分和原始异常；修复后仍保留。
2. **当前事实**：当前关系结构、当前评分和当前文本异常；随重放结果变化。
3. **处理事实**：合并、拆分、校订、删除、占位、标记、通过及来源；它描述用户或 AI
   做过什么，不等于文本本身的异常。

因此一行并不是一个完整关系，一个 snap 也不总是一个显示事实。原生 `N:1`、单 snap
合并和跨 snap 合并可以由多行共同表示一个当前关系；拆分和校订则可以在一个初始关系下
产生多个独立的当前 `1:1`。原有代码试图通过 span、空字符串、`sub == 0` 和 marker
分别恢复这些作用域，意图合理，但事实归属被分散到了多个渲染函数。

## 2. 七列语义

| 列 | 内容来源 | 正确归属 | 主要显示行为 |
| --- | --- | --- | --- |
| 关系 | anchor snap / 展示组 | 当前展示组 | 整组一格；用于焦点、选择和定位 |
| 初始类型 | 原始 operation | 原始 snap 片段 | 跨 snap 合并时各片段分别保留；复合标签按最严重关系着色 |
| 初始评分 | 原始 operation | 原始 snap 片段 | 普通 bundle 分别显示；跨 snap 原子校订显示带 `*` 的平均值 |
| 当前状态 | marker + 当前异常 | 当前关系 | 原生非对称关系和 merge 为整组；split/edit 后的各行独立 |
| 当前评分 | ScoreManager | 与当前状态相同 | 关系级只请求一个完整块评分；独立 `1:1` 各自请求 |
| 文档 A | 当前行文本 | 当前关系的 A 成员 | 短侧整组一格，长侧逐成员；merge 内部边界画虚线 |
| 文档 B | 当前行文本 | 当前关系的 B 成员 | 与 A 对称 |

评分列有两种纯显示模式：明细模式显示百分比，紧凑模式显示窄色带。pending/loading/failed
是评分生命周期，不是对齐状态。删除行统一删除线，筛选带入的上下文统一灰色斜体；二者是
整行样式覆盖。橙色角标表示当前单元格文本相对初始文本发生了实际变化。操作色还承担
“该侧受处理影响”的强调作用，不能与橙色角标简单合并为一个布尔量。

## 3. 操作后的归属

| 情况 | 初始列 | 当前状态/评分 | 文本列 |
| --- | --- | --- | --- |
| 原始 `1:1` | 单行 | 单行 | 单行 |
| 原始 `N:1 / 1:N / gap` | 原始关系整组 | 当前关系整组 | 短侧跨满，长侧逐行 |
| 单 snap `[M]` | 原始关系整组 | 合并关系整组 | 保留可读的逐行文本，内部虚线；导出时智能拼接 |
| 跨 snap `[M]` | 每个原始 snap 独立 | bundle 整体 | 按 bundle 总基数决定短侧，当前评分编码完整块 |
| `[S] / [E]` | 初始关系整组 | 每个新 `1:1` 独立 | 每行独立；允许拆分后递归产生新的合并关系 |
| `[D]` | 保留 | 删除状态 | 保留可审阅文本并加删除线，导出跳过 |
| `[P]` | 保留 | 占位状态 | 只有缺失侧发生实际文本变化 |
| `[F] / [OK]` | 保留 | 标记/通过状态 | 不改变文本；可用操作色强调处理状态 |

AI 建议表沿用相同归属规则，但同一 snap 可以有多条建议，所以展示组必须是
`(snap, proposal)`，不能只使用 snap。平坦预览故意取消关系归属：两侧分别按当前输出顺序
铺开，以便暴露累计错位；它不应复用七列表的 span。

## 4. 本轮确认并修复的问题

1. 跨 snap merge 的初始片段被错误用于当前状态、当前评分和文本跨度。
2. 跨 snap merge 保存的是各片段基数而不是 bundle 总基数，当前评分也曾逐子行请求。
3. 主表和 AI 表各有一处把 `(rowSpan, colSpan)` 的列跨度当成行跨度。
4. 相同 snap 的多条 AI 建议会被误合为一个展示组。
5. `snap N + N:M` 复合展示字符串无法被类型着色器解析，gap/non-1:1 会错误退回灰色。
6. 当前状态文字来自当前异常，但颜色曾错误使用筛选得到的初始异常。
7. 跨 snap 校订已保存带 `*` 的平均初始评分文本，但主表从未显示。
8. 平坦预览的跨 snap merge 只读取 anchor 原始 operation，遗漏 bundle 其余文本。
9. `[D] / [P]` 在模型层定义为当前评分 0，评分管理器却会在操作后重新编码并覆盖零分。

## 5. 归属投影

本轮加入纯函数 `project_table_cells(rows)`：先为每格赋予事实 owner，再由连续相同 owner
统一推导：

- `spans`：需要跨行合并的锚点和行数；
- `covered_cells`：Qt 不应再次创建内容或评分请求的格；
- `divider_cells`：同一 merge 关系内、文本成员不同的内部边界。

主表和 AI 表现在共同消费这一个投影。它不是第二套可变状态机：唯一可变历史仍是
`RepairState = snapshot + action log`，投影只是重放结果到表格的确定性函数。这比维护一套
“格子现在处于什么状态”的事件状态机更简单，也不存在状态同步问题。

## 6. 尚未完全统一的部分

当前投影已统一结构行为，但没有贸然接管内容和样式：

- `init_type` 仍兼作语义类型和展示标签，原始片段边界仍以非空 anchor 表示；长期应加入
  显式 `initial_segment_id` 和纯 `relation_type`，不再解析字符串。
- 主表与 AI 表仍分别创建 `QTableWidgetItem`；下一阶段可引入纯 `CellSpec(value, owner,
  score_key, style, tooltip)`，再由两个薄 Qt adapter 渲染。
- AI 建议若提出跨 snap merge，预览评分可能是继承分而非重新编码的完整块分；没有编码器
  时应显示 pending/unknown，而不应伪造精确值。
- 主表与基表各有一份 deficit-fill 行高实现；可在 CellSpec 稳定后统一，但它只影响布局，
  不应与关系状态迁移同时改写。
- `compute_text_colors` 实际表达“操作强调侧”，名字容易被误读为“文本真的变化”；真正的
  内容变化由 `has_snap_text_changed` 决定。二者应在未来 CellSpec 中分别命名。

## 7. 后续收敛条件

只有在以下等价测试齐备后，才适合让 CellSpec 接管内容和样式：原始 `1:1/N:1/1:N/gap`、
单/跨 snap merge、单/跨 snap edit、split、placeholder、delete、flag、ok、AI 多提议、
上下文行、评分四态、明细/紧凑模式和主题切换。归属投影本身应保持纯函数、无 Qt、无编码
请求、无阈值；任何显示规则都必须能回答“该格描述哪个事实”，而不是回答“这个案例看起来
应该合并吗”。

## 8. snap 与关系身份

审查固化链路后，结论是：**关系身份应与归属投影统一接口，但不应由投影拥有**。投影是
可丢弃的视图；修复日志需要持久身份。当前 `snap_index` 同时承担：

1. `snapshot.original_ops` 的数组位置；
2. 修复日志、评分、AI 建议的主键；
3. GUI 展示编号和选择组；
4. 跨关系操作的 anchor，而其余来源另存于 `orig_snaps`。

这种复用解释了为何运行期不漂移，却迫使固化阶段维护 `operation_map`、组合位置映射、
`orig_snaps` 重写、评分 key 重写和 AI 建议重锚。

项目实际上已经具备更好的基础：`AlignmentLink / BlockLink` 有稳定 `id`，
`PairEditingState` 的正文块也有稳定 block ID；merge 保留第一个 link ID，split 产生后缀 ID。
迁移前的复杂性主要来自 GUI/报告使用旧 `RepairState + op_index`，固化时才临时转入 native
pair model，保存后又把稳定 ID 丢回位置数组。

建议的收敛模型为：

```text
RelationRecord
  id                    # 报告期内不可变，如 L000123
  origin_ids            # 跨关系操作来源；普通关系为自身
  document_a_block_ids
  document_b_block_ids
  ordinal               # 当前顺序中的派生位置，不是身份

RepairAction
  relation_ids          # 替代 op_index + data.orig_snaps

CellProjection
  display_group_id      # relation id，或 (relation id, proposal id)
  cell owner / score slot / span / divider
```

报告的 `ops` 应保存 link ID，repair log、scores、AI proposals 以 relation ID 为键。GUI 仍可
显示连续数字，但数字只由当前有序 links 枚举产生。固化时直接在 `PairEditingState` 上操作；
重新对齐后，内容两侧完全相同且唯一的关系继承旧 ID，边界或正文已改变的关系获得新 ID。
后者仍需要现有的“精确唯一关系映射”，因为重新对齐可能改变关系边界；稳定 ID 不能凭空
证明新旧语义相同。但不再需要把所有派生状态先映射为新数组位置再组合映射。

这项迁移预计能删除或显著缩小：`orig_snaps` 兼容分支、`operation_map` 的大部分消费者、
字符串评分键解析、`link_id_for_operation()` 位置转换，以及 GUI 多处按 snap 扫描的逻辑。
它不能与本轮显示修复混为一个补丁：需要报告格式版本、RepairAction 兼容读取、会话恢复、
CLI、AI proposal store、solidify/pair_save 和 GUI 一起切换，并对部分固化、merge 后 split、
删除、重复文本无法唯一重锚等场景做事务测试。

因此推荐下一阶段以 native `PairEditingState` 成为唯一运行状态为目标迁移；不要把更多身份
逻辑塞进 `TableCellProjection`。本轮投影已支持显式 `display_group_id`，可直接作为该迁移的
视图端接口。

### 8.1 迁移进度（2026-08-24）

第一阶段兼容层已经落地：

- `ops` 持久化稳定关系 ID，旧报告按顺序派生兼容 ID；
- `AlignmentSnapshot` 同时保存关系 ID 与当前顺序，并提供双向投影；
- `RepairAction.relation_ids` 成为动作身份，进入 `RepairState` 时由身份派生兼容的
  `op_index/orig_snaps`；
- GUI 会话、CLI 缓存、原生 `AlignmentPair` 和固化入口共享报告中的 ID；
- 固化重对齐只让“双侧内容完全相同且新旧均唯一”的关系继承 ID，新关系不复用已消失
  的 ID。

`AiProposalStore` 随后也已改为按 `relation_id` 分组：接受、拒绝和恢复只接收身份已绑定的
动作，不再同时传入一份可能冲突的 snap 编号；旧报告中的数字字典键在进入 `RepairState`
时一次性转换。状态重建会复制并投影 proposal store，因而撤销栈中的旧状态不再与新状态
共享可变的建议对象。

持久评分也已迁入 `RelationScoreCache`：内存键为 `(relation_id, sub)`，报告按关系 ID 嵌套
存储，旧 `snap_sub` 字符串只在读取边界解析一次。固化不再重写评分位置键，只保留最终
仍存在且正文未改变的关系身份。异步 `ScoreManager` 的位置键只是当前 GUI 作业地址，并已
移除 `snap * 1_000_000 + sub` 这一不必要的整数编码和跨度假设。

核心回放对象也已收敛为 `RelationRow/RelationGroup`。关系组同时携带稳定 `relation_id` 和
当前 `ordinal`，替换、删除与 GUI 评分投影显式使用 ordinal；旧 `SnapGroup.snap_i` 接口和
兼容别名均已删除。主表 `RelationRow/TableRow`、AI 建议行和通用表格基类现统一暴露
`ordinal`，`TableRow.op_index` 重复别名也已删除。选择、异常与 AI 外部短地址仍可使用数字，
但进入单元格归属投影后只有一种当前位置字段，不再出现 `snap_index/index/op_index` 混称。

跨关系动作的位置表示也已收敛：`RepairAction.operation_indices` 是唯一显式位置投影，
`data` 不再混入 `orig_snaps`。所有重放、GUI 聚焦、异常投影、自动修复和固化消费者直接
读取同一属性；旧字段只在报告/原始动作反序列化边界转换。由此删除了各处重复的
“`orig_snaps` 否则 `op_index`”解析、去重和异常容错分支。下一步仍应让新动作尽早绑定
`relation_ids`，使 `operation_indices` 只服务 GUI ordinal 和旧接口，而非业务判断。

固化链随后已完全删除公开 `operation_map`、组合位置映射和 `changed_operations`。未处理的
修复、AI 建议与评分现在采用同一迁移规则：目标 `relation_id` 仍在最终关系集合且未被本次
固化改变才保留；运行期 `operation_indices` 由最终 ID 顺序一次性投影。唯一仍需要的
新旧关系比较是 `_exact_relation_map`：它用于判断重对齐后哪些完整双侧内容唯一且完全相同，
从而决定关系 ID 是否可继承，而不是迁移派生状态。

原 `SnapState` 体系也不再维护“先从快照 build、再从修复状态 refresh”的两份派生状态。
它已改为 `RelationStatus` 纯投影：唯一输入是 `RepairState`，一次计算原始事实、当前文本与
操作历史；GUI 异常筛选和 AI `RelationReviewInfo` 共用同一结果。AI 工具协议仍展示数字
`id`，但它只是本次上下文中的 ordinal 短地址，不写入持久状态，也不参与固化身份判断。

曾用于探索 native pair model 的 `pair_editing_adapter.py` 与 `change_set.py` 已移除。二者没有
GUI、CLI、保存或固化消费者，只在专属测试中互相构成另一套动作回放，并且对 merge/delete
的处理与正式固化策略不同。现在唯一写正文的路径是 `build_solidification_plan()`：
`RepairState` 负责可逆审阅投影，`PairEditingState` 只在固化边界承载自然文档块和关系编辑。
这两者是不同层次的表示，不再用第二个“工作状态”适配器假装统一。

动作覆盖规则也已只保留在 `normalize_repair_log()`：动作绑定身份后按 relation ID 集合判断
冲突，`apply()` 不再另写一套只检查 anchor ordinal 的过滤逻辑。查询、单项重置和清除
标记同样从任一目标关系都能找到跨关系动作，避免非 anchor 关系残留不可见操作。

`RepairState` 的业务查询入口现已只接受 relation ID：`action_for_relation()`、
`reset_relation()`、`flag_for_relation()`、`without_relation_flag()` 和
`relation_text_changed()`。GUI 在选择边界把临时 ordinal 投影成 ID；回放状态内部不再公开
一套名字和参数都暗示位置是身份的 `*_for_op` 接口。

GUI 异常列表也由无类型字典收敛为不可变 `RelationAnomaly` 投影，同时携带 relation IDs 与
当前 ordinals。导航、筛选、撤销定位和全章 AI 上下文直接读取 `ordinals`，删除了各处
“`snap_indices` 否则 `snap_index`”的重复容错；异常字段拼写错误现在会在代码/测试中直接
暴露，而不会静默退化为缺失值。

GUI 的唯一焦点管理器也已改用 `focused_ordinal/selected_ordinals/force_show_ordinals`，
并通过 `relation_focused` 信号同步主表、审阅导航和 AI 预览。通用表格的焦点入口统一为
`focus_ordinal()`；没有保留旧 `go_to_snap/select_snaps/focus_snap` 别名。

`RepairAction` 的位置投影也只保留 `operation_indices`，删除了原样转发的
`target_operation_indices` 属性。运行期消费者现在对“稳定身份用 relation IDs、当前地址用
operation indices”各只有一个字段名。

新报告进一步停止持久化位置投影：动作和 AI 建议只写 `relation_ids`，保存边界还会把旧式
建议键、动作位置与平坦评分键规范化成当前 ID 格式。`op_index/operation_indices/orig_snaps`
只允许作为旧报告输入。ID 到当前 ordinal 的投影也提取为
`project_action_to_relation_order()`，由回放和固化共用；这同时修复了固化读取 ID-only
跨关系动作时误用占位位置的问题。

审阅状态的命名也已收敛：审批管线只公开 `APPROVAL_PROPOSED`，持久化值仍为历史兼容的
`"auto"`；初始异常与当前异常分别显式使用 `initial_anomaly_types` 和
`current_anomaly_types`。删除 `APPROVAL_AUTO` 和含义含混的 `anomaly_types` 别名后，调用方
无法再把“拟修复”误读成“自动批准”，也不能无意间混用初始事实与当前状态。

旧动作格式的解释现集中在 `canonicalize_action_payload()` 和 `RepairAction.from_dict()` 两个
反序列化入口。普通报告保存与固化保存不再分别实现位置回退；二者都会把
`operation_indices/orig_snaps/op_index` 转成稳定 ID 并清除旧字段。正常构造动作时也不再从
`data` 偷读位置、身份或来源，因此历史格式不会渗入运行时业务模型。所有 `make_*` 工厂
进一步共用一个元数据提取入口，确保 `source/timestamp/relation_ids/operation_indices` 与编辑
内容严格分层；这也删除了各工厂原先重复且隐含依赖 `__post_init__` 的参数搬运。

GUI 审阅层已删除无人使用的摘要兼容方法、空按钮样式常量和旧质量门控转发函数。章节摘要
与 AI 建议导航分别显式使用 `chapter` 和 `ordinal`，不再用 `filename` 或 `snap` 暗示并不存在
的文件身份/持久位置；仍保留的 `snap` 名称因此更容易定位为下一阶段真正需要迁移的接口。

`RepairAction` 最终也不再同时存储 `op_index` 与 `operation_indices[0]`。动作只保存非空的
`operation_indices`，只读 `ordinal` 属性从首项派生 anchor；所有回放、AI、GUI 与固化代码
都使用这两个无冲突视图。`op_index` 现在只出现在旧 JSON 的规范化/反序列化代码及对应兼容
测试中，新动作的序列化也不会再生成它。

评分服务现以 `(ordinal, sub)` 为唯一作业地址，并公开 `invalidate_ordinals()`；跨关系合并也
统一命名为 `repair_bundle_relations()/do_bundle_relations()`。二者都只是当前会话投影，不再把
位置集合包装成名为 snap 的第二种领域对象。

GUI、编码线程和 `create_alignment_pair()` 对唯一工作报告的称呼已统一为 `report_path`；窗口
并只维护 `_report_path/_report_file_hash/_report_file_present`。`FilePair` 中无人使用的
`source_path/target_path/alignment_path` 只读别名已删除。历史批量固化清单中的
`alignment_path` 仍只在其读取边界作为旧键接受。
