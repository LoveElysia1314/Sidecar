"""Run the body-free Dualign observer bake-off on frozen local case assets.

The script never writes source text.  Per-arm outputs contain stable case IDs,
hashes, scores, metrics, and runtime metadata only.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import platform
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

RETRIEVAL_INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
STRICT_EQUIVALENCE_INSTRUCTION = (
    "Determine whether the Document conveys exactly the same alignment-relevant "
    "information as the Query. Penalize any omission, addition, contradiction, "
    "or unsupported specification. Do not reward mere topical relevance."
)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    text: str
    exact: bool


@dataclass(frozen=True)
class Case:
    dataset: str
    case_id: str
    direction: str
    work_or_cluster_id: str
    role: str
    anchor: str
    candidates: tuple[Candidate, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_split_roles(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    roles: dict[str, str] = {}
    for assignment in payload.get("assignments", []):
        role = str(assignment["role"])
        for identifier in assignment.get("canonical_group_ids", []):
            roles[str(identifier)] = role
    for role in ("train", "dev", "diagnostic_holdout"):
        value = payload.get(role)
        if isinstance(value, list):
            identifiers = value
        elif isinstance(value, dict):
            identifiers = value.get("canonical_group_ids", value.get("group_ids", []))
        else:
            identifiers = []
        for identifier in identifiers:
            roles[str(identifier)] = role
    if not roles:
        for role, value in payload.get("splits", {}).items():
            identifiers = value.get("canonical_group_ids", value.get("group_ids", []))
            for identifier in identifiers:
                roles[str(identifier)] = str(role)
    return roles


def extract_hashed_text(value: Any, label: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        raise ValueError(f"{label} must be a hashed text object")
    text = value["text"]
    expected = value.get("sha256")
    if expected != sha256_text(text):
        raise ValueError(f"{label} text SHA-256 mismatch")
    return text


def load_private_groups(path: Path, split_path: Path) -> list[Case]:
    split_roles = load_split_roles(split_path)
    cases: list[Case] = []
    for row in read_jsonl(path):
        case_id = str(row["canonical_group_id"])
        candidates = [
            Candidate(
                "positive",
                "exact",
                extract_hashed_text(row["positive"], f"{case_id}:positive"),
                True,
            )
        ]
        for negative in row["negatives"]:
            candidates.append(
                Candidate(
                    str(negative["candidate_id"]),
                    str(negative["negative_primary_family"]),
                    extract_hashed_text(
                        negative, f"{case_id}:{negative['candidate_id']}"
                    ),
                    False,
                )
            )
        cases.append(
            Case(
                dataset="internal_v1_k3",
                case_id=case_id,
                direction=str(row["direction"]),
                work_or_cluster_id=str(row["work_lineage_id"]),
                role=split_roles.get(case_id, "seen_unsplit"),
                anchor=extract_hashed_text(row["anchor"], f"{case_id}:anchor"),
                candidates=tuple(candidates),
            )
        )
    return cases


def load_natural_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for row in read_jsonl(path):
        cases.append(
            Case(
                dataset="internal_reader_natural",
                case_id=str(row["id"]),
                direction=str(row["direction"]),
                work_or_cluster_id=str(row["work_id_sha256"]),
                role="previously_scored_heldout",
                anchor=str(row["anchor"]),
                candidates=(
                    Candidate("positive", "exact", str(row["positive"]), True),
                    Candidate(
                        "negative",
                        str(row["negative_type"]),
                        str(row["negative"]),
                        False,
                    ),
                ),
            )
        )
    return cases


def load_validation_development(path: Path) -> list[Case]:
    cases: list[Case] = []
    for row in read_jsonl(path):
        cases.append(
            Case(
                dataset="validation_v4_development",
                case_id=str(row["id"]),
                direction=str(row["direction"]),
                work_or_cluster_id=str(row["split_cluster_id"]),
                role="development",
                anchor=str(row["anchor"]),
                candidates=(
                    Candidate("exact", "exact", str(row["exact"]), True),
                    Candidate(
                        "partial", str(row["family"]), str(row["partial"]), False
                    ),
                    Candidate("unrelated", "unrelated", str(row["unrelated"]), False),
                ),
            )
        )
    return cases


def load_cases(args: argparse.Namespace) -> tuple[list[Case], dict[str, Any]]:
    sources = {
        "private_groups": Path(args.private_groups).resolve(),
        "private_split": Path(args.private_split).resolve(),
        "natural_cases": Path(args.natural_cases).resolve(),
        "validation_development": Path(args.validation_development).resolve(),
    }
    cases = [
        *load_private_groups(sources["private_groups"], sources["private_split"]),
        *load_natural_cases(sources["natural_cases"]),
        *load_validation_development(sources["validation_development"]),
    ]
    identifiers = [(case.dataset, case.case_id) for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate dataset/case identifiers")
    expected = {
        "internal_v1_k3": 40,
        "internal_reader_natural": 256,
        "validation_v4_development": 1440,
    }
    actual = Counter(case.dataset for case in cases)
    if dict(actual) != expected:
        raise ValueError(
            f"case counts changed: expected={expected}, actual={dict(actual)}"
        )
    for case in cases:
        if sum(candidate.exact for candidate in case.candidates) != 1:
            raise ValueError(
                f"case {case.case_id} does not have exactly one exact candidate"
            )
    source_receipt = {
        key: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for key, path in sources.items()
    }
    source_receipt["counts"] = dict(actual)
    source_receipt["internal_v1_role_counts"] = dict(
        sorted(
            Counter(
                case.role for case in cases if case.dataset == "internal_v1_k3"
            ).items()
        )
    )
    if source_receipt["internal_v1_role_counts"] != {
        "dev": 8,
        "diagnostic_holdout": 8,
        "train": 24,
    }:
        raise ValueError(
            "internal v1 split roles changed: "
            f"{source_receipt['internal_v1_role_counts']}"
        )
    source_receipt["total_cases"] = len(cases)
    source_receipt["total_pairs"] = sum(len(case.candidates) for case in cases)
    return cases, source_receipt


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    margins = [float(row["margin"]) for row in rows]
    correct = sum(bool(row["positive_top1"]) for row in rows)
    return {
        "cases": len(rows),
        "top1_correct": correct,
        "top1_rate": correct / len(rows),
        "margin_mean": statistics.fmean(margins),
        "margin_p10": quantile(margins, 0.10),
        "margin_min": min(margins),
    }


def summarize_evaluation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"overall": metric_summary(rows)}
    by_dataset: dict[str, Any] = {}
    for dataset in sorted({str(row["dataset"]) for row in rows}):
        selected = [row for row in rows if row["dataset"] == dataset]
        dataset_summary = metric_summary(selected)
        dataset_summary["by_direction"] = {
            direction: metric_summary(
                [row for row in selected if row["direction"] == direction]
            )
            for direction in sorted({str(row["direction"]) for row in selected})
        }
        dataset_summary["by_role"] = {
            role: metric_summary([row for row in selected if row["role"] == role])
            for role in sorted({str(row["role"]) for row in selected})
        }
        comparisons: list[dict[str, Any]] = []
        for row in selected:
            comparisons.extend(row["negative_comparisons"])
        dataset_summary["by_family"] = {
            family: metric_summary(
                [
                    {
                        "margin": item["margin"],
                        "positive_top1": item["exact_wins"],
                    }
                    for item in comparisons
                    if item["family"] == family
                ]
            )
            for family in sorted({str(item["family"]) for item in comparisons})
        }
        by_dataset[dataset] = dataset_summary
    summary["by_dataset"] = by_dataset
    directions: dict[str, Any] = {}
    for direction in sorted({str(row["direction"]) for row in rows}):
        directions[direction] = metric_summary(
            [row for row in rows if row["direction"] == direction]
        )
    summary["by_direction_all_datasets"] = directions
    worst_direction = min(directions, key=lambda key: directions[key]["top1_rate"])
    summary["worst_direction_by_top1"] = {
        "direction": worst_direction,
        **directions[worst_direction],
    }
    return summary


def evaluate_scores(
    cases: list[Case], score_by_pair: dict[tuple[str, str, str], float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        scored: list[tuple[Candidate, float]] = []
        anchor_hash = sha256_text(case.anchor)
        for candidate in case.candidates:
            candidate_hash = sha256_text(candidate.text)
            key = (case.dataset, case.case_id, candidate.candidate_id)
            scored.append((candidate, float(score_by_pair[key])))
        positive = next(item for item in scored if item[0].exact)
        negatives = [item for item in scored if not item[0].exact]
        hardest = max(negatives, key=lambda item: item[1])
        margin = positive[1] - hardest[1]
        rows.append(
            {
                "dataset": case.dataset,
                "case_id": case.case_id,
                "direction": case.direction,
                "work_or_cluster_id": case.work_or_cluster_id,
                "role": case.role,
                "anchor_sha256": anchor_hash,
                "positive_candidate_id": positive[0].candidate_id,
                "positive_sha256": sha256_text(positive[0].text),
                "positive_score": positive[1],
                "hardest_negative_candidate_id": hardest[0].candidate_id,
                "hardest_negative_family": hardest[0].family,
                "hardest_negative_sha256": sha256_text(hardest[0].text),
                "hardest_negative_score": hardest[1],
                "margin": margin,
                "positive_top1": margin > 0.0,
                "negative_comparisons": [
                    {
                        "candidate_id": candidate.candidate_id,
                        "candidate_sha256": sha256_text(candidate.text),
                        "family": candidate.family,
                        "negative_score": score,
                        "margin": positive[1] - score,
                        "exact_wins": positive[1] > score,
                    }
                    for candidate, score in negatives
                ],
            }
        )
    return rows


def pair_items(cases: list[Case]) -> list[tuple[Case, Candidate]]:
    return [(case, candidate) for case in cases for candidate in case.candidates]


def last_token_pool(last_hidden_states: Any, attention_mask: Any) -> Any:
    import torch

    if bool(torch.all(attention_mask[:, -1] == 1)):
        return last_hidden_states[:, -1]
    lengths = attention_mask.sum(dim=1) - 1
    batches = torch.arange(
        last_hidden_states.shape[0], device=last_hidden_states.device
    )
    return last_hidden_states[batches, lengths]


def score_embedding(
    cases: list[Case], base_model: Path, adapter: Path | None, batch_size: int
) -> tuple[dict[tuple[str, str, str], float], dict[str, Any]]:
    import torch
    from torch.nn import functional
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        base_model, local_files_only=True, trust_remote_code=True, padding_side="left"
    )
    texts_by_hash: dict[str, str] = {}
    for case in cases:
        texts_by_hash.setdefault(sha256_text(case.anchor), case.anchor)
        for candidate in case.candidates:
            texts_by_hash.setdefault(sha256_text(candidate.text), candidate.text)
    text_items = sorted(texts_by_hash.items())
    token_lengths = [
        len(tokenizer.encode(text, add_special_tokens=True)) for _, text in text_items
    ]
    model = AutoModel.from_pretrained(
        base_model,
        local_files_only=True,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    if adapter is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter, local_files_only=True)
    device = torch.device("cuda")
    model = model.to(device).eval()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    start = time.perf_counter()
    embeddings: dict[str, Any] = {}
    with torch.inference_mode():
        for start_index in range(0, len(text_items), batch_size):
            batch = text_items[start_index : start_index + batch_size]
            encoded = tokenizer(
                [text for _, text in batch],
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            output = model(**encoded, use_cache=False)
            vectors = (
                functional.normalize(
                    last_token_pool(
                        output.last_hidden_state, encoded["attention_mask"]
                    ),
                    p=2,
                    dim=1,
                )
                .float()
                .cpu()
            )
            for (text_hash, _), vector in zip(batch, vectors, strict=True):
                embeddings[text_hash] = vector
    scores: dict[tuple[str, str, str], float] = {}
    for case, candidate in pair_items(cases):
        scores[(case.dataset, case.case_id, candidate.candidate_id)] = float(
            embeddings[sha256_text(case.anchor)]
            @ embeddings[sha256_text(candidate.text)]
        )
    elapsed = time.perf_counter() - start
    runtime = {
        "device": torch.cuda.get_device_name(device),
        "dtype": "bfloat16",
        "batch_size": batch_size,
        "unique_texts": len(text_items),
        "pairs": len(scores),
        "max_observed_tokens": max(token_lengths),
        "p95_observed_tokens": quantile(
            [float(value) for value in token_lengths], 0.95
        ),
        "hard_token_truncation": False,
        "elapsed_seconds": elapsed,
        "milliseconds_per_pair_amortized": elapsed * 1000.0 / len(scores),
        "pairs_per_second_amortized": len(scores) / elapsed,
        "peak_cuda_allocated_gib": torch.cuda.max_memory_allocated(device) / 1024**3,
        "peak_cuda_reserved_gib": torch.cuda.max_memory_reserved(device) / 1024**3,
    }
    del model, tokenizer, embeddings
    gc.collect()
    torch.cuda.empty_cache()
    return scores, runtime


def reranker_tokens(
    tokenizer: Any, instruction: str, query: str, document: str
) -> list[int]:
    prefix = (
        "<|im_start|>system\nJudge whether the Document meets the requirements "
        "based on the Query and the Instruct provided. Note that the answer can "
        'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    )
    suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    body = f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}"
    return [
        *tokenizer.encode(prefix, add_special_tokens=False),
        *tokenizer.encode(body, add_special_tokens=False),
        *tokenizer.encode(suffix, add_special_tokens=False),
    ]


def score_reranker(
    cases: list[Case], model_path: Path, instruction: str, batch_size: int
) -> tuple[dict[tuple[str, str, str], float], dict[str, Any]]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        model_path, local_files_only=True, trust_remote_code=True, padding_side="left"
    )
    tokenizer.pad_token = tokenizer.eos_token
    items = pair_items(cases)
    tokenized = [
        reranker_tokens(tokenizer, instruction, case.anchor, candidate.text)
        for case, candidate in items
    ]
    model = (
        AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
        )
        .to("cuda")
        .eval()
    )
    yes_id = tokenizer.convert_tokens_to_ids("yes")
    no_id = tokenizer.convert_tokens_to_ids("no")
    if yes_id in (None, tokenizer.unk_token_id) or no_id in (
        None,
        tokenizer.unk_token_id,
    ):
        raise ValueError("reranker yes/no token IDs are unavailable")
    device = torch.device("cuda")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    start = time.perf_counter()
    values: list[float] = []
    with torch.inference_mode():
        for start_index in range(0, len(tokenized), batch_size):
            batch_ids = tokenized[start_index : start_index + batch_size]
            encoded = tokenizer.pad(
                {"input_ids": batch_ids}, padding=True, return_tensors="pt"
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            try:
                output = model(
                    **encoded, use_cache=False, logits_to_keep=1, return_dict=True
                )
            except TypeError:
                output = model(**encoded, use_cache=False, return_dict=True)
            logits = output.logits[:, -1, :].float()
            values.extend((logits[:, yes_id] - logits[:, no_id]).cpu().tolist())
    scores = {
        (case.dataset, case.case_id, candidate.candidate_id): float(value)
        for (case, candidate), value in zip(items, values, strict=True)
    }
    elapsed = time.perf_counter() - start
    runtime = {
        "device": torch.cuda.get_device_name(device),
        "dtype": "bfloat16",
        "score": "yes_logit_minus_no_logit",
        "batch_size": batch_size,
        "pairs": len(scores),
        "max_observed_tokens": max(map(len, tokenized)),
        "p95_observed_tokens": quantile(
            [float(len(value)) for value in tokenized], 0.95
        ),
        "hard_token_truncation": False,
        "elapsed_seconds": elapsed,
        "milliseconds_per_pair_amortized": elapsed * 1000.0 / len(scores),
        "pairs_per_second_amortized": len(scores) / elapsed,
        "peak_cuda_allocated_gib": torch.cuda.max_memory_allocated(device) / 1024**3,
        "peak_cuda_reserved_gib": torch.cuda.max_memory_reserved(device) / 1024**3,
        "yes_token_id": int(yes_id),
        "no_token_id": int(no_id),
    }
    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    return scores, runtime


def model_receipt(path: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for name in (
        "model.safetensors",
        "adapter_model.safetensors",
        "config.json",
        "adapter_config.json",
    ):
        candidate = path / name
        if candidate.exists():
            files[name] = {
                "bytes": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
    return {"path": str(path.resolve()), "files": files}


def command_validate(args: argparse.Namespace) -> None:
    cases, sources = load_cases(args)
    family_counts: Counter[str] = Counter()
    direction_counts = Counter(case.direction for case in cases)
    for case in cases:
        family_counts.update(
            candidate.family for candidate in case.candidates if not candidate.exact
        )
    payload = {
        "schema": "dualign-observer-bakeoff-validation/v1",
        "body_text_in_output": False,
        "sources": sources,
        "direction_counts": dict(sorted(direction_counts.items())),
        "negative_family_comparisons": dict(sorted(family_counts.items())),
    }
    if args.output:
        write_json(Path(args.output), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def command_score(args: argparse.Namespace) -> None:
    import torch
    import transformers

    cases, sources = load_cases(args)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this bake-off")
    arm = str(args.arm)
    instruction: str | None = None
    if arm == "embedding_base":
        scores, runtime = score_embedding(
            cases, Path(args.embedding_model), None, args.embedding_batch_size
        )
        model = model_receipt(Path(args.embedding_model))
        score_protocol = "raw_text_last_token_l2_cosine"
    elif arm in {"embedding_l1", "embedding_l2"}:
        adapter_arg = args.l1_adapter if arm == "embedding_l1" else args.l2_adapter
        adapter = Path(adapter_arg)
        scores, runtime = score_embedding(
            cases, Path(args.embedding_model), adapter, args.embedding_batch_size
        )
        model = {
            "base": model_receipt(Path(args.embedding_model)),
            "adapter": model_receipt(adapter),
        }
        score_protocol = "raw_text_last_token_l2_cosine"
    elif arm in {"reranker_retrieval", "reranker_strict"}:
        instruction = (
            RETRIEVAL_INSTRUCTION
            if arm == "reranker_retrieval"
            else STRICT_EQUIVALENCE_INSTRUCTION
        )
        scores, runtime = score_reranker(
            cases, Path(args.reranker_model), instruction, args.reranker_batch_size
        )
        model = model_receipt(Path(args.reranker_model))
        score_protocol = "qwen_yes_logit_minus_no_logit"
    else:
        raise ValueError(f"unknown arm: {arm}")
    rows = evaluate_scores(cases, scores)
    payload = {
        "schema": "dualign-observer-bakeoff-arm/v1",
        "arm": arm,
        "body_text_in_output": False,
        "created_at_unix": time.time(),
        "sources": sources,
        "model": model,
        "instruction": instruction,
        "score_protocol": score_protocol,
        "runtime": runtime,
        "software": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "summary": summarize_evaluation(rows),
        "cases": rows,
    }
    output = Path(args.output)
    write_json(output, payload)
    print(
        json.dumps(
            {
                "arm": arm,
                "output": str(output.resolve()),
                "output_sha256": sha256_file(output),
                "overall": payload["summary"]["overall"],
                "runtime": runtime,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def paired_flips(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    base_rows = {(row["dataset"], row["case_id"]): row for row in base["cases"]}
    other_rows = {(row["dataset"], row["case_id"]): row for row in other["cases"]}
    if base_rows.keys() != other_rows.keys():
        raise ValueError("arm case sets differ")
    result: dict[str, Any] = {}
    for dataset in sorted({key[0] for key in base_rows}):
        counts = Counter()
        gains: list[str] = []
        losses: list[str] = []
        for key in sorted(item for item in base_rows if item[0] == dataset):
            before = bool(base_rows[key]["positive_top1"])
            after = bool(other_rows[key]["positive_top1"])
            if not before and after:
                counts["wrong_to_correct"] += 1
                gains.append(key[1])
            elif before and not after:
                counts["correct_to_wrong"] += 1
                losses.append(key[1])
            elif before:
                counts["stable_correct"] += 1
            else:
                counts["stable_wrong"] += 1
        result[dataset] = {
            **dict(counts),
            "wrong_to_correct_ids": gains,
            "correct_to_wrong_ids": losses,
        }
    return result


def architecture_gate(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = arms["embedding_base"]
    candidates = ["reranker_retrieval", "reranker_strict"]
    assessments: dict[str, Any] = {}
    for arm_name in candidates:
        arm = arms[arm_name]
        flips = paired_flips(base, arm)
        dataset_checks: dict[str, Any] = {}
        for dataset in (
            "internal_v1_k3",
            "internal_reader_natural",
            "validation_v4_development",
        ):
            base_metric = base["summary"]["by_dataset"][dataset]
            arm_metric = arm["summary"]["by_dataset"][dataset]
            family_checks: dict[str, bool] = {}
            critical = (
                ("coverage_completeness", "semantic_near_miss_wrong_alignment")
                if dataset == "internal_v1_k3"
                else (
                    ("omission", "boundary")
                    if dataset == "internal_reader_natural"
                    else (
                        "adjacent_addition",
                        "low_salience_addition",
                        "boundary_shift",
                        "middle_omission",
                        "omission_head",
                        "omission_tail",
                    )
                )
            )
            for family in critical:
                before = base_metric["by_family"].get(family)
                after = arm_metric["by_family"].get(family)
                family_checks[family] = bool(
                    before
                    and after
                    and after["top1_rate"] >= before["top1_rate"]
                    and after["margin_p10"] > 0.0
                )
            flip = flips[dataset]
            gains = int(flip.get("wrong_to_correct", 0))
            losses = int(flip.get("correct_to_wrong", 0))
            dataset_checks[dataset] = {
                "top1_improved": arm_metric["top1_rate"] > base_metric["top1_rate"],
                "p10_positive": arm_metric["margin_p10"] > 0.0,
                "critical_families_nonregressed_with_positive_p10": family_checks,
                "paired_gains_exceed_losses": gains > losses,
                "correct_to_wrong_at_most_half_gains": (
                    losses * 2 <= gains if gains else False
                ),
            }
            dataset_checks[dataset]["passed"] = all(
                [
                    dataset_checks[dataset]["top1_improved"],
                    dataset_checks[dataset]["p10_positive"],
                    all(family_checks.values()),
                    dataset_checks[dataset]["paired_gains_exceed_losses"],
                    dataset_checks[dataset]["correct_to_wrong_at_most_half_gains"],
                ]
            )
        runtime = arm["runtime"]
        cost_passed = (
            runtime["milliseconds_per_pair_amortized"] <= 100.0
            and runtime["peak_cuda_allocated_gib"] <= 4.0
        )
        passed = (
            all(value["passed"] for value in dataset_checks.values()) and cost_passed
        )
        assessments[arm_name] = {
            "datasets": dataset_checks,
            "cost": {
                "milliseconds_per_pair_amortized_lte_100": runtime[
                    "milliseconds_per_pair_amortized"
                ]
                <= 100.0,
                "peak_cuda_allocated_gib_lte_4": runtime["peak_cuda_allocated_gib"]
                <= 4.0,
                "passed": cost_passed,
            },
            "passed": passed,
        }
    winner = next((name for name in candidates if assessments[name]["passed"]), None)
    return {
        "status": (
            "architecture_turn_supported"
            if winner
            else "architecture_turn_not_supported"
        ),
        "selected_pairwise_arm": winner,
        "assessments": assessments,
        "scope": "engineering_probe_not_deployment_conclusion",
        "native_margin_scale_warning": (
            "Cosine and reranker logit margins are not numerically commensurate; "
            "the gate uses Top-1, paired flips, per-arm p10 sign, and family non-regression."
        ),
    }


def command_summarize(args: argparse.Namespace) -> None:
    arms: dict[str, dict[str, Any]] = {}
    arm_files: dict[str, Any] = {}
    for path_value in args.arm_results:
        path = Path(path_value).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        arm = str(payload["arm"])
        arms[arm] = payload
        arm_files[arm] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    required = {
        "embedding_base",
        "embedding_l1",
        "embedding_l2",
        "reranker_retrieval",
        "reranker_strict",
    }
    if set(arms) != required:
        raise ValueError(
            f"arm set differs: expected={sorted(required)}, actual={sorted(arms)}"
        )
    base = arms["embedding_base"]
    receipt = {
        "schema": "dualign-observer-bakeoff-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "scientific_scope": "independent_engineering_probe_not_sealed_not_deployment",
        "training_performed": False,
        "shadow_or_confirmation_opened": False,
        "source_receipt": base["sources"],
        "arm_files_local_only": arm_files,
        "arms": {
            name: {
                "model": payload["model"],
                "instruction": payload["instruction"],
                "score_protocol": payload["score_protocol"],
                "runtime": payload["runtime"],
                "software": payload["software"],
                "summary": payload["summary"],
                "paired_flips_vs_embedding_base": (
                    None if name == "embedding_base" else paired_flips(base, payload)
                ),
            }
            for name, payload in sorted(arms.items())
        },
        "preregistered_gate": architecture_gate(arms),
    }
    output = Path(args.output)
    write_json(output, receipt)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "sha256": sha256_file(output),
                "gate": receipt["preregistered_gate"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def add_sources(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--private-groups", required=True)
    parser.add_argument("--private-split", required=True)
    parser.add_argument("--natural-cases", required=True)
    parser.add_argument("--validation-development", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    add_sources(validate)
    validate.add_argument("--output")
    validate.set_defaults(function=command_validate)

    score = subparsers.add_parser("score")
    add_sources(score)
    score.add_argument(
        "--arm",
        required=True,
        choices=(
            "embedding_base",
            "embedding_l1",
            "embedding_l2",
            "reranker_retrieval",
            "reranker_strict",
        ),
    )
    score.add_argument("--embedding-model", required=True)
    score.add_argument("--l1-adapter", required=True)
    score.add_argument("--l2-adapter", required=True)
    score.add_argument("--reranker-model", required=True)
    score.add_argument("--embedding-batch-size", type=int, default=32)
    score.add_argument("--reranker-batch-size", type=int, default=16)
    score.add_argument("--output", required=True)
    score.set_defaults(function=command_score)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--arm-results", nargs="+", required=True)
    summarize.add_argument("--output", required=True)
    summarize.set_defaults(function=command_summarize)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
