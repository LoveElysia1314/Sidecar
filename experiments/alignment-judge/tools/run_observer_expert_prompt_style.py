"""Evaluate expert-proposed prompt styles against the leading 4B prompt."""

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
PROMPTS = {
    "p5_semantic_set_equality": (
        "Treat the reference and each candidate as sets of alignment-relevant "
        "information. Choose the candidate whose information set is the same as "
        "the reference: it must be neither a subset nor a superset. Faithful "
        "translation or paraphrase may change the wording. Reply with only the "
        "best option letter."
    ),
    "p6_mutual_substitutability": (
        "Choose the candidate that could replace the reference without changing "
        "any alignment-relevant meaning or boundary. If the replacement would "
        "lose information or introduce information, that candidate is wrong. "
        "Faithful translation or paraphrase is allowed. Reply with only the best "
        "option letter."
    ),
    "p7_compact_balanced_entailment": (
        "Choose the candidate that is mutually entailing with the reference. "
        "Reference-to-candidate and candidate-to-reference are equally required; "
        "failure in either direction makes the candidate wrong. Faithful "
        "translation or paraphrase is allowed. Reply with only the best option "
        "letter."
    ),
}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def challenger_gate(
    baseline: dict[str, Any], candidate: dict[str, Any], paired: dict[str, Any]
) -> dict[str, Any]:
    dataset_checks = {
        key: candidate["by_dataset"][key]["accuracy"]
        >= baseline["by_dataset"][key]["accuracy"]
        for key in sorted(candidate["by_dataset"])
    }
    protected_markers = (
        "addition",
        "attribute_counterfactual",
        "coverage_completeness",
    )
    protected_family_checks = {
        key: candidate["by_family"][key]["accuracy"]
        >= baseline["by_family"][key]["accuracy"]
        for key in sorted(candidate["by_family"])
        if any(marker in key for marker in protected_markers)
    }
    checks = {
        "overall_accuracy_strictly_improved": (
            candidate["overall"]["accuracy"] > baseline["overall"]["accuracy"]
        ),
        "paired_net_positive": paired["net_second_minus_first_correct"] > 0,
        "all_datasets_nonregressed": all(dataset_checks.values()),
        "protected_families_nonregressed": all(protected_family_checks.values()),
        "zero_parse_failures": candidate["overall"]["parse_failures"] == 0,
    }
    return {
        "checks": checks,
        "dataset_nonregression": dataset_checks,
        "protected_family_nonregression": protected_family_checks,
        "passed": all(checks.values()),
        "scope": "eligibility_to_challenge_current_leader_on_opened_suite",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--prompt-runtime-script", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--leader-answers", required=True)
    parser.add_argument("--variant", required=True, choices=sorted(PROMPTS))
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep-alive", default="10m")
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    mcq = load_module(Path(args.mcq_script).resolve(), "observer_mcq_for_expert_style")
    runtime = load_module(
        Path(args.prompt_runtime_script).resolve(), "observer_runtime_for_expert_style"
    )
    if runtime.MODEL != MODEL or runtime.OPTIONS.get("num_ctx") != 8192:
        raise ValueError("runtime model or context differs from the frozen comparison")
    system_prompt = PROMPTS[args.variant]
    questions_path = Path(args.questions).resolve()
    questions = mcq.read_jsonl(questions_path)
    if len(questions) != 1736:
        raise ValueError(f"expected 1736 questions, got {len(questions)}")
    keys = {(row["dataset"], row["case_id"]) for row in questions}
    leader_path = Path(args.leader_answers).resolve()
    leader = [
        row
        for row in mcq.read_jsonl(leader_path)
        if (row["dataset"], row["case_id"]) in keys
    ]
    if len(leader) != 1736:
        raise ValueError("leader answer set does not cover all questions")

    warmup, warmup_wall = runtime.request_chat(
        args.endpoint, system_prompt, mcq.warmup_prompt(), args.timeout, args.keep_alive
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
                system_prompt,
                question["user_prompt"],
                args.timeout,
                args.keep_alive,
            )
            response_text = str(response.get("message", {}).get("content", ""))
            predicted = mcq.parse_response(response_text, question["valid_letters"])
            row = {
                "schema": "dualign-observer-expert-prompt-answer/v1",
                "model": MODEL,
                "prompt_variant": args.variant,
                "system_prompt_sha256": hashlib.sha256(
                    system_prompt.encode()
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
                        {"variant": args.variant, "completed": index, "target": 1736}
                    ),
                    flush=True,
                )

    summary = mcq.summarize_rows(rows)
    leader_summary = mcq.summarize_rows(leader)
    paired = mcq.paired_comparison(leader, rows)
    receipt = {
        "schema": "dualign-observer-expert-prompt-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "scientific_scope": "opened_prompt_development_suite_not_confirmation",
        "training_performed": False,
        "shadow_or_confirmation_opened": False,
        "model": MODEL,
        "prompt_variant": args.variant,
        "system_prompt": system_prompt,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
        "generation": {
            **runtime.OPTIONS,
            "think": False,
            "keep_alive": args.keep_alive,
        },
        "questions": {
            "path": str(questions_path),
            "bytes": questions_path.stat().st_size,
            "sha256": mcq.sha256_file(questions_path),
        },
        "leader_answers": {
            "path": str(leader_path),
            "bytes": leader_path.stat().st_size,
            "sha256": mcq.sha256_file(leader_path),
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
        "leader_summary": leader_summary,
        "paired_vs_leader": paired,
        "challenger_gate": challenger_gate(leader_summary, summary, paired["overall"]),
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
                "paired": paired["overall"],
                "gate": receipt["challenger_gate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
