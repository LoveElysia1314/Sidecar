# Observer Expert Prompt Style Report

## 结论

在 `qwen3.5:4b`、同一 1,736 题、`temperature=0`、`think=false` 的强制单选条件下，专家建议的 P5/P6/P7 均未超过当前架构提示词。最终继续采用当前架构提示词；不晋升 P5/P6/P7。

最终提示词：

```text
You are a bilingual or multilingual alignment judge. Choose the one candidate that best preserves all alignment-relevant information from the reference and adds no unsupported information. Natural translation and faithful paraphrase differences are allowed. Any omission, addition, contradiction, or incorrect text boundary makes a candidate worse. Do not rewrite or explain the text. Return only the best option letter.
```

它仍然只允许返回最佳选项字母，不包含 `AMBIGUOUS` 或 `NONE`。

## 完整测试

| 提示词 | 正确数 | 正确率 | 墙钟总耗时 | 相对当前领先净变化 | 门槛 |
|---|---:|---:|---:|---:|---|
| 当前架构强制单选 | 1667/1736 | 96.03% | 318.5s | — | 保留 |
| P5 信息集等价 | 1590/1736 | 91.59% | 289.4s | -77 | 未通过 |
| P6 替换测试 | 1497/1736 | 86.23% | 297.2s | -170 | 未通过 |
| P7 双向蕴含 | 1591/1736 | 91.65% | 289.7s | -76 | 未通过 |
| 旧原始设问基线 | 1561/1736 | 89.92% | 303.2s | — | 参考 |

最强专家风格是 P7（1591/1736，91.65%），但仍比当前架构提示词少答对 76 题。配对结果为当前领先独有正确 92 题、P7 独有正确 16 题，McNemar 双侧精确检验 `p=3.78e-14`。

## 第二选项排列审计

固定抽取 300 题，并对每题实施非零循环换位，使正确选项字母全部改变。

| 提示词 | 原排列同子集 | 第二排列 | 语义候选选择一致率 |
|---|---:|---:|---:|
| 当前架构强制单选 | 281/300 (93.67%) | 282/300 (94.00%) | 88.33% |
| P7 双向蕴含 | 272/300 (90.67%) | 270/300 (90.00%) | 81.33% |

第二排列上当前提示词仍领先 12 题（282 对 270）。这说明完整集领先并非只由原始选项位置造成；但一致率并非 100%，因此 4B 模型仍存在可测的选项顺序敏感性，不能宣称已彻底消除位置偏置。

## 解释与边界

P5/P7 的形式化表达很简洁，但在这个 4B 模型上，显式列出 `omission`、`addition`、`contradiction` 和 `incorrect text boundary` 的架构提示更有效。P6 的“可替换”表述下降最大。这里是模型与已打开工程题集上的实证结果，不是关于提示词理论优劣的普遍结论。

所有候选均为零解析失败；没有训练模型，也没有打开 rolling shadow、confirmation 或 source-held-out final。公开报告和收据不包含语料正文。
