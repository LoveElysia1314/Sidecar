# Alignment Judge 设计与晋升边界

状态：`engineering baseline updated / no automatic production switch`

## 1. 判定合同

一个 case 包含参考文本和 2–4 个候选，并且恰有一个候选满足严格对齐等价：

- 保留全部 alignment-relevant information；
- 不增加无依据的信息；
- 不出现矛盾、错误实体/属性/数量/时间/顺序；
- 文本边界正确；
- 忠实翻译和自然改写允许措辞不同。

生成式判别器只返回当前题的最佳选项字母。解释、多字母、非法字母和解析失败全部计错。这个强制单选合同
成立的前提是题包已经验证“恰有一个 exact candidate”；它不适用于真实产品中可能多解、无解或输入损坏的场景。

## 2. Dualign 架构位置

实验比较了三类 observer：

```text
bilateral-instruction embedding
        ↓
全局 atomic matrix 与 composition proposal（当前生产主干）

retrieval reranker ── 零微调 strict-equivalence probe（未过门）

qwen3.5:4b ───────── 离线 MCQ / prompt-development observer（96.03%，未接生产）
```

应用当前的 embedding 输入协议不是 raw text，而是对参考文本与所有候选都对称添加
`Instruct: Identify parallel sentences across languages\nQuery: `（末尾包含一个空格）。

在此产品协议下，Harrier 0.6B 为 `1721/1736 = 99.14%`，本机实际存在的
原版 `qwen3-embedding:0.6b` 为 `1704/1736 = 98.16%`，`qwen3-embedding:4b-q4_K_M`
为 `1729/1736 = 99.60%`。Harrier 相对同尺寸原版净增 17 题（29 个 Harrier 独对、12 个原版独对）；
4B 相对 Harrier 有 15 个 wrong-to-correct、7 个 correct-to-wrong，净增 8 题。4B 的完整编码耗时为
181.16 秒，Harrier 为 72.63 秒，原版 0.6B 为 69.97 秒；三次均完整驻留 GPU，但这是游戏并发负载下的
观测值。

历史 embedding/reranker bake-off 中的 raw embedding `1631/1736 = 93.95%` 与 strict reranker
`1501/1736 = 86.46%` 继续作为历史消融证据，不能替代上述应用协议基线。现成 reranker 仍不进入
生产决策链，也不改变 atomic matrix、candidate pruning、structure cost、MDL path solver 或
disagreement review。

生成式 4B 结果说明严格信息等价可以被小模型较好地观察，但它的 96.03% 来自已打开的提示词开发集；
300题换位一致率只有 88.33%。同题配对时，4B embedding 与生成式 4B 共同答对 1,662 题，embedding
独对 67 题，生成式模型独对 5 题，共同错 2 题。这个结果支持继续以 embedding 作为产品主干，但不能证明
4B 已达到生产晋升标准：题集不是 fresh validation，且安装量化、显存和吞吐成本与 Harrier 不同。

因此，先前基于 raw-text embedding 93.95% 与生成式 LLM 96.03% 得出的“LLM 高于 cosine”工程假设
已经撤销。同模型 Qwen3 Embedding 0.6B 的单变量重放显示，raw text 为 93.84%，应用双边 instruction
为 98.16%（净增 75 题，McNemar `p=1.20e-12`）。正式反证边界和机器证据见
[`reports/OBSERVER-LLM-VS-EMBEDDING-HYPOTHESIS-REVERSAL-REPORT.md`](reports/OBSERVER-LLM-VS-EMBEDDING-HYPOTHESIS-REVERSAL-REPORT.md)。

## 3. 数据与证据分层

| 层 | 内容 | Git 策略 | 可作何种结论 |
| --- | --- | --- | --- |
| tracked protocols/reports | 预注册规则、汇总指标、结论 | 提交 | 解释实验与复现入口 |
| tracked evidence | ID、hash、标签、计时、聚合/逐题无正文记录 | 提交 | 验证数量、顺序和历史结果 |
| private sources | 参考文本、候选正文、内部 lineage | 忽略 | 本机完整重放 |
| private runs | 逐题答案、错误集、模型输出 | 忽略 | 配对分析和人工审阅 |
| model/checkpoint | Ollama 模型、HF 权重、LoRA | 不迁入 | 由外部模型标识与 hash 解析 |

私有文件可以位于仓库工作区，但不是 Git 权威。`MIGRATION.json` 中的 SHA-256 是迁移完整性的权威；若私有文件
缺失，应从受控历史归档恢复并核对哈希，不能用同名新语料替代。

## 4. 已否定与保留的提示词方向

- 长 checklist 和“寻找最小差异”的 near-miss framing 在4B上退化。
- 简短双向蕴含在错误挖掘子集上改善 omission/order，但明显损害 addition，不能作为通用替换。
- 信息集等价 P5、可替换 P6、双向蕴含 P7 在全1,736题上分别为91.59%、86.23%、91.65%，均低于最终
  架构提示词96.03%。
- 显式列出 omission、addition、contradiction、incorrect boundary，同时要求只返回字母，是当前保留基线。

这些是 `qwen3.5:4b` 与当前工程题集的行为结论，不是提示词理论的普遍排名。

## 5. 再开启研究的门槛

近期探索在此收口。只有出现明确产品需求或新方法时才重开，并至少满足：

1. 使用 source/work-disjoint 的新题集，禁止继续对 development/check 追词；
2. 正确选项位置均衡，并至少执行第二排列或多排列审计；
3. 单独报告 omission、addition、contradiction、boundary、merge/split 和最差方向；
4. 相对当前基线做 paired flips 与精确检验，解析失败计错；
5. 若拟进入生产，必须支持真实场景的多解/无解/歧义语义，而不是复用强制单选假设；
6. 端到端验证不得破坏 MDL 路径、人工审阅状态、固化事务或报告身份；
7. 本地8GB设备上给出独占GPU的延迟、显存和失败恢复数据。

未满足这些条件时，新的 prompt 微调只属于探索性诊断，不更新产品架构。
