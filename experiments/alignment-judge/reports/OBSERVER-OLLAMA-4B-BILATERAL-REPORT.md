# Ollama embedding 双边平行 instruction 评测

日期：2026-09-01

状态：`opened engineering suite / not fresh validation / no production promotion`

关于“LLM 正确率高于 cosine embedding”原假设的正式判决和单变量 raw/instruction 反证见
[`OBSERVER-LLM-VS-EMBEDDING-HYPOTHESIS-REVERSAL-REPORT.md`](OBSERVER-LLM-VS-EMBEDDING-HYPOTHESIS-REVERSAL-REPORT.md)。

## 结论

本机实际可用的 4B embedding 模型是 `qwen3-embedding:4b-q4_K_M`，不是名为 Qwen4 的模型。
它在 Dualign 应用当前的双边平行 instruction 下得到 `1729/1736 = 99.60%`，比相同协议的
Harrier 0.6B `1721/1736 = 99.14%` 高 8 题（+0.46 个百分点）。

原版 `qwen3-embedding:0.6b` 得到 `1704/1736 = 98.16%`。Harrier 与它同为约 0.6B、Q8_0，
在同协议下多对 17 题（+0.98 个百分点），说明当前 Harrier 的收益在产品输入协议下仍然存在。

同一题集上的生成式 `qwen3.5:4b` 强制单选最佳结果为 `1667/1736 = 96.03%`。按 case ID 配对，
4B embedding 独对 67 题，生成式 4B 独对 5 题，两者共同错 2 题。因此在这批已打开的工程题上，
应用协议下的 embedding Top-1 明显优于生成式 LLM 判题；这不是 source-held-out 泛化结论。

## 协议

- 冻结题集：1,736 题、4,992 个 anchor-candidate pair；正文与逐题输出位于 Git 忽略的 `private/`。
- 输入 instruction（参考文本和每个候选均使用）：
  `Instruct: Identify parallel sentences across languages\nQuery: `（末尾包含一个空格）。

- instruction SHA-256：`51e9fbc22ee90e6197531edf5bb498e6b812e4b866a3faa221f6146869fb2ae2`。
- 使用 Dualign 的 `OllamaEncoder` 调用 `/api/embed`，对输出 L2 归一化后计算 cosine。
- 每题以 exact candidate 与 partial/unrelated 中最高分者比较；只有 margin 严格大于 0 才计 Top-1 正确。
- 全部唯一文本只编码一次，共 2,629 条；三个模型串行运行并在切换时卸载。

## 结果

| 模型 | 量化 | 正确/总数 | Top-1 | margin p10 | 编码时间 | pair/s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3 Embedding 0.6B | Q8_0 | 1704/1736 | 98.16% | 0.02938 | 69.97 s | 71.34 |
| Harrier 0.6B | Q8_0 | 1721/1736 | 99.14% | 0.02567 | 72.63 s | 68.73 |
| Qwen3 Embedding 4B | Q4_K_M | 1729/1736 | 99.60% | 0.03784 | 181.16 s | 27.56 |

4B 编码时间约为 Harrier 的 2.49 倍、原版 0.6B 的 2.59 倍。运行时三个模型均报告完整 GPU 驻留；
4B 驻留约 5.00 GB，两个 0.6B 均约 2.86 GB。测试时机器同时运行游戏，因此计时只代表当时负载，
不能当作独占 GPU 基准。

### 数据集切片

| 数据集 | Qwen3 0.6B | Harrier 0.6B | Qwen3 4B |
| --- | ---: | ---: | ---: |
| internal v1 K3（40） | 27/40（67.50%） | 34/40（85.00%） | 37/40（92.50%） |
| Reader natural（256） | 251/256（98.05%） | 256/256（100.00%） | 255/256（99.61%） |
| validation-v4 development（1,440） | 1426/1440（99.03%） | 1431/1440（99.38%） | 1437/1440（99.79%） |

4B 最差聚合语言方向为 `zh-en`：`395/398 = 99.25%`。7 个错误分布为：internal K3 3 题、
Reader natural 1 题、validation-v4 development 3 题；对应 hardest family 包括 semantic corruption、
coverage completeness、omission、middle omission、order perturbation 和 attribute counterfactual。

原版 0.6B 的主要短板集中在 internal K3（仅 67.50%），最差聚合方向为 `en-zh`：
`365/378 = 96.56%`。validation-v4 的错误主要落在 attribute counterfactual、merge/split、
middle omission 和 order perturbation。

### 配对变化

| 比较 | 共同正确 | 仅基线正确 | 仅候选正确 | 共同错误 | 候选净增 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Harrier 0.6B vs 原版 Qwen3 0.6B | 1692 | 12 | 29 | 3 | +17 |
| 4B embedding vs Harrier 0.6B | 1714 | 7 | 15 | 0 | +8 |
| 4B embedding vs 原版 Qwen3 0.6B | 1700 | 4 | 29 | 3 | +25 |
| 4B embedding vs 生成式 qwen3.5:4b | 1662 | 5 | 67 | 2 | +62 |

## 解释边界

这次测试纠正了历史比较中的关键口径问题：产品侧 embedding 不是 raw text，而是双边添加平行文本
instruction。历史 raw Qwen3 0.6B 的 93.95% 只能作为消融记录，不能拿来代表当前应用协议。

4B 的准确率和 p10 都更高，但仍不应据此直接替换 Harrier：工程集已经被多轮实验打开；两个本机模型的
量化不同；4B 更慢、驻留更大，并且有 7 个 Harrier 正确而它回退的 case。若讨论生产切换，需要在全新
source/work-disjoint 集合上冻结后复测，并在独占 GPU 环境测端到端吞吐和显存。

机器证据：

- [`OBSERVER-OLLAMA-HARRIER-BILATERAL-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-HARRIER-BILATERAL-RECEIPT.json)
- [`OBSERVER-OLLAMA-QWEN3-0.6B-BILATERAL-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-QWEN3-0.6B-BILATERAL-RECEIPT.json)
- [`OBSERVER-OLLAMA-QWEN3-4B-BILATERAL-RECEIPT.json`](../evidence/OBSERVER-OLLAMA-QWEN3-4B-BILATERAL-RECEIPT.json)
