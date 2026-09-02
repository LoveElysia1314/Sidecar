# Architecture-adapted forced-choice prompt protocol

Status: frozen before scoring on 2026-09-01.

## Requested prompt and architecture adaptation

The user proposed a bilingual alignment judge that may return a candidate ID,
`AMBIGUOUS`, or `NONE`, and explicitly requested removal of the two abstention
outputs. The actual observer architecture differs in four relevant ways:

1. It covers Chinese, English, and Japanese, so the judge is multilingual.
2. Every case is validated to contain exactly one exact candidate.
3. Candidates are exposed to the model as option letters `A/B/C/D`; the parser
   accepts a single valid option letter, not an arbitrary internal candidate ID.
4. The model must not rewrite or explain; parse failures count as incorrect.

Frozen candidate system prompt:

> You are a bilingual or multilingual alignment judge. Choose the one candidate
> that best preserves all alignment-relevant information from the reference and
> adds no unsupported information. Natural translation and faithful paraphrase
> differences are allowed. Any omission, addition, contradiction, or incorrect
> text boundary makes a candidate worse. Do not rewrite or explain the text.
> Return only the best option letter.

Neither `AMBIGUOUS` nor `NONE` remains in the runtime prompt.

## Comparison

Run only local `qwen3.5:4b`. Use the already-opened 1,736-question suite and its
previous 4B answers as the paired baseline. Keep question text, candidate order,
parser, temperature 0, seed 20260901, `think=false`, `num_predict=8`, and 8K
context unchanged. Only the system prompt changes.

This is further development on an opened engineering suite. Do not open
rolling-shadow, confirmation, or source-final data, and do not call the result a
fresh validation estimate.

## Metrics and decision rule

Report overall and per-dataset accuracy, paired gains/losses, exact McNemar test,
latency, direction, role, candidate count, and every perturbation family. Because
the previous mutual-entailment prompt improved omissions while regressing
additions, adjacent-addition and low-salience-addition are mandatory audit rows.

Support general replacement on this opened suite only if all are true:

- overall accuracy strictly improves;
- every dataset is non-regressed;
- every critical addition, omission, boundary, order, merge/split, and K3 family
  is non-regressed;
- parse failures remain zero.

Failure of this gate does not make the prompt useless; it means the evidence does
not support replacing the general baseline.
