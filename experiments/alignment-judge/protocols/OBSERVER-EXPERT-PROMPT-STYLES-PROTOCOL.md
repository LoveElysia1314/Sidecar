# Expert prompt styles comparison protocol

Status: frozen before P5/P6/P7 scoring on 2026-09-01.

## Objective

Test the three prompt styles proposed in the supplied expert review against the
current leading architecture-forced-choice prompt. Use only local
`qwen3.5:4b`. This is prompt development on the already-opened 1,736-question
suite, not fresh validation.

## Frozen styles

### P5 semantic set equality

> Treat the reference and each candidate as sets of alignment-relevant
> information. Choose the candidate whose information set is the same as the
> reference: it must be neither a subset nor a superset. Faithful translation or
> paraphrase may change the wording. Reply with only the best option letter.

### P6 mutual substitutability

> Choose the candidate that could replace the reference without changing any
> alignment-relevant meaning or boundary. If the replacement would lose
> information or introduce information, that candidate is wrong. Faithful
> translation or paraphrase is allowed. Reply with only the best option letter.

### P7 compact balanced entailment

> Choose the candidate that is mutually entailing with the reference.
> Reference-to-candidate and candidate-to-reference are equally required; failure
> in either direction makes the candidate wrong. Faithful translation or
> paraphrase is allowed. Reply with only the best option letter.

## Controls and selection

Keep question text, deterministic candidate order, parser, model, temperature 0,
seed 20260901, `think=false`, output budget, and 8K context fixed. Models run
strictly serially and are unloaded between styles. Do not change decoder settings.

The current leader is `architecture_forced_single_choice/v1` at 1,667/1,736.
A challenger is eligible only if it strictly improves overall accuracy, has
positive paired net flips, does not regress any dataset, does not regress adjacent
addition, low-salience addition, attribute counterfactual, or K3, and has zero
parse failures. Among eligible challengers choose highest accuracy, then paired
net, then lower wall time. If none is eligible, retain the current leader.

After the opened-suite comparison, run the current leader and the strongest
challenger on a frozen 300-case second deterministic option permutation. Report
accuracy and selected-candidate consistency across permutations. This audit is
not fresh semantic validation but detects prompt-specific option-symbol bias.

Do not open rolling-shadow, confirmation, or source-final data. Do not design a
fourth style after seeing these results.
