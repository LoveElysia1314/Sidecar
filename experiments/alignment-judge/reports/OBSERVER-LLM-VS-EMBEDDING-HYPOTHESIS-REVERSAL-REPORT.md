# 原假设推翻报告：应用协议下 LLM 是否优于 cosine embedding

日期：2026-09-01

状态：`prior engineering hypothesis rejected / opened-suite evidence / not universal validation`

## 1. 判决

原假设：

> 在 Dualign 的候选选择任务中，生成式 LLM 判题比 cosine embedding 更准确。

**该假设在当前 Dualign 工程任务和应用输入协议下被拒绝。** 同一批 1,736 题上，生成式
`qwen3.5:4b` 的最佳强制单选结果为 `1667/1736 = 96.03%`；三个按应用协议运行的 embedding
分别为：

| observer | 正确/总数 | Top-1 | 相对 LLM |
| --- | ---: | ---: | ---: |
| 原版 Qwen3 Embedding 0.6B Q8_0 | 1704/1736 | 98.16% | +37 题 / +2.13 pp |
| Harrier 0.6B Q8_0 | 1721/1736 | 99.14% | +54 题 / +3.11 pp |
| Qwen3 Embedding 4B Q4_K_M | 1729/1736 | 99.60% | +62 题 / +3.57 pp |

三项差异在同题配对的 McNemar 双侧精确检验下均显著，且经过三重比较 Bonferroni 阈值
`0.05/3 = 0.0167` 后仍然成立。最直接的工程结论不是“embedding 普遍优于 LLM”，而是：

> **此前“LLM 高于 cosine”的结论来自 raw-text embedding 与提示词优化 LLM 的错位比较；它不能代表
> Dualign 当前的双边平行 instruction embedding 协议。**

## 2. 为什么旧观察看起来支持原假设

在同一套题上，raw-text `qwen3-embedding:0.6b` 为 `1629/1736 = 93.84%`，生成式 4B 为
`1667/1736 = 96.03%`。LLM 净多 38 题，McNemar `p=0.00293`。历史 BF16 raw 结果
`1631/1736 = 93.95%` 也与本次 Q8_0 raw 重放接近。

因此，“LLM 高于 raw cosine”这个观察可以复现。问题在于它回答的是错误的问题：应用实际不会把裸文本
直接交给 embedding，而会对参考文本和每个候选对称添加：

`Instruct: Identify parallel sentences across languages\nQuery: `（末尾包含一个空格）。

与此同时，LLM 的 96.03% 已经来自在该工程集上筛选出的最佳提示词，并非无提示的模型能力。将优化后的
LLM 与非应用协议的 raw embedding 比较，把输入协议差异错误地归因给了架构差异。

## 3. 关键单变量反证

为隔离上述混淆，本轮使用完全相同的本机模型、digest、Q8_0 量化、题目、标签、批大小、cosine 实现和
Top-1 判据，只改变 embedding 输入 instruction：

| Qwen3 Embedding 0.6B | 正确/总数 | Top-1 | margin p10 |
| --- | ---: | ---: | ---: |
| raw text，空 instruction | 1629/1736 | 93.84% | 0.00785 |
| 应用双边 instruction | 1704/1736 | 98.16% | 0.02938 |

配对结果为：共同正确 1,608 题，instruction 独对 96 题，raw 独对 21 题，共同错误 11 题；instruction
净增 75 题、`+4.32 pp`，McNemar 双侧精确 `p=1.20×10⁻¹²`。

这一步不依赖 4B 模型、更换量化或 Harrier 微调，足以确认输入协议本身会翻转 LLM 与 embedding 的排名：

```text
raw Qwen3 0.6B       93.84%  <  生成式 4B 96.03%
应用协议 Qwen3 0.6B 98.16%  >  生成式 4B 96.03%
```

## 4. 与 LLM 的严格同题配对

下表中“仅 embedding 正确”和“仅 LLM 正确”来自完全相同的 case ID，不是两个独立样本的总分比较：

| embedding 候选 | 共同正确 | 仅 LLM 正确 | 仅 embedding 正确 | 共同错误 | 净增 | McNemar p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 原版 Qwen3 0.6B | 1639 | 28 | 65 | 4 | +37 | 1.58×10⁻⁴ |
| Harrier 0.6B | 1654 | 13 | 67 | 2 | +54 | 6.42×10⁻¹⁰ |
| Qwen3 4B | 1662 | 5 | 67 | 2 | +62 | 6.39×10⁻¹⁵ |

这不是由少量共同错误或解析失败造成的表面差异。即便使用参数量远小于生成式 4B 的原版 0.6B，embedding
仍有 65 个独有正确、只有 28 个反向损失。

## 5. 非补偿性检查

### 数据集

