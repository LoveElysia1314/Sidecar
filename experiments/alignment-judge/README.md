# Alignment Judge 实验归档

状态：`closed-engineering-exploration / local-replayable / not-production`

本目录接管原 `dualign-embedding-lab-v4` 中更贴近 Dualign 产品架构的 observer/alignment-judge
实验。研究问题是：给定参考文本与若干候选，embedding、reranker 或本地生成模型能否稳定选出信息严格等价、
边界正确的候选。

## 收口结论

1. Dualign 当前 Ollama embedding 协议会对参考文本和每个候选对称添加
   `Instruct: Identify parallel sentences across languages\nQuery: `，再用归一化 cosine 构造全局相似度、
   候选图和 composition evidence；这里不应把 raw-text 历史分数当作产品协议基线。
2. 在相同的 1,736 题工程集和上述双边 instruction 下，本机
   `qwen3-embedding:4b-q4_K_M` 得到 `1729/1736 = 99.60%`；当前 Harrier 0.6B 对照为
   `1721/1736 = 99.14%`，原版 `qwen3-embedding:0.6b` 为 `1704/1736 = 98.16%`。
   Harrier 相对同尺寸原版净增 17 题；4B 相对 Harrier 净增 8 题，但编码耗时约为后者的 2.49 倍。
3. 本机 `qwen3.5:4b` 在强制单选题上的最佳提示词为：

   ```text
   You are a bilingual or multilingual alignment judge. Choose the one candidate that best preserves all alignment-relevant information from the reference and adds no unsupported information. Natural translation and faithful paraphrase differences are allowed. Any omission, addition, contradiction, or incorrect text boundary makes a candidate worse. Do not rewrite or explain the text. Return only the best option letter.
   ```

4. 该提示词在已打开的 1,736 题工程集上得到 `1667/1736 = 96.03%`，高于旧设问的
   `1561/1736 = 89.92%`。它只返回一个选项字母，不提供 `AMBIGUOUS` 或 `NONE`。
5. 在固定的第二套 300 题选项排列中，它得到 `282/300 = 94.00%`；最强专家风格 P7 为
   `270/300 = 90.00%`。模型仍有选项顺序敏感性，因此该结果不是独立泛化率。
6. 4B embedding 在这批题上也高于生成式 4B 的 96.03%；但两者延迟口径不同，且题集已经参与过
   架构和提示词开发，不能把差值解释成未见数据泛化率。
7. 目前最合适的用途是离线诊断、错误分层和未来专用判别器的基线，而不是自动覆盖 Dualign 的
   MDL/人工审阅决策。

详细设计与晋升条件见 [DESIGN.md](DESIGN.md)。历史协议和逐轮结果分别保留在
[`protocols/`](protocols/) 与 [`reports/`](reports/)；机器证据在 [`evidence/`](evidence/)。
本次双边 instruction 的 4B embedding 报告见
[`reports/OBSERVER-OLLAMA-4B-BILATERAL-REPORT.md`](reports/OBSERVER-OLLAMA-4B-BILATERAL-REPORT.md)。
关于“LLM 正确率高于 cosine embedding”原假设的正式反证见
[`reports/OBSERVER-LLM-VS-EMBEDDING-HYPOTHESIS-REVERSAL-REPORT.md`](reports/OBSERVER-LLM-VS-EMBEDDING-HYPOTHESIS-REVERSAL-REPORT.md)。

## 目录

```text
alignment-judge/
├── README.md                 # 当前入口与最终结论
├── DESIGN.md                 # 数据契约、架构位置和后续门槛
├── MIGRATION.json            # 迁移来源、哈希和排除范围
├── protocols/                # 冻结在评分前的协议
├── reports/                  # 人类可读结果
├── evidence/                 # 去正文、去本机路径的 manifest/receipt
├── tools/                    # 构题、评分、消融、审计、导出工具
├── tests/                    # 工具和迁移完整性测试
└── private/                  # 本机正文、题包、逐题回答和运行输出；Git 忽略
```

## 数据范围

完整工程集为 1,736 题、4,992 个候选：

| 数据集 | 题数 | 候选数/题 | 边界 |
| --- | ---: | ---: | --- |
| internal v1 K3 | 40 | 4 | 单 reviewer、既有模型已见，仅工程诊断 |
| Reader natural | 256 | 2 | 单一 WorkLineage、既有 reviewed report 派生 |
| validation-v4 development | 1,440 | 3 | original-generated、development only |

`rolling-shadow`、`confirmation` 和 `source-final` 从未因本轮提示词探索而打开。私有数据的本机布局和
来源哈希见 [`private/README.md`](private/README.md) 与 `MIGRATION.json`。

## 快速验证

只运行不依赖模型和私有正文的测试：

```powershell
uv run pytest -q experiments/alignment-judge/tests
```

验证本机私有源数据能否重建 1,736 题：

```powershell
uv run python experiments/alignment-judge/tools/run_observer_bakeoff.py validate `
  --private-groups experiments/alignment-judge/private/sources/internal-v1/candidate-groups.private.jsonl `
  --private-split experiments/alignment-judge/private/sources/internal-v1/split.json `
  --natural-cases experiments/alignment-judge/private/sources/reader-natural/cases.jsonl `
  --validation-development experiments/alignment-judge/private/sources/validation-v4/development.cases.jsonl
```

Ollama 评分、模型 bake-off 和提示词消融是显式的本地实验命令，不进入默认测试；运行前应独占 GPU，运行后
检查 `ollama ps`。历史命令参数可通过相应工具的 `--help` 查看。

## 迁移语义

本次是所有权与复现入口迁移，不是历史源目录清理。原实验室资产仍保留，直到单独完成归档索引和可恢复清理；
Dualign 内的 `MIGRATION.json` 与私有副本是新的产品侧研究入口。
