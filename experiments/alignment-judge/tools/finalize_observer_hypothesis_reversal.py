from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

DATASETS = ("internal_v1_k3", "internal_reader_natural", "validation_v4_development")
SAFE_MODEL_DETAIL_KEYS = (
    "context_length",
    "embedding_length",
    "families",
    "family",
    "format",
    "parameter_size",
    "quantization_level",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_receipt(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def mcnemar_exact(candidate_only: int, baseline_only: int) -> float:
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return 1.0
    lower = min(candidate_only, baseline_only)
    tail = sum(math.comb(discordant, index) for index in range(lower + 1)) / (
        2**discordant
    )
    return min(1.0, 2 * tail)


def paired(
    candidate: dict[tuple[str, str], bool], baseline: dict[tuple[str, str], bool]
) -> dict[str, Any]:
    if candidate.keys() != baseline.keys():
        missing_candidate = sorted(baseline.keys() - candidate.keys())
        missing_baseline = sorted(candidate.keys() - baseline.keys())
        raise ValueError(
            f"case sets differ: missing_candidate={missing_candidate[:3]!r}, "
            f"missing_baseline={missing_baseline[:3]!r}"
        )
    both_correct = sum(candidate[key] and baseline[key] for key in candidate)
    candidate_only = sum(candidate[key] and not baseline[key] for key in candidate)
    baseline_only = sum(baseline[key] and not candidate[key] for key in candidate)
    both_wrong = len(candidate) - both_correct - candidate_only - baseline_only
    return {
        "cases": len(candidate),
        "both_correct": both_correct,
        "baseline_only_correct": baseline_only,
        "candidate_only_correct": candidate_only,
        "both_wrong": both_wrong,
        "net_candidate_minus_baseline_correct": candidate_only - baseline_only,
        "accuracy_difference_percentage_points": 100
        * (candidate_only - baseline_only)
        / len(candidate),
        "mcnemar_exact_two_sided_p": mcnemar_exact(candidate_only, baseline_only),
    }


def compact_model(model: dict[str, Any]) -> dict[str, Any]:
    details = model.get("details") or {}
    return {
        "name": model.get("name"),
        "digest": model.get("digest"),
        "size": model.get("size"),
        "details": {
            key: details[key] for key in SAFE_MODEL_DETAIL_KEYS if key in details
        },
    }


def summarize_rows(rows: dict[tuple[str, str], bool]) -> dict[str, Any]:
    correct = sum(rows.values())
    by_dataset = {}
    for dataset in DATASETS:
        values = [
            value for (row_dataset, _), value in rows.items() if row_dataset == dataset
        ]
        by_dataset[dataset] = {
            "cases": len(values),
            "correct": sum(values),
            "accuracy": sum(values) / len(values),
        }
    return {
        "cases": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows),
        "by_dataset": by_dataset,
    }


def load_embedding(path: Path) -> tuple[dict[tuple[str, str], bool], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = {
        (row["dataset"], row["case_id"]): bool(row["positive_top1"])
        for row in payload["cases"]
    }
    metadata = {
        "protocol": payload["score_protocol"],
        "instruction_sha256": payload["instruction_sha256"],
        "instruction_applied_to": payload["instruction_applied_to"],
        "model": compact_model(payload["model"]),
        **summarize_rows(rows),
    }
    return rows, metadata


def load_llm(path: Path) -> tuple[dict[tuple[str, str], bool], dict[str, Any]]:
    answer_rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows = {
        (row["dataset"], row["case_id"]): bool(row["correct"]) for row in answer_rows
    }
    first = answer_rows[0]
    metadata = {
        "protocol": "forced_single_choice_valid_letter_only",
        "model": first["model"],
        "prompt_variant": first["prompt_variant"],
        "system_prompt_sha256": first["system_prompt_sha256"],
        **summarize_rows(rows),
    }
    return rows, metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-answers", type=Path, required=True)
    parser.add_argument("--raw-qwen", type=Path, required=True)
    parser.add_argument("--app-qwen", type=Path, required=True)
    parser.add_argument("--app-harrier", type=Path, required=True)
    parser.add_argument("--app-qwen4b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows: dict[str, dict[tuple[str, str], bool]] = {}
    arms: dict[str, dict[str, Any]] = {}
    sources = {}
    for name, path in (
        ("raw_qwen3_embedding_0_6b", args.raw_qwen),
        ("app_qwen3_embedding_0_6b", args.app_qwen),
        ("app_harrier_0_6b", args.app_harrier),
        ("app_qwen3_embedding_4b", args.app_qwen4b),
    ):
        rows[name], arms[name] = load_embedding(path)
        sources[name] = source_receipt(path)
    rows["generative_qwen3_5_4b"], arms["generative_qwen3_5_4b"] = load_llm(
        args.llm_answers
    )
    sources["generative_qwen3_5_4b"] = source_receipt(args.llm_answers)

    reference_keys = rows["generative_qwen3_5_4b"].keys()
    if any(value.keys() != reference_keys for value in rows.values()):
        raise ValueError("not all arms cover the identical case set")

    comparisons = {}
    for name, candidate, baseline in (
        ("llm_vs_raw_qwen0_6b", "generative_qwen3_5_4b", "raw_qwen3_embedding_0_6b"),
        (
            "app_qwen0_6b_vs_raw_qwen0_6b",
            "app_qwen3_embedding_0_6b",
            "raw_qwen3_embedding_0_6b",
        ),
        ("app_qwen0_6b_vs_llm", "app_qwen3_embedding_0_6b", "generative_qwen3_5_4b"),
        ("app_harrier0_6b_vs_llm", "app_harrier_0_6b", "generative_qwen3_5_4b"),
        ("app_qwen4b_vs_llm", "app_qwen3_embedding_4b", "generative_qwen3_5_4b"),
        (
            "app_harrier0_6b_vs_app_qwen0_6b",
            "app_harrier_0_6b",
            "app_qwen3_embedding_0_6b",
        ),
        ("app_qwen4b_vs_app_harrier0_6b", "app_qwen3_embedding_4b", "app_harrier_0_6b"),
    ):
        comparisons[name] = {
            "candidate": candidate,
            "baseline": baseline,
            **paired(rows[candidate], rows[baseline]),
        }

    payload = {
        "schema": "dualign-observer-hypothesis-reversal/v1",
        "body_text_in_output": False,
        "hypothesis_rejected": (
            "generative forced-choice LLM is more accurate than cosine embedding under the Dualign application protocol"
        ),
        "decision_scope": "rejected_on_opened_engineering_suite_not_a_universal_model_claim",
        "case_universe": {"cases": len(reference_keys), "datasets": list(DATASETS)},
        "arms": arms,
        "paired_comparisons": comparisons,
        "sources": sources,
        "interpretation_guards": [
            "All accuracy comparisons use identical case IDs and labels.",
            "Raw versus application-instruction Qwen3 0.6B changes only the embedding input instruction.",
            "The suite is opened and development-heavy, so this rejects the prior engineering claim, not a universal claim.",
            "Latency across generative and embedding architectures is not directly comparable.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"output": str(args.output), "comparisons": comparisons},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