| observer | internal K3（40） | Reader natural（256） | validation-v4 dev（1,440） |
| --- | ---: | ---: | ---: |
| 生成式 qwen3.5:4b | 28/40（70.00%） | 250/256（97.66%） | 1389/1440（96.46%） |
| 原版 Qwen3 Embedding 0.6B | 27/40（67.50%） | 251/256（98.05%） | 1426/1440（99.03%） |
| Harrier 0.6B | 34/40（85.00%） | 256/256（100.00%） | 1431/1440（99.38%） |
| Qwen3 Embedding 4B | 37/40（92.50%） | 255/256（99.61%） | 1437/1440（99.79%） |

原版 0.6B 在小型 K3 上比 LLM 少 1 题，所以不能声称它每个切片都占优；但 Harrier 0.6B 和 4B
embedding 在三个数据集上都不退化，排除了“只靠大 development 集补偿困难集损失”的解释。

### 关键错误族

| family | 生成式 4B | Harrier 0.6B | Qwen3 Embedding 4B |
| --- | ---: | ---: | ---: |
| adjacent addition | 93.75% | 100.00% | 100.00% |
| low-salience addition | 95.83% | 100.00% | 100.00% |
| Reader natural omission | 96.09% | 100.00% | 99.22% |
| middle omission | 92.36% | 99.31% | 99.31% |
| omission head | 93.75% | 100.00% | 100.00% |
| omission tail | 97.92% | 100.00% | 100.00% |
| order perturbation | 95.83% | 97.22% | 99.31% |
| merge/split missing sub-event | 100.00% | 100.00% | 100.00% |
| boundary shift | 100.00% | 100.00% | 100.00% |
| attribute counterfactual | 95.14% | 97.22% | 99.31% |

Harrier 与 4B embedding 在列出的 addition、omission、boundary、order、merge/split 和 attribute
切片上均未低于生成式 LLM。因此，aggregate 反转并非来自容易的 unrelated case 补偿关键语义退化。

## 6. 哪些结论被推翻，哪些没有

已被证据推翻：

- “Dualign 应用中，生成式 LLM 的正确率高于 cosine embedding”；
- “93.95% 左右的 raw embedding 分数可以代表当前产品 embedding 协议”；
- “必须依靠 4B 生成模型才能得到高于 96% 的严格对齐选择准确率”。

没有被本报告证明：

- embedding 在所有数据分布、所有多语种语义任务上普遍优于 LLM；
- 4B embedding 已显著优于 Harrier。两者只有 22 个分歧题，4B 净增 8 题但 `p=0.134`；
- 99% 以上是未见数据泛化率。题集已经参与过模型、架构和提示词探索；
- 强制单选工程题可以覆盖真实产品中的多解、无解、歧义或损坏输入；
- 当前游戏并发负载下的耗时可以代表独占 GPU 性能。

## 7. 工程结论

原假设应从 Dualign 的设计依据中撤销，替换为：

> 在当前已打开工程集上，使用应用双边平行 instruction 的 cosine embedding 比最佳生成式 4B 强制单选
> observer 更准确；Harrier 0.6B 是当前同尺寸首选，4B embedding 是更高准确率但更高成本的候选。

生成式 LLM 仍可用于离线错误解释、难例构造和独立异构复核，但现有准确率证据不支持把它放在 embedding
之前充当主判定器。下一次若要恢复“LLM 优于 embedding”的主张，必须在新的 source/work-disjoint 冻结集上，
使用应用真实双边 instruction、相同 case contract 和同题配对检验重新成立。

## 8. 可复核证据

- 机器汇总：[`OBSERVER-HYPOTHESIS-REVERSAL-SUMMARY.json`](../evidence/OBSERVER-HYPOTHESIS-REVERSAL-SUMMARY.json)
- raw 单变量对照：[`OBSERVER-OLLAMA-QWEN3-0.6B-RAW-ABLATION-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-QWEN3-0.6B-RAW-ABLATION-RECEIPT.json)
- 原版 0.6B 应用协议：[`OBSERVER-OLLAMA-QWEN3-0.6B-BILATERAL-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-QWEN3-0.6B-BILATERAL-RECEIPT.json)
- Harrier 应用协议：[`OBSERVER-OLLAMA-HARRIER-BILATERAL-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-HARRIER-BILATERAL-RECEIPT.json)
- 4B 应用协议：[`OBSERVER-OLLAMA-QWEN3-4B-BILATERAL-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-QWEN3-4B-BILATERAL-RECEIPT.json)
- 生成式提示词结果：[`OBSERVER-ARCHITECTURE-PROMPT-REPORT.md`](OBSERVER-ARCHITECTURE-PROMPT-REPORT.md)
- 汇总生成工具：[`finalize_observer_hypothesis_reversal.py`](../tools/finalize_observer_hypothesis_reversal.py)

所有公共证据均不含语料正文或本机路径；私有逐题结果由 SHA-256 和字节数绑定，保存在 Git 忽略目录。
