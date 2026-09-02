# Observer MCQ exact-equivalence protocol

Status: frozen before full scoring on 2026-09-01.

## Question and answer contract

Each of the 1,736 frozen observer cases becomes one multiple-choice question. The
reference text is shown first; every existing candidate is shown exactly once.
The model must choose the single candidate that conveys exactly the same
alignment-relevant information. Omissions, additions, contradictions, boundary
shifts, and unsupported details are wrong.

Candidate order is deterministic, using SHA-256 over
`prompt_version | dataset | case_id | candidate_id`. Question order is also a
separate deterministic SHA-256 ordering. The answer parser accepts a single valid
option letter, optionally wrapped as `Answer: A`, `Option A`, `答案：A`, or simple
brackets/punctuation. Explanations, multiple letters, and invalid letters are
parse failures and count as incorrect. No semantic repair is allowed.

## Frozen input scope

- `internal_v1_k3`: 40 four-choice questions; train/dev/diagnostic roles remain
  visible in metrics. This is single-reviewer internal evidence, not a sealed set.
- `internal_reader_natural`: 256 two-choice questions from one work; this asset
  was previously scored and is not newly sealed.
- `validation_v4_development`: 1,440 three-choice questions. Only development is
  opened; rolling-shadow, confirmation, and source-final remain unopened.

The aggregate therefore has 1,736 questions and 4,992 candidates. Its weighted
uniform-random baseline is 618/1,736 = 35.60%.

## Model and runtime control

The controlled comparison is `qwen3.5:2b` versus `qwen3.5:4b`, both already
present in local Ollama. Models run strictly serially. Each receives the same
questions, system prompt, order, `temperature=0`, seed `20260901`, `think=false`,
`num_predict=8`, and `num_ctx=8192`. A fixed trivial warm-up is excluded from
accuracy and reported separately. Ollama API durations and client wall time are
both retained. A model is unloaded before the next model is started.

## Metrics and interpretation

Primary metric: exact-choice accuracy with parse failures counted as wrong.
Report correct/total, Wilson 95% interval, parse failures, total evaluation wall
time, throughput, and p50/p95/p99 per-question latency. Break down accuracy by
dataset, direction, perturbation family, role, and candidate count.

This is an engineering probe of a generative observer, not training, deployment,
or sealed confirmation evidence. Candidate counts differ across datasets, so
cross-dataset raw accuracy is descriptive rather than a difficulty-controlled
ranking. The validation-v4 development set is synthetic/original-generated; the
Reader set is single-work; K3 has single-reviewer limitations.

## Privacy and lineage

Question packets containing text are written only under the private V4 directory.
Public V4 artifacts contain IDs, SHA-256 values, option letters, timings, and
aggregate statistics only. No source text, private body, model weight, teacher
target, checkpoint, or cache is committed.
