"""Evaluate one architecture-adapted, forced-single-choice prompt with local 4B."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

MODEL = "qwen3.5:4b"
PROMPT_VARIANT = "architecture_forced_single_choice/v1"
SYSTEM_PROMPT = (
    "You are a bilingual or multilingual alignment judge. Choose the one "
    "candidate that best preserves all alignment-relevant information from the "
    "reference and adds no unsupported information. Natural translation and "
    "faithful paraphrase differences are allowed. Any omission, addition, "
    "contradiction, or incorrect text boundary makes a candidate worse. Do not "
    "rewrite or explain the text. Return only the best option letter."
)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def family_delta(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    keys = sorted(set(baseline) | set(candidate))
    output = {}
    for key in keys:
        before = baseline.get(key)
        after = candidate.get(key)
        if before is None or after is None:
            raise ValueError(f"family set mismatch at {key}")
        output[key] = {
            "questions": after["questions"],
            "baseline_accuracy": before["accuracy"],
            "candidate_accuracy": after["accuracy"],
            "delta": after["accuracy"] - before["accuracy"],
            "nonregressed": after["accuracy"] >= before["accuracy"],
        }
    return output


def replacement_gate(
    baseline_summary: dict[str, Any], candidate_summary: dict[str, Any]
) -> dict[str, Any]:
    by_dataset = {
        key: candidate_summary["by_dataset"][key]["accuracy"]
        >= baseline_summary["by_dataset"][key]["accuracy"]
        for key in sorted(candidate_summary["by_dataset"])
    }
    deltas = family_delta(baseline_summary["by_family"], candidate_summary["by_family"])
    critical = {
        key: value["nonregressed"]
        for key, value in deltas.items()
        if any(
            marker in key
            for marker in (
                "addition",
                "omission",
                "boundary",
                "order_perturbation",
                "merge_split",
                "coverage_completeness",
            )
        )
    }
    checks = {
        "overall_accuracy_improved": (
            candidate_summary["overall"]["accuracy"]
            > baseline_summary["overall"]["accuracy"]
        ),
        "all_datasets_nonregressed": all(by_dataset.values()),
        "all_critical_families_nonregressed": all(critical.values()),
        "zero_parse_failures": candidate_summary["overall"]["parse_failures"] == 0,
    }
    return {
        "checks": checks,
        "by_dataset_nonregression": by_dataset,
        "critical_family_nonregression": critical,
        "family_deltas": deltas,
        "passed": all(checks.values()),
        "meaning": "general_prompt_replacement_supported_on_opened_engineering_suite",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--prompt-ablation-script", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--baseline-answers", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep-alive", default="10m")
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    mcq = load_module(Path(args.mcq_script).resolve(), "observer_mcq_for_arch_prompt")
    runtime = load_module(
        Path(args.prompt_ablation_script).resolve(), "observer_prompt_runtime_for_arch"
    )
    if runtime.MODEL != MODEL or runtime.OPTIONS.get("num_ctx") != 8192:
        raise ValueError("runtime model or context differs from the frozen comparison")
    if "AMBIGUOUS" in SYSTEM_PROMPT.upper() or "`NONE`" in SYSTEM_PROMPT.upper():
        raise ValueError("forbidden abstention output remains in the prompt")

    question_path = Path(args.questions).resolve()
    questions = mcq.read_jsonl(question_path)
    if len(questions) != 1736:
        raise ValueError(f"expected 1736 opened questions, got {len(questions)}")
    keys = {(row["dataset"], row["case_id"]) for row in questions}
    if len(keys) != len(questions):
        raise ValueError("duplicate question key")
    baseline_path = Path(args.baseline_answers).resolve()
    baseline = [
        row
        for row in mcq.read_jsonl(baseline_path)
        if (row["dataset"], row["case_id"]) in keys
    ]
    if len(baseline) != len(questions):
        raise ValueError("baseline does not cover the opened question set")

    warmup, warmup_wall = runtime.request_chat(
        args.endpoint,
        SYSTEM_PROMPT,
        mcq.warmup_prompt(),
        args.timeout,
        args.keep_alive,
    )
    warmup_text = str(warmup.get("message", {}).get("content", ""))
    if mcq.parse_response(warmup_text, ["A", "B"]) != "A":
        raise RuntimeError("warmup did not return A")

    rows = []
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, question in enumerate(questions, 1):
            response, wall = runtime.request_chat(
                args.endpoint,
                SYSTEM_PROMPT,
                question["user_prompt"],
                args.timeout,
                args.keep_alive,
            )
            response_text = str(response.get("message", {}).get("content", ""))
            predicted = mcq.parse_response(response_text, question["valid_letters"])
            row = {
                "schema": "dualign-observer-architecture-prompt-answer/v1",
                "model": MODEL,
                "prompt_variant": PROMPT_VARIANT,
                "system_prompt_sha256": hashlib.sha256(
                    SYSTEM_PROMPT.encode()
                ).hexdigest(),
                "dataset": question["dataset"],
                "case_id": question["case_id"],
                "direction": question["direction"],
                "role": question["role"],
                "family": question["family"],
                "candidate_count": len(question["options"]),
                "user_prompt_sha256": question["user_prompt_sha256"],
                "answer_letter": question["answer_letter"],
                "predicted_letter": predicted,
                "correct": predicted == question["answer_letter"],
                "response_sha256": hashlib.sha256(response_text.encode()).hexdigest(),
                "response_chars": len(response_text),
                "wall_seconds": wall,
                "api_total_seconds": float(response.get("total_duration", 0)) / 1e9,
                "load_seconds": float(response.get("load_duration", 0)) / 1e9,
                "prompt_eval_seconds": float(response.get("prompt_eval_duration", 0))
                / 1e9,
                "eval_seconds": float(response.get("eval_duration", 0)) / 1e9,
                "prompt_eval_count": int(response.get("prompt_eval_count", 0)),
                "eval_count": int(response.get("eval_count", 0)),
                "done_reason": response.get("done_reason"),
            }
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            if index % args.progress_every == 0:
                print(
                    json.dumps(
                        {
                            "variant": PROMPT_VARIANT,
                            "completed": index,
                            "target": len(questions),
                        }
                    ),
                    flush=True,
                )

    summary = mcq.summarize_rows(rows)
    baseline_summary = mcq.summarize_rows(baseline)
    receipt = {
        "schema": "dualign-observer-architecture-prompt-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "scientific_scope": "opened_engineering_suite_not_sealed_confirmation",
        "training_performed": False,
        "shadow_or_confirmation_opened": False,
        "model": MODEL,
        "prompt_variant": PROMPT_VARIANT,
        "system_prompt": SYSTEM_PROMPT,
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "architecture_adaptations": [
            "bilingual_or_multilingual_matches_zh_en_ja_scope",
            "exactly_one_candidate_matches_dataset_contract",
            "option_letter_matches_A_B_C_D_parser_contract",
            "AMBIGUOUS_and_NONE_removed",
            "rewrite_and_explanation_forbidden",
        ],
        "generation": {
            **runtime.OPTIONS,
            "think": False,
            "keep_alive": args.keep_alive,
        },
        "questions": {
            "path": str(question_path),
            "bytes": question_path.stat().st_size,
            "sha256": mcq.sha256_file(question_path),
        },
        "baseline_answers": {
            "path": str(baseline_path),
            "bytes": baseline_path.stat().st_size,
            "sha256": mcq.sha256_file(baseline_path),
        },
        "answer_file": {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": mcq.sha256_file(output_path),
        },
        "warmup": {
            "wall_seconds": warmup_wall,
            "load_seconds": float(warmup.get("load_duration", 0)) / 1e9,
            "response_chars": len(warmup_text),
        },
        "summary": summary,
        "baseline_summary": baseline_summary,
        "paired_vs_baseline": mcq.paired_comparison(baseline, rows),
        "replacement_gate": replacement_gate(baseline_summary, summary),
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    mcq.write_json(Path(args.receipt).resolve(), receipt)
    print(
        json.dumps(
            {
                "receipt": str(Path(args.receipt).resolve()),
                "summary": summary["overall"],
                "paired": receipt["paired_vs_baseline"]["overall"],
                "gate": receipt["replacement_gate"]["passed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
