# 4B wrong-union prompt optimization report

Date: 2026-09-01
Status: completed exploratory prompt-development round; no training and no sealed
evaluation data opened.

## Outcome

The union of errors from the earlier `qwen3.5:2b` and `qwen3.5:4b` runs produced
a new private raw corpus of **422 questions**. It contains the original reference,
all candidates, the exact answer, source metadata, and both baseline predictions.
The public manifest contains only IDs, hashes, labels, and option letters.

Using only `qwen3.5:4b`, the best tested instruction was
`bidirectional_entailment`. It improved the pre-registered 296-case tuning split
from **173/296 (58.45%)** to **208/296 (70.27%)**, then improved the one-time
126-case prompt-check split from **74/126 (58.73%)** to **85/126 (67.46%)**.

The check result is directionally positive but modest: it fixed 20 baseline errors
and regressed 9 baseline-correct answers, net +11. Its two-sided exact McNemar
result is `p=0.0614`, so the check alone does not cross the conventional 0.05
threshold. This is useful prompt-development evidence, not a fresh generalization
claim.

## Raw corpus composition

| Selection reason | Cases |
|---|---:|
| Both 2B and 4B wrong | 145 |
| Only 2B wrong | 247 |
| Only 4B wrong | 30 |
| Union | 422 |

| Source | Cases |
|---|---:|
| validation-v4 development | 368 |
| Reader natural, previously scored | 33 |
| Internal K3, single reviewer | 21 |

The stratified deterministic split contains 296 prompt-tuning and 126
prompt-check cases. Because membership was selected using prior model errors,
neither split is an independent validation set.

## Tuning comparison

Only the system instruction changed. Question bodies, candidate order, parser,
model, temperature, seed, 8K context, and generation limit remained fixed.

| System instruction | Correct | Accuracy | Net paired change vs baseline | Wall time |
|---|---:|---:|---:|---:|
| Original baseline, reused | 173/296 | 58.45% | — | reused |
| `two_way_coverage` | 144/296 | 48.65% | -29 | 59.88 s |
| `near_miss_elimination` | 130/296 | 43.92% | -43 | 55.60 s |
| `bidirectional_entailment` | 208/296 | 70.27% | +35 | 56.49 s |

The long explicit checklist and “find the smallest mismatch” framing both made
the 4B model worse. More instructions did not produce more careful judging. The
shorter mutual-entailment framing was the only positive arm.

## Selected instruction

> Treat this as lossless translation verification, not relevance ranking. The
> correct candidate must satisfy both directions: the reference entails the
> candidate and the candidate entails the reference, at the level of
> alignment-relevant facts and boundaries. Reject an option if it drops a
> reference fact or introduces an unsupported fact, even if the difference is
> small. Check negation, entities, attributes, numbers, time, and event order.
> Reply with only the best option letter.

All 422 responses were single valid letters; there were no parse failures.

## Descriptive full-union view

Combining the selected tuning and check results only for error analysis gives
293/422 (69.43%), versus 247/422 (58.53%) for the original 4B prompt. Paired
counts are 216 both correct, 98 both wrong, 77 selected-prompt-only correct, and
31 baseline-only correct: net +46, exact McNemar `p=1.12e-5`.

This 69.43% must not be reported as model accuracy: the 422 cases were selected
because at least one earlier model failed, and the prompt was selected on 296 of
them.

| Source | Original prompt | Selected prompt | Change |
|---|---:|---:|---:|
| Reader natural (33) | 36.36% | 81.82% | +45.45 pp |
| validation-v4 development (368) | 61.68% | 70.11% | +8.42 pp |
| Internal K3 (21) | 38.10% | 38.10% | 0.00 pp |

The prompt does not solve K3. On the six K3 prompt-check cases it moved from 2/6
to 1/6, so the apparent aggregate gain must not be generalized to that lineage.

## What improved and what regressed

On this error-mined corpus, the selected prompt strongly improved omission-type
cases: natural omission 24%→84%, middle omission 44.44%→73.33%, omission-head
51.85%→83.33%, and omission-tail 61.36%→81.82%. It also improved order
perturbation 69.81%→84.91% and merge/split missing-sub-event 78.57%→100%.

The same prompt regressed addition detection: adjacent addition fell
47.27%→27.27% and low-salience addition 61.36%→36.36%. Boundary shift declined
slightly from 96.88% to 93.75%. Therefore `bidirectional_entailment` is **not**
supported as a universal replacement for the original prompt. It is a promising
targeted second-pass hypothesis for omission/order failures, requiring fresh
source-balanced evaluation before any routing or deployment decision.

## Runtime and operational controls

The selected prompt took 80.35 seconds for all 422 error-mined cases, averaging
190.4 ms/question (p50 185.5 ms, p95 232.9 ms, p99 332.1 ms). The reused original
prompt took 76.52 seconds on those same cases. The selected wording therefore
added about 5.0% wall time.

All valid arms ran at 8K context with the model 100% GPU-resident and were
strictly serialized. Four partial attempts made while a game occupied VRAM were
preserved as diagnostics and excluded: 33, 10, 9, and 8 rows. No low-context or
CPU-offloaded result entered model selection.

## Decision

Keep the original prompt as the general 4B baseline. Retain
`bidirectional_entailment` as the sole candidate from this round, specifically
for a future controlled omission/order-focused second-pass experiment. Do not
retain `two_way_coverage` or `near_miss_elimination`, and do not design another
prompt from the opened prompt-check results in this round.
