"""Score one prompt on a second option permutation and audit semantic consistency."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

PROMPT_KINDS = ("architecture_leader", "p7_challenger")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def selected_candidate_id(
    question: dict[str, Any], predicted: str | None
) -> str | None:
    if predicted is None:
        return None
    matches = [
        option["candidate_id"]
        for option in question["options"]
        if option["letter"] == predicted
    ]
    if len(matches) != 1:
        raise ValueError("predicted letter does not map to exactly one candidate")
    return str(matches[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--runtime-script", required=True)
    parser.add_argument("--architecture-script", required=True)
    parser.add_argument("--expert-script", required=True)
    parser.add_argument("--permuted-questions", required=True)
    parser.add_argument("--original-questions", required=True)
    parser.add_argument("--original-answers", required=True)
    parser.add_argument("--prompt-kind", choices=PROMPT_KINDS, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep-alive", default="10m")
    parser.add_argument("--progress-every", type=int, default=50)
    args = parser.parse_args()
    mcq = load_module(Path(args.mcq_script).resolve(), "observer_mcq_for_perm_score")
    runtime = load_module(
        Path(args.runtime_script).resolve(), "observer_runtime_for_perm_score"
    )
    architecture = load_module(
        Path(args.architecture_script).resolve(), "observer_arch_for_perm_score"
    )
    expert = load_module(
        Path(args.expert_script).resolve(), "observer_expert_for_perm_score"
    )
    prompt = (
        architecture.SYSTEM_PROMPT
        if args.prompt_kind == "architecture_leader"
        else expert.PROMPTS["p7_compact_balanced_entailment"]
    )
    permuted_path = Path(args.permuted_questions).resolve()
    permuted = mcq.read_jsonl(permuted_path)
    if len(permuted) != 300:
        raise ValueError("permutation audit must contain 300 questions")
    keys = {(row["dataset"], row["case_id"]) for row in permuted}
    original_questions = {
        (row["dataset"], row["case_id"]): row
        for row in mcq.read_jsonl(Path(args.original_questions).resolve())
        if (row["dataset"], row["case_id"]) in keys
    }
    original_answers = {
        (row["dataset"], row["case_id"]): row
        for row in mcq.read_jsonl(Path(args.original_answers).resolve())
        if (row["dataset"], row["case_id"]) in keys
    }
    if len(original_questions) != 300 or len(original_answers) != 300:
        raise ValueError("original packet or answers do not cover audit keys")

    warmup, warmup_wall = runtime.request_chat(
        args.endpoint, prompt, mcq.warmup_prompt(), args.timeout, args.keep_alive
    )
    warmup_text = str(warmup.get("message", {}).get("content", ""))
    if mcq.parse_response(warmup_text, ["A", "B"]) != "A":
        raise RuntimeError("warmup did not return A")
    rows = []
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, question in enumerate(permuted, 1):
            response, wall = runtime.request_chat(
                args.endpoint,
                prompt,
                question["user_prompt"],
                args.timeout,
                args.keep_alive,
            )
            response_text = str(response.get("message", {}).get("content", ""))
            predicted = mcq.parse_response(response_text, question["valid_letters"])
            key = (question["dataset"], question["case_id"])
            original_answer = original_answers[key]
            original_candidate = selected_candidate_id(
                original_questions[key], original_answer["predicted_letter"]
            )
            permuted_candidate = selected_candidate_id(question, predicted)
            row = {
                "schema": "dualign-observer-permutation-answer/v1",
                "model": "qwen3.5:4b",
                "prompt_kind": args.prompt_kind,
                "dataset": question["dataset"],
                "case_id": question["case_id"],
                "direction": question["direction"],
                "role": question["role"],
                "family": question["family"],
                "candidate_count": len(question["options"]),
                "answer_letter": question["answer_letter"],
                "predicted_letter": predicted,
                "correct": predicted == question["answer_letter"],
                "original_correct": bool(original_answer["correct"]),
                "original_selected_candidate_id": original_candidate,
                "permuted_selected_candidate_id": permuted_candidate,
                "selection_consistent": original_candidate == permuted_candidate,
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
            }
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            if index % args.progress_every == 0:
                print(
                    json.dumps(
                        {
                            "prompt_kind": args.prompt_kind,
                            "completed": index,
                            "target": 300,
                        }
                    ),
                    flush=True,
                )
    summary = mcq.summarize_rows(rows)
    original_correct = sum(row["original_correct"] for row in rows)
    consistent = sum(row["selection_consistent"] for row in rows)
    receipt = {
        "schema": "dualign-observer-permutation-audit-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "prompt_kind": args.prompt_kind,
        "system_prompt": prompt,
        "system_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "questions": {
            "path": str(permuted_path),
            "bytes": permuted_path.stat().st_size,
            "sha256": mcq.sha256_file(permuted_path),
        },
        "answer_file": {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": mcq.sha256_file(output_path),
        },
        "original_subset": {
            "questions": 300,
            "correct": original_correct,
            "accuracy": original_correct / 300,
        },
        "permuted_summary": summary,
        "semantic_selection_consistency": {
            "consistent": consistent,
            "questions": 300,
            "rate": consistent / 300,
        },
        "warmup": {"wall_seconds": warmup_wall, "response_chars": len(warmup_text)},
    }
    mcq.write_json(Path(args.receipt).resolve(), receipt)
    print(
        json.dumps(
            {
                "receipt": str(Path(args.receipt).resolve()),
                "original": receipt["original_subset"],
                "permuted": summary["overall"],
                "consistency": receipt["semantic_selection_consistency"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
