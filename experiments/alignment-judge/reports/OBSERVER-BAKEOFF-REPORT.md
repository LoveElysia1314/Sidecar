# Dualign Observer Bake-off 报告

日期：2026-09-01
判定：`architecture_turn_not_supported / keep_embedding_and_data_supervision_mainline`
范围：`engineering_probe_only / no_training / no_deployment_conclusion`

## 1. 结论

本轮不支持把 Dualign 下一阶段的主要精力从 embedding 转向零微调 pairwise observer，也不支持现在把
Qwen3-Reranker-0.6B 接入生产决策链。

普通 retrieval instruction 的 pooled Top-1 为 `1461/1736 = 84.16%`；strict-equivalence instruction 提升到
`1501/1736 = 86.46%`，但仍低于 raw Qwen3 embedding 的 `1631/1736 = 93.95%`。两条 reranker arm 的 pooled
p10 都为 `-0.125`，而 raw embedding 为 `+0.00769`。strict arm 在三个数据集都没有通过预注册的 Top-1、p10、
critical-family 和 paired-flip 门。

因此当前建议是：

1. 保留 raw-text embedding 作为全局召回、atomic matrix 和 composition proposal 主干；
2. 继续优先修复数据 construct、2+1 标注与 embedding supervision；
3. 不把现成 retrieval reranker 当作严格信息等价模型；
4. 若未来数据门通过，可把专门训练的 Dualign pair classifier 作为独立 sibling 重测，但不能由本轮零微调结果
   宣布 cross-encoder architecture 无效。

## 2. 冻结输入与边界

评分前冻结了 1,736 cases、4,992 anchor-candidate pairs：

| 数据集 | cases | 角色与限制 |
|---|---:|---|
| internal v1 K=3 | 40 | 5 WorkLineage；单 reviewer；24 train / 8 dev / 8 diagnostic；全部 seen |
| Reader natural heldout | 256 | 单 WorkLineage；128 omission + 128 boundary；既有 reviewed reports 派生 |
| Validation-v4 development | 1,440 | 6 directions、10 families；original-generated、独立 QA；development only |

没有打开 rolling-shadow、confirmation 或 source-final；没有使用 MASSIVE metadata-only 候选；没有训练模型。
本机没有现成 multilingual NLI checkpoint，因此没有为第三臂扩大下载范围。

关键输入 SHA-256：

- internal v1 private package：`30a6bbcf4ed9625d39e04c8064aba0a23261fa1207527b148cbe2d1db800f348`；
- Reader natural cases：`0190ba27e753f3a8bf68c30dd3087f09287e344d1aadbe1ef959fc3d3cde19e5`；
- Validation-v4 development：`c5a5c66a8696165cef1ea4d8f9bcc74a825ecbf20729f543bd3e983f9bd556f3`。

Reranker 固定为 `Qwen/Qwen3-Reranker-0.6B` revision
`e61197ed45024b0ed8a2d74b80b4d909f1255473`；本地 `model.safetensors` SHA-256 为
`27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b`，与官方文件摘要一致；license 为
Apache-2.0。

## 3. 主结果

不同 observer 的 native margin 不同尺度：embedding 是 cosine gap，reranker 是 `yes_logit - no_logit` gap。
因此绝对 margin 大小不跨模型比较；p10 只比较正负和各 arm 自身的尾部状态。

| arm | internal v1 K=3 | Reader natural | Validation-v4 dev | pooled | pooled p10 |
|---|---:|---:|---:|---:|---:|
| raw embedding | 25/40 (62.50%) | 243/256 (94.92%) | 1363/1440 (94.65%) | 1631/1736 (93.95%) | +0.00769 |
| embedding L1 | 30/40 (75.00%) | 243/256 (94.92%) | 1369/1440 (95.07%) | 1642/1736 (94.59%) | +0.00915 |
| embedding L2 | 29/40 (72.50%) | 243/256 (94.92%) | 1365/1440 (94.79%) | 1637/1736 (94.30%) | +0.00938 |
| reranker retrieval | 18/40 (45.00%) | 240/256 (93.75%) | 1203/1440 (83.54%) | 1461/1736 (84.16%) | -0.12500 |
| reranker strict | 21/40 (52.50%) | 240/256 (93.75%) | 1240/1440 (86.11%) | 1501/1736 (86.46%) | -0.12500 |

分数据集 p10：

| arm | internal v1 | Reader natural | Validation-v4 dev |
|---|---:|---:|---:|
| raw embedding | -0.01168 | +0.02144 | +0.00900 |
| embedding L1 | -0.00516 | +0.02284 | +0.01030 |
| embedding L2 | -0.00545 | +0.02226 | +0.01061 |
| reranker retrieval | -0.43750 | +0.25000 | -0.18750 |
| reranker strict | -0.38125 | +0.34375 | -0.12500 |

### 3.1 相对 raw embedding 的 paired flips

