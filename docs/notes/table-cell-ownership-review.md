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
兼容别名均已删除。主表关系行、AI 建议行和通用表格基类现统一暴露
`ordinal`；选择、异常与 AI 外部短地址仍可使用数字，
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

筛选投影现名为 `RelationFilter`，工作区面板的空 `set_gating()` 已删除。表格层原先重复的
`compute_text_colors()` 与 `has_snap_text_changed()` 已拆成唯一事实函数
`relation_text_changes()` 和一层纯视觉着色规则：edit/split 的正文比较只实现一次，而
merge/marker 的强调色不会被误当成正文确实发生变化。Snap 列宽/列索引接口也改为 relation。

主题颜色不再复制成模块级静态别名，所有 GUI 消费者统一读取动态 `ThemeManager`，避免主题
切换后一部分控件仍持有旧色。设置读写也从 `_load_history/_save_history` 收敛为配置快照和
`_schedule_settings_save/_save_settings`，调用方不再直接访问 `DualignConfig._data`。

标记的视觉组合规则只保留一份：生产回放原先私有的 `_combine_meta()` 已下沉为
`marker.combine()`，统一处理 `[OK]/[F]` 互斥、去重和 `[AI]` 来源保留。审阅生命周期则由
`normalize_repair_log()` 统一投影：正文动作保留 `[F]` 并使旧 `[OK]` 失效，显式 `ok` 解除
`[F]`，再次 flag 重新开启事项。静态未使用代码审计
随后清除了回放中的多余导入，80% 置信度以上不再报告未使用的生产符号。

同一轮审计还删除了从未接入界面的折叠容器与分数渐变图例、失去入口的单关系自动修复
分派、被 `report_matches_alignment()` 覆盖的 provenance 比较函数，以及已无消费者的内容行
分段辅助函数。这些符号既没有运行时引用，也没有承担文件格式兼容职责；保留它们只会让人
误以为项目仍有第二套界面或报告判定路径。兼容代码仍严格保留在旧报告和旧批处理清单的读取
边界，没有用“清理未引用代码”为由删除可读取历史数据的能力。

GUI 控制层现在也只用 ordinal 表示关系的会话位置：审阅控制器公开
`_current_ordinal/_selected_ordinals/analyze_relations`，评分失效、批量删除、撤销焦点与关系
导航均采用同一术语。原 `SnapIndicator` 已改为 `RelationIndicator`。这里没有改名
`AlignmentSnapshot`，因为它仍准确表示报告所绑定的不可变输入快照；也没有改 AI 工具向模型
展示的 `snap N`，它是一次 Agent 会话内的人类可读短地址，不是第二套持久身份。

公开 GUI 组件也缩减到实际接线的界面：删除了空壳 `ConfigDialog`、已被当前文件队列取代的
`FileListPanel`、旧 change-set 专用的 `ChangeReviewDialog`，以及没有挂入主窗口的
`ActivityBar/ActivityButton`。现有 `AgentConfigDialog`、固化预览和 `DockPanelHelper` 分别仍有
明确入口，因此保留。这样 `dualign.gui` 的惰性公开 API 不再宣称支持已经不存在的交互流程。

审阅领域模型中旧的 `auto_note` 字符串生成/解析和独立关系预览也已删除。当前状态由
`project_relation_statuses()` 一次性投影为结构化字段，正文预览由 RepairState/表格行投影负责；
继续保留可往返解析的说明字符串会形成第二套状态协议。配置模块中三个无消费者的旧模型名、
报告版本号和 UI session 路径同样移除；实际嵌入配置兼容仍留在 embedding 服务的输入边界。

Marker 模块也不再同时提供“解析成布尔字典”“逐项语义查询”和“测试专用中文显示”三套
读取方式。生产代码统一使用 `has_tag/is_*` 语义查询，组合仍只有 `combine()`；无人消费的
`parse/get_tags/get_source/get_display_text/is_from_ai/is_ai_reviewed` 及其自证式测试已删除。
`[AI]` 是否存在与是否位于前缀不再由两个近义函数给出可能不同的答案。

表格数据路径最终只保留 `RelationRow`。原 `TableRow` 逐字段复制相同数据，合并“重建”只是
再复制一次，删除分支则重复执行 `with_marker()` 已完成的分数归零。`make_table_view()` 现在
直接展平不可变 `ChapterState` 关系行并计算单元格投影，不再制造第二种可变行对象；GUI 也
直接标注并消费 `RelationRow`。

info-full edit/split 的行构造也已统一调用 `RelationGroup.with_text()`，删除 repair 服务中的
逐字段复刻。收敛时同时发现该旧修改器会把多行的 `sub` 全部写成 0；现已改为连续子序号并
增加多行断言。无人读取的 `RelationRow.is_divider` 与同名 marker 转发函数一并移除，虚线
归属继续由统一单元格投影决定。

