# 技术笔记目录

本文档归集不适合纳入正式文档但可能有参考价值的技术记录。

| 文件                                                      | 内容                                                                          | 来源                                 |
| --------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| [GUI 启动闪烁诊断](gui-flicker-diagnosis.md)              | Windows DWM 闪烁问题的定位与修复                                              | 旧版 `docs/gui-flicker-diagnosis.md` |
| [批处理集成论证与 Demo 设计](batch-integration-design.md) | 消费端批处理调研、三段式 Demo 设计方案                                        | 2026-06-21 分析论证                  |
| [文档审查报告](doc-review-report.md)                      | 多提供方适配问题 + 全部 10 篇文档质量评分 + 三档优化方案                      | 2026-06-21 发布前审查                |
| [Instruction 机制审查](instruction-fix-design.md)         | 各编码器 Instruction 实现分析 + 副作用评估 + 缓存影响 + per-provider 改动方案 | 2026-06-21 分析论证                  |
| [N:1 / 1:M 智能修复决策草案](n-to-one-repair-decision.md) | 对齐关系、结构规范化、候选评分与跨项目职责的实验结论和待决策选项              | 2026-08-20 调研与实验                |
| [对齐算法试错路线归档](alignment-research-archive.md) | 交错脚手架、组合分数、混合码与 199 次随机化等淘汰路线及负面证据 | 2026-08-24 收敛归档 |
| [统计门控稀疏 MDL 全量异常审阅](research-alignment-pipeline-full-review.md) | 292 文档、761 条旧异常、99 个差异岛逐项审阅 | 2026-08-23 隔离研究 |
| [稀疏 MDL 的精确剪枝与退化修复研究](pruning-and-degeneration-report.md) | 精确 gap 商图、路径 DLD、双模型一致性与全量性能 | 2026-08-24 隔离研究 |
| [局部拆分递归对齐研究](local-split-realignment-study.md) | 无 gap 局部语法、条件结构码、生产适配和真实拆分审计 | 2026-08-24 已迁移 |
| [Legacy 锚点算法归档](legacy-anchor-algorithm.md) | 冻结算法、历史参数与显式 benchmark 入口 | 2026-08-24 归档 |
| [固化后重新对齐与状态重锚](solidification-realignment-design.md) | 固化后重跑对齐、内容指纹、剩余操作和 AI 建议的安全迁移方案                    | 2026-08-22 设计研究                  |

> 笔记不保证与当前代码完全一致，仅供参考。
