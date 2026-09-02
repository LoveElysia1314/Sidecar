# Dualign Observer Bake-off 预注册协议

日期：2026-09-01
状态：`frozen_before_scoring / engineering_probe_only / no_training`

## 问题

同一批 exact-vs-hardest cases 上，Qwen3-Reranker-0.6B 的 pairwise interaction 是否足以支持把下一阶段结构改为
“embedding 负责全局 proposal，pairwise observer 只判 decision-relevant candidates”，还是应继续以
embedding/data-supervision 为主线。

## 冻结资产

1. internal v1 K=3：40 groups、5 WorkLineage、单 reviewer；仅作 internal engineering probe。
2. Reader natural heldout：256 cases、单 WorkLineage、128 omission + 128 boundary；来自 hash-bound reviewed
   reports，但仍是既有 seen evidence。
3. Validation-v4 development：1,440 cases、6 directions、10 families；original-generated、独立 QA；只打开
   development，不打开 rolling-shadow/confirmation。

MASSIVE metadata-only 候选、source-final、rolling-shadow 和 confirmation 均不进入本轮。

## 冻结 arms

- `embedding_base`：Qwen/Qwen3-Embedding-0.6B，HF BF16，完整 raw text，last-token pooling，L2 cosine。
- `embedding_l1`：同一 base + 现有 internal L1 LoRA。
- `embedding_l2`：同一 base + 现有 internal L2 LoRA。
- `reranker_retrieval`：Qwen3-Reranker-0.6B 固定 revision，官方普通 retrieval instruction。
- `reranker_strict`：同一 checkpoint，只把 instruction 改为 strict equivalence，明确惩罚 omission、addition、
  contradiction、unsupported specification。

不训练模型，不加入 4B，不为 NLI 扩大下载范围。全部 GPU scorer 严格串行。

## 指标

- exact Top-1（严格 `margin > 0`）；
- exact-vs-hardest native margin mean/p10/min；
- 相对 raw embedding 的 wrong-to-correct、correct-to-wrong 和稳定项；
- family：omission、addition、substitution、boundary 及细分；
- direction 与最差方向；
- wall time、amortized ms/pair、pairs/s、peak CUDA allocated/reserved；
- 不以平均 cosine 作主结论。

cosine margin 与 reranker logit margin 不同尺度，不比较绝对差值大小。跨架构判断只使用 Top-1、paired flips、
各自 p10 的正负与 family non-regression。

## 预注册架构转向门

pairwise arm 只有同时满足以下条件才支持架构转向：

1. 三个数据集中 Top-1 都严格高于 raw embedding；
2. 三个数据集自身的 p10 margin 都为正；
3. omission/boundary，以及有覆盖时的 addition，在 candidate-level Top-1 不退化且 p10 为正；
4. 每个数据集 wrong-to-correct 多于 correct-to-wrong，且 loss 不超过 gain 的一半；
5. observed batch 下 amortized latency 不超过 100 ms/pair，peak CUDA allocated 不超过 4 GiB。

本门刻意保守。未通过表示“本轮不支持架构转向”，不等于 pairwise architecture 永久无效；通过也只支持
下一步最小接入实验，不构成部署结论。
