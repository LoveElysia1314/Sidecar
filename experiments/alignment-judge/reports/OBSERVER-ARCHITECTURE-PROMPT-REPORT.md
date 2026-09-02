# Architecture-adapted forced-choice prompt report

Date: 2026-09-01
Model: local `qwen3.5:4b`
Scope: opened engineering suite; no training and no sealed confirmation data.

## Prompt adaptation

The proposed prompt allowed a candidate ID, `AMBIGUOUS`, or `NONE`. The actual
observer architecture guarantees exactly one exact candidate, labels visible
choices as `A/B/C/D`, and parses only a single option letter. The tested prompt
therefore removes abstention and matches that contract exactly:

> You are a bilingual or multilingual alignment judge. Choose the one candidate
> that best preserves all alignment-relevant information from the reference and
> adds no unsupported information. Natural translation and faithful paraphrase
> differences are allowed. Any omission, addition, contradiction, or incorrect
> text boundary makes a candidate worse. Do not rewrite or explain the text.
> Return only the best option letter.

Changes from the proposal:

- `bilingual` becomes `bilingual or multilingual` for the zh/en/ja scope;
- `all meaningful information on both sides` becomes the more operationally
  symmetric “preserves all alignment-relevant information ... and adds no
  unsupported information”;
- generic `candidate ID` becomes the actual `option letter` contract;
- `AMBIGUOUS` and `NONE` are removed;
- rewriting and explanation are both forbidden.

## Primary result

The candidate was compared against the original system prompt on the identical
1,736 questions, candidate order, parser, model, temperature 0, seed 20260901,
`think=false`, output budget, and 8K context.

| Prompt | Correct | Accuracy | Wall time | p50 / p95 |
|---|---:|---:|---:|---:|
| Original 4B baseline | 1,561/1,736 | 89.92% | 303.20 s | 172.1 / 207.3 ms |
| Architecture forced-choice | 1,667/1,736 | **96.03%** | 318.48 s | 180.2 / 220.7 ms |

The candidate fixed 116 baseline errors and regressed 10 baseline-correct cases,
for net +106 and +6.11 percentage points. Both were correct on 1,551 and both
wrong on 59. Exact two-sided McNemar `p=4.95e-24`. All 1,736 responses were one
valid letter; neither abstention token nor any parse failure occurred. Runtime
increased by 5.0%.

## Dataset breakdown

| Dataset | Original | Candidate | Change |
|---|---:|---:|---:|
| validation-v4 development, 1,440 | 90.21% | 96.46% | +6.25 pp |
| Reader natural, 256 | 91.80% | 97.66% | +5.86 pp |
| Internal K3, 40 | 67.50% | 70.00% | +2.50 pp |

The pre-registered opened-suite replacement gate passed: overall improved, all
three datasets were non-regressed, all critical addition/omission/boundary/order/
merge-split/K3 families were non-regressed, and parse failures remained zero.
This gate supports advancement on the opened suite, not production replacement.

## Perturbation-family audit

| Family | Original | Candidate | Change |
|---|---:|---:|---:|
| adjacent addition | 79.86% | 93.75% | +13.89 pp |
| low-salience addition | 88.19% | 95.83% | +7.64 pp |
| natural omission | 85.16% | 96.09% | +10.94 pp |
| middle omission | 82.64% | 92.36% | +9.72 pp |
| omission head | 81.94% | 93.75% | +11.81 pp |
| omission tail | 88.19% | 97.92% | +9.72 pp |
| order perturbation | 88.89% | 95.83% | +6.94 pp |
| merge/split missing sub-event | 95.83% | 100.00% | +4.17 pp |
| boundary shift | 99.31% | 100.00% | +0.69 pp |
| K3 mixed hard group | 67.50% | 70.00% | +2.50 pp |

One non-critical family regressed: attribute counterfactual moved from 97.22% to
95.14%, or 140/144 to 137/144. This three-case loss is real and must remain in
future non-inferiority checks even though the pre-registered critical-family gate
passed.

## Comparison on the error-mined 422 cases

For descriptive failure analysis only:

| Prompt | Correct | Accuracy |
|---|---:|---:|
| Original baseline | 247/422 | 58.53% |
| Prior bidirectional entailment | 293/422 | 69.43% |
| Architecture forced-choice | 357/422 | **84.60%** |

This confirms that the new wording is not merely recovering easy cases. However,
the 422 cases were selected from prior model errors and cannot be treated as an
independent evaluation distribution.

## Option-position audit

The same deterministic permutation was used for both prompts. Gold positions
were A=613, B=596, C=514, D=13.

| Gold option | Original | Candidate | Net paired change |
|---|---:|---:|---:|
| A | 450/613 (73.41%) | 558/613 (91.03%) | +108 |
| B | 590/596 (98.99%) | 591/596 (99.16%) | +1 |
| C | 509/514 (99.03%) | 507/514 (98.64%) | -2 |
| D | 12/13 (92.31%) | 11/13 (84.62%) | -1 |

The entire +106 aggregate gain decomposes into +108 on gold-A cases and -2 over
B/C/D combined. The original prompt predicted A only 453 times despite 613 gold-A
cases; the candidate predicted A 566 times. It therefore appears to remove a
large option-A avoidance present under the original wording.

This does not invalidate the paired improvement: both prompts saw exactly the
same option order. It does mean the mechanism is not established as purely
semantic, and the current test does not prove permutation invariance. Before any
general replacement claim, rerun a frozen 50–100 case audit under a second
deterministic permutation and score answer consistency as well as accuracy.

## Relation to the supplied external analysis

The result is consistent with the supplied hypothesis that this non-thinking 4B
model responds better to a compact semantic criterion than to a procedural
checklist. The candidate is shorter and less procedural than the failed
`two_way_coverage` and `near_miss_elimination` prompts, while balancing omission
and addition in one sentence.

It is not the supplied P5 semantic-set, P6 substitutability, or P7 compact-mutual-
entailment proposal. Those remain separate hypotheses. They were not introduced
mid-run, and decoder settings were not changed.

## Decision and next evidence

Advance this prompt as the leading general 4B candidate. Do not yet replace the
general baseline in production or call 96.03% a fresh validation estimate: the
suite is fully opened, development-heavy, and the improvement is concentrated in
one gold option position.

The smallest decisive next experiment is a frozen permutation audit using the
same prompts and cases but a different deterministic option rotation. After that,
the scientifically important confirmation should use new, human-gold cases from
the real upstream Dualign trigger distribution, with addition and attribute
counterfactual registered as non-inferiority guards.
