# 研究与迁移结论归档

状态：历史依据，不定义公共契约

更新日期：2026-08-26

本文压缩记录已经完成的设计迁移、被实验否定的路线和复现入口。现行行为以
[工作报告架构](architecture.md)、[对齐算法](algorithm.md)和
[详细算法设计](research-alignment-pipeline.md)为准；代码与这些文档冲突时，不应从本页恢复
旧实现。

## 已收敛的工程决策

| 主题 | 结论 | 现行位置 |
| --- | --- | --- |
| 工作状态 | 源 Markdown 与一个版本化 `report.json` 是唯一权威来源；报告只以稳定关系 ID 持久化动作身份 | `src/dualign/services/report_io.py`、`src/dualign/models/relation_identity.py` |
| 运行期地址 | `relation_id` 表示身份，`ordinal` 只是当前快照中的顺序；表格、AI、重放和固化不再各自维护索引语义 | `src/dualign/models/relation_status.py`、`src/dualign/services/table_projection.py` |
| 人工完成度 | 从当前关系状态统一投影 `subjects / required / completed`；自动修复和 Agent 决定不冒充用户审阅 | `project_relation_statuses()`、`manual_review_counts()` |
| 保存与固化 | 普通保存只写报告；固化先规划未来正文、重新对齐，再按双侧文本完全相同且唯一的关系保守重锚剩余状态 | `src/dualign/services/solidify.py`、`src/dualign/services/pair_save.py` |
| 自动修复 | 文档 A/B 策略统一经过 `repair_policy`；`1:0` 以文档 A 为准时使用占位，不删除 A 的正文 | `src/dualign/services/repair_policy.py` |
| 嵌入指令 | instruction 属于编码器配置并进入缓存身份；不同提供方可以显式关闭或覆盖，不能由全局常量替实际模型作决定 | `src/dualign/services/embedding.py`、`src/dualign/services/cached_encoder.py` |
| Legacy | 锚点算法冻结为显式 CLI/benchmark 路径，不进入 GUI，不作为 MDL 拒绝后的回退 | `src/dualign/core/legacy_anchor_aligner.py` |

这些结论曾分散在文档审查、N:1 修复草案、表格归属审查和固化重锚设计稿中。实现完成后继续
保留逐轮迁移记录，会让已经删除的别名、双状态和旧报告兼容看起来仍是产品能力，因此只保留
上述最终约束。

## 对齐研究的保留结论

### 旧锚点路线

旧算法通过互惠高分点切分文档，再在区间内补齐路径。它速度快，但锚点会过早限定后续搜索；
一旦正确复合关系跨越锚点，正确路径无法进入最终 DP。固定 `2:1 / 1:2`、锚点密度阈值、gap
比例和合并触顶指标也把生成能力与经验质量门混在一起。该实现只为回归保留：

```bash
uv run dualign align -a a.md -b b.md --algorithm legacy-anchor-v1
```

### 已否定的候选与组合策略

- 两遍奇偶交错窗口仍可能同时错过跨越两个脚手架点的正确关系；单覆盖、可跨越脚手架消除了
  parity 参数。
- 完整拼接余弦变高不能单独证明应合并；“相对最佳子块增益”能识别部分漏译，却会误伤表格和
  同主题续句，因此不能作为固定阈值。
- posterior 与 counterfactual DLD 的等权混合在真实异常集上比任一结构模型更差；当前保留
  两条路径的分歧作为复核信号，而不调经验权重。
- 199 次顺序随机化只规定 Monte Carlo 预算，没有匹配产品问题；短文档还会受最小 p 值限制。
  当前直接比较无序最优证据与单调最优证据的相对损失。
- 固定 top-k、连续两层路径稳定和候选图按轮扩张都不能给出最优性证书。实测编码开销已经低于
  额外求解和控制流成本，因此未进入生产。

### 精确化简与局部拆分

路径复杂度满足 `c = n + m - 2r`，所以同一语义关系数下 gap 的二维走法不携带额外信息。
生产求解器对 gap 网格取精确商，在稀疏语义边上求固定关系数的最大权单调链；这是目标函数的
等价变换，不是走廊近似。

人工拆分后的局部重对齐采用无 gap 递归 MDL：只在已选父关系内部工作，拆分引入语法边界，
另一侧仍可重新组合。失败时保留父关系并标记复核，不调用 legacy 全文对齐，也不通过降低
阈值强行产出路径。

当前仍无法仅靠同一嵌入空间可靠区分同主题漏译、译注和自然续句。若要扩大能力，应引入独立
校准的 token 覆盖、跨编码器证据或人工金标，而不是恢复长度、余弦和锚点阈值。

余弦得分的可观察精度固定为 binary16：先按精确逻辑文本合并重复轴，只计算唯一语料对，
再量化和展开。该规则消除低于部署链路有效精度的伪排序，但不降低嵌入缓存、概率码长或
动态规划的内部数值精度。门控校准 `real21.v3` 与这一观察空间绑定。

## 验证范围与局限

2026-08 的收敛实验覆盖 292 份含旧生产异常的真实文档，并逐项比较主路径、备选路径和状态。
门控探索集只有 20 对文档；循环错配和块乱序可证明流程可复现，却不是独立同分布测试集上的
泛化率。详细数字、复杂度和当前优化结果保留在
[详细算法设计](research-alignment-pipeline.md)，不在多份笔记中重复维护。

## 复现入口

这些脚本依赖调用方提供的数据或 `.artifacts/` 中的本地产物，不是单元测试：

| 脚本 | 用途 |
| --- | --- |
| `scripts/audit_production_anomalies.py` | 从仍与正文哈希一致的报告建立只读异常清单 |
| `scripts/calibrate_alignment_gate.py` | 生成与嵌入模型身份绑定的确定性门控校准 |
| `scripts/evaluate_mdl_pipeline.py` | 比较历史报告路径与当前生产 MDL 路径 |
| `scripts/benchmark_mdl_runtime.py` | 重放清单并输出路径摘要和运行时间，检查优化等价性 |

脚本不会把本机语料或实验产物纳入仓库。正式回归仍由 `tests/` 承担；研究脚本不能替代单元
测试，也不应使用硬编码的个人数据路径。