正文落盘也只保留固化事务。`RepairService.render_to_files()` 会绕过报告重锚、哈希冲突检查
与双文件原子保存，只有一个已经使用旧 `op_index` API 的 AI demo 和自证式单元测试调用；
该方法、过时 demo 及无人调用的 `apply_ai_actions/is_dirty/undo` 便利接口现已删除。
`render_rows()` 仍作为报告物化的纯投影保留，但不再自行写文件。

单元格投影的可选首列参数也从 `snap_col` 改为 `relation_col`。它的 owner 本来就是当前关系，
且与 `ordinal` 一起决定跨行范围；旧名会错误暗示该列由不可变快照对象拥有。初始列仍按显式
初始关系片段投影，因此跨关系合并的“多个初始片段、一个当前关系”语义未变。

`compute_spans()` 的薄包装也已移除。跨度、covered cells 与虚线边界必须来自同一次
`project_table_cells()` 所有权投影；单独暴露只返回 spans 的入口容易让调用方重新绕开另外
两种投影结果。`make_table_view()` 现在直接读取这一个投影函数。

AI 章节上下文内部现存储 `relation_statuses/relation_infos`，并通过
`get_relation_status/get_relation_info` 查询。模型工具继续用整数 `target` 作为会话内短地址，
但提示、回复和 Python 对象均称“关系/ordinal”；`snap_range/snap_id/pair_spec` 只在工具输入
边界作为旧参数别名接受。GUI 的筛选、框选、悬停、评分和复制输出也已统一到同一套关系术语。

最后一轮 GUI 状态审计删除了只写不读的“焦点行”、AI 焦点丢失、hover 来源/坐标、文件多选
集合和选择重入字段。高亮现在只有 `_selected_rows` 一个视觉事实；状态灯只缓存实际绘制颜色。
对齐结果的 `_sim_matrix` 也不再挂到窗口后闲置，旧 `.sim.npy` 的删除兼容仍保留在清理边界。

其余只写状态也已清除：FocusManager 不再重复保存 ReviewController 已拥有的动作焦点和异常
序号，Agent 面板不再保存未展示的 turn 计数，摘要链接依赖 Qt 传入 href 而不私挂 `_path`。
无人调用的 dock 最小宽度估算和手动主题切换捷径也删除；主题继续由系统色彩方案唯一驱动。
SolidificationPlan 与 RelationStatus 中两个只构造不读取的审计字段同样不再占用模型表面。

环境检测结果不再生成欢迎页从未展示的 provider 标签；文件匹配规则也移除了声明却从未参与
排序的 `sort_key`。这两处尤其避免出现“配置看似可控、实际求解完全忽略”的假参数。

冻结锚点算法的隔离也补完：删除其 `AlignConfig` 别名与 `dualign.core` 对锚点/余量/归一化
内部函数的转发。生产真正共用的 `op_type_str/smart_join_lines` 提取到 `core.text`，所有生产
调用直接依赖该纯工具模块。提取同时修复旧 `op_type_str` 把一般 N:M 错写成 N:1/1:M 的问题，
并增加 `2:3` 回归断言；legacy CLI 和 benchmark 仍显式使用 `LegacyAnchorConfig`。

固化后的全文重建也不再接受或判断 `LegacyAnchorConfig`，并移除了只为旧质量门控存在的
`quality_config` 分支。`rebuild_alignment()` 现在严格调用生产 `AlignConfig` 与统计校准；因此
legacy 只剩 CLI 管线中的惰性显式分支和 benchmark，两条生产重对齐路径均不会意外进入旧算法。

聚合包边界也同步收紧：`LegacyAnchorConfig` 不再从 `dualign.core` 导出，冻结的 quality-gate
函数不再从 `dualign.services` 导出。最终又移除了 `core.aligner` 对 legacy 配置的导入、适配和
分派，以及聚合包中的 legacy 算法常量。CLI 与回归测试必须显式导入归档模块，使普通库调用方
不会把旧阈值配置、旧拒绝指标或算法选择器误认成生产 API。

正式 `AlignmentResult` 也不再复刻 legacy 的 `anchors/anchor_op_indices/sim_matrix`。这些字段在
GUI、报告和生产求解中均无人消费；尤其保留完整相似度矩阵会让显式 legacy CLI 在返回前额外
占用 `O(nm)` 内存。归档求解器自己的 benchmark 结果仍保留这些诊断，跨入正式报告管线时只
适配共同需要的关系、统计和决策状态。

GUI 中最后一层旧拒绝投影也已删除：`_last_quality_assessment` 只可能得到
`diagnostic_only`，却仍保留 `unreliable` 自动预览分支。现在正式 `result.status == rejected`
直接写决策报告、进入只读预览并禁用关系操作；接受或需审阅的 MDL 结果只写不参与决策的
诊断载荷。GUI 不再解释 legacy 的 anchor/gap/overflow 状态词。

旧 GUI `quality_gate` 设置也只在载入时删除，不再把其中的固定最低分或 Z-score 参数迁移到
新异常显示设置。这样淘汰算法的调参不会以“兼容迁移”名义继续影响新版本；用户明确保存过的
独立 `anomaly_detection` 显示设置仍照常保留。