| arm | internal v1 gain/loss | Reader natural gain/loss | Validation-v4 dev gain/loss |
|---|---:|---:|---:|
| embedding L1 | 5 / 0 | 0 / 0 | 10 / 4 |
| embedding L2 | 4 / 0 | 0 / 0 | 8 / 6 |
| reranker retrieval | 5 / 12 | 9 / 12 | 53 / 213 |
| reranker strict | 8 / 12 | 9 / 12 | 48 / 171 |

strict instruction 相对普通 retrieval 在 Validation-v4 development 有 133 gain / 96 loss，说明 instruction
确实改变了 observer 行为；但它在 internal v1 为 11/8、Reader natural 为 10/10，且没有跨数据集稳定胜出。

### 3.2 决策相关 family

strict reranker 的局部强项是 addition：

- adjacent addition：`141/144`，高于 raw embedding 的 `133/144`；
- low-salience addition：`144/144`，与 raw embedding 持平；
- private structural boundary：`37/40`，高于 raw embedding 的 `36/40`。

但关键 omission/boundary guards 明显失败：

- Validation-v4 middle omission：`99/144`，raw 为 `135/144`；
- omission head：`130/144`，raw 为 `141/144`；
- omission tail：`100/144`，raw 为 `143/144`；
- merge/split missing sub-event：`119/144`，raw 为 `136/144`；
- Reader natural omission：`113/128`，raw 为 `116/128`；
- Validation-v4 boundary shift：`143/144`，raw 为 `144/144`。

这不是可以用 addition 收益补偿的 guard trade-off。strict instruction 没有把 retrieval checkpoint 变成稳定的
strict-equivalence observer。

## 4. 成本

| arm | amortized ms/pair | pairs/s | peak CUDA allocated | max tokens | truncation |
|---|---:|---:|---:|---:|---|
| raw embedding | 3.96 | 252.36 | 1.29 GiB | 202 | none |
| embedding L1 | 5.09 | 196.65 | 1.36 GiB | 202 | none |
| embedding L2 | 5.07 | 197.16 | 1.36 GiB | 202 | none |
| reranker retrieval | 11.52 | 86.83 | 1.32 GiB | 450 | none |
| reranker strict | 12.62 | 79.26 | 1.33 GiB | 473 | none |

Reranker 成本门通过，说明只评分 decision-relevant candidates 在 8GB 设备上工程上可行。失败来自准确性和尾部，
不是显存或吞吐。这里是 batch-amortized probe，不等同于交互式单 pair latency。

## 5. Dualign 最小接入点审计

只读源码 commit：`4f47223a98498e40eea4aa173ff06be079ccbd20`。

当前调用链是：

```text
global embedding cosine matrix
→ align_centered_frontier_mdl
→ decision_relevant_candidates
→ _prepare_counterfactual_composition_models
→ joined full block + leave-one-line-out ablations
→ counterfactual_diagnostics / conditional rank evidence
→ dual composition MDL solve
→ disagreement/witness review
```

`pipeline.py` 先用 embedding 构建 atomic matrix，再在 `decision_relevant_candidates()` 后才编码 compound variants。
`composition_mdl.py` 对每个 N:1/1:N proposal 构造 full 与所有 leave-one-line-out variants，并计算
full-vs-best-ablation gain。若未来专用 pairwise arm 真正过门，最小研究接入点是仅把这一步的 variant-vs-counterpart
score 抽象为 `pair_score_fn`；atomic matrix、candidate pruning、structure cost、path solver 和 disagreement 流程均保持
不变。本轮 gate 失败，因此没有实施该改动。

## 6. 质量事件与复现

第一次 preflight 评分发现 private 40 的 raw 结果异常高于既有 receipt。根因是 private JSON 的正文节点为
`{sha256,text}`，初版 loader 错把整个对象字符串化，实际比较了带 hash metadata 的对象表示。该批结果被宣布无效并
覆盖；最终 loader 强制提取 `text`、逐项验证 SHA-256，并新增回归测试。修正后 raw private 结果回到 `25/40`，与
既有 probe 量级一致；最大 observed tokens 从异常运行的 278 回到 receipt 预期的 202。

最终验证：

- scorer 单元测试：5 passed；
- 1,736 case IDs 唯一，恰好一个 exact candidate；
- private split：24/8/8 闭合；
- 五臂均 4,992 pairs、无 truncation、无 NaN/OOM；
- 评分后无 CUDA compute process；
- Dualign、dualign-embedding-training 和旧 lab 均未被本任务修改；V4 目录不是 Git 仓库；
- per-arm body-free predictions 存于 local-only `dualign-embedding-lab-v4-private/observer-bakeoff-v1`。

## 7. 决策

预注册判据结论为 `architecture_turn_not_supported`。下一阶段继续 embedding/data-supervision 主线，优先完成 V4
正式 2+1 annotation/supply 与真实 work-disjoint confirmation。若之后仍要研究 pairwise observer，推荐使用同一
semantic ledger 训练明确的 `exact / subset / superset / contradiction / unrelated` classifier，并以相同 cases、
同一 paired gate 与 embedding sibling 比较；不要继续在现成 retrieval instruction 上调措辞追分。
