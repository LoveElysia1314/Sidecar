# Wrong-union prompt ablation protocol

Status: frozen before prompt-variant scoring on 2026-09-01.

## Corpus construction

Select the union of the full-run errors from `qwen3.5:2b` and `qwen3.5:4b` on
the deterministic 1,736-question MCQ corpus. The expected union is 422 cases:
145 both wrong, 247 where only 2B is wrong, and 30 where only 4B is wrong. The
private raw corpus retains reference text, all original candidates, the exact
answer, option order, source metadata, and both baseline predictions. The public
manifest retains only IDs, hashes, labels, letters, and selection metadata.

This is deliberately error-mined data. It is a prompt-development corpus, not a
fresh validation set and not evidence of population accuracy.

## Development split

Within each `(dataset, error_pattern)` stratum, order cases by SHA-256 over the
fixed split seed, dataset, and case ID. Assign rounded 70% to `prompt_tuning` and
the remainder to `prompt_check`. Expected totals are 296 tuning and 126 check.
All prompt variants run on tuning. Select one winner by tuning accuracy, with
paired net improvement over baseline as the first tie-break and lower wall time
as the second. Run only that winner once on check.

Because the corpus itself was selected using prior 4B errors, prompt-check only
reduces variant-selection overfitting; it does not restore independent or sealed
generalization evidence.

## Controlled arms

Use only local `qwen3.5:4b`. Reuse the exact same question bodies, candidate
orders, answer parser, and generation settings from the baseline (`temperature=0`,
seed `20260901`, `think=false`, `num_predict=8`, `num_ctx=8192`). Change only the
system-level method instruction:

1. `two_way_coverage`: explicit reference-to-candidate and candidate-to-reference
   proposition coverage with entity, attribute, negation, quantity, time, order,
   and boundary checks.
2. `near_miss_elimination`: assume fluent near-miss decoys and eliminate an option
   at its smallest semantic mismatch.
3. `bidirectional_entailment`: require lossless mutual entailment rather than
   relevance.

The previously completed 4B answers provide the unchanged baseline; do not spend
another run to reproduce them. The complete, fully GPU-resident 8K
`two_way_coverage` run is eligible. Partially CPU-offloaded attempts made while a
game occupied the GPU are operational diagnostics only and are excluded.

## Metrics and stopping rule

Primary: exact-choice accuracy, with parse failures wrong. Also report paired
wrong-to-correct and correct-to-wrong flips versus the baseline on the same split,
Wilson 95% interval, source/family/direction breakdown, total wall time, and
p50/p95/p99. Do not iterate new prompts after viewing prompt-check in this round.

Models run serially and are unloaded after each arm. No training, weights,
checkpoints, shadow set, confirmation set, or source-final data are opened.
