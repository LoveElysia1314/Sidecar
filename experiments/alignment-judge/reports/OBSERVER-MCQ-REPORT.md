# Local Ollama multiple-choice observer report

Date: 2026-09-01
Scope: engineering probe; no training; no sealed confirmation data opened.

## Result

The frozen 1,736-case observer collection was converted into deterministic
strict-equivalence multiple-choice questions and answered by two already-local
Ollama models. `qwen3.5:4b` was the clear aggregate winner: **1,561/1,736
(89.92%)**, versus **1,344/1,736 (77.42%)** for `qwen3.5:2b`. Neither run had a
parse failure.

| Model | Correct | Accuracy (Wilson 95%) | Net evaluation time | Questions/s | p50 / p95 / p99 |
|---|---:|---:|---:|---:|---:|
| `qwen3.5:2b` | 1,344 / 1,736 | 77.42% (75.39–79.32%) | 172.66 s | 10.06 | 97.9 / 119.7 / 146.7 ms |
| `qwen3.5:4b` | 1,561 / 1,736 | 89.92% (88.41–91.25%) | 303.20 s | 5.73 | 172.1 / 207.3 / 279.0 ms |

The fixed warm-up, excluded from accuracy and net evaluation time, took 3.02 s
for 2B (2.87 s model load) and 3.44 s for 4B (3.24 s model load). The 4B run
gained 12.50 percentage points while taking 75.6% more net wall time.

Uniform random selection is not 33.3% here because the three sources have
different candidate counts. The weighted random baseline is 618/1,736 = 35.60%.

## Dataset breakdown

| Dataset | Choices | Questions | 2B | 4B | 4B minus 2B |
|---|---:|---:|---:|---:|---:|
| validation-v4 development | 3 | 1,440 | 1,089 (75.63%) | 1,299 (90.21%) | +14.58 pp |
| Reader natural, previously scored | 2 | 256 | 236 (92.19%) | 235 (91.80%) | -0.39 pp |
| Internal K3, single reviewer | 4 | 40 | 19 (47.50%) | 27 (67.50%) | +20.00 pp |

The aggregate improvement is concentrated in validation-v4 development and the
small K3 probe. The natural Reader subset is effectively tied: 2B alone fixed 13
cases, 4B alone fixed 12, and the exact paired test is p=1.0. This prevents the
aggregate result from being read as a universal 4B win on every source.

## Paired comparison

Across the identical 1,736 questions, both models were correct on 1,314 and both
were wrong on 145. The 4B model alone was correct on 247; the 2B model alone was
correct on 30, for a net +217 cases. They returned the same option on 1,455
questions (83.81%). The two-sided exact McNemar result is
`p = 1.30e-43`; this is strong evidence for a paired difference on this opened
engineering set, not a sealed generalization claim.

| Dataset | 2B only correct | 4B only correct | Net 4B |
|---|---:|---:|---:|
| validation-v4 development | 17 | 227 | +210 |
| Reader natural | 13 | 12 | -1 |
| Internal K3 | 0 | 8 | +8 |

## Direction breakdown

| Direction | Questions | 2B | 4B |
|---|---:|---:|---:|
| en→ja | 240 | 74.58% | 89.58% |
| en→zh | 378 | 79.89% | 92.59% |
| ja→en | 240 | 79.58% | 89.17% |
| ja→zh | 240 | 77.08% | 90.42% |
| zh→en | 398 | 79.65% | 89.20% |
| zh→ja | 240 | 70.83% | 87.50% |

The worst direction was zh→ja for both models, though 4B reduced the gap
substantially. Counts combine sources where their direction labels coincide and
therefore should not be treated as source-controlled language comparisons.

## Perturbation observations

On validation-v4 development, 2B was weakest on omission-head (62.50%), order
perturbation (63.19%), and adjacent addition (63.89%). The 4B model improved all
three to 81.94%, 88.89%, and 79.86%, respectively. Its remaining weakest
validation-v4 family was adjacent addition (79.86%), followed by omission-head
(81.94%) and middle omission (82.64%). Both models reached 100% on same-topic
mismatch.

The Reader natural subset behaves differently: 4B improved boundary cases from
93.75% to 98.44% but regressed omission from 90.63% to 85.16%. That source is a
single-work, previously scored set, so this is a targeted diagnostic rather than
a population estimate.

## Protocol and artifact boundaries

- Every source case is used once. Candidate and question orders are independent,
  deterministic SHA-256 orderings.
- The frozen prompt asks for exact alignment-equivalence and explicitly penalizes
  omission, addition, contradiction, boundary shift, and unsupported detail.
- Both models used Ollama `0.33.2`, `temperature=0`, seed `20260901`,
  `think=false`, `num_predict=8`, and `num_ctx=8192`. They ran strictly serially
  and were unloaded between runs.
- The parser accepts one valid option letter with only a small declared wrapper;
  explanations or multiple letters count as wrong. Both full runs had 0/1,736
  parse failures.
- Private question packets contain the reference and candidate bodies. Public V4
  files contain only stable IDs, hashes, letters, timings, and aggregates.
- Only validation-v4 development was opened. Rolling-shadow, confirmation, and
  source-final were not opened. No training or deployment decision was made.

## Decision

For a local generative multiple-choice observer, `qwen3.5:4b` is the better
default on this probe: its +217 paired net wins are large relative to its 75.6%
runtime premium, and it remains well within interactive batch latency on the
local RTX 4060 Laptop GPU. Retain `qwen3.5:2b` only when throughput matters more
than the substantial accuracy loss.

Do not treat this as evidence that generative MCQ should replace the existing
embedding scorer. The model sees all candidates jointly, candidate counts differ
by source, and none of these results is sealed confirmation evidence. The next
scientifically useful step would be a pre-registered, source-balanced comparison
on fresh unopened data, not tuning against these 1,736 opened answers.
