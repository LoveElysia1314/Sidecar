"""Run controlled system-prompt ablations on the private wrong-union corpus."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODEL = "qwen3.5:4b"
OPTIONS = {
    "temperature": 0,
    "seed": 20260901,
    "num_predict": 8,
    "num_ctx": 8192,
}
PROMPTS = {
    "two_way_coverage": (
        "Judge exact cross-lingual alignment. Work silently. For each candidate, "
        "apply a two-way coverage check: every proposition in the reference must "
        "be preserved by the candidate, and every proposition in the candidate "
        "must be supported by the reference. Preserve actors, actions, objects, "
        "attributes, negation, quantities, time, causal or event order, and text "
        "boundaries. Translation and paraphrase may change wording. Choose the "
        "only zero-mismatch candidate. Reply with only its option letter."
    ),
    "near_miss_elimination": (
        "Choose the one candidate that is exactly equivalent to the reference. "
        "The wrong options are often fluent, relevant, and almost correct but "
        "contain one subtle omission, addition, changed attribute, contradiction, "
        "order change, or boundary shift. Silently find the smallest semantic "
        "mismatch in each option and eliminate every option with any mismatch. "
        "Allow faithful paraphrase across languages. Reply with only the letter."
    ),
    "bidirectional_entailment": (
        "Treat this as lossless translation verification, not relevance ranking. "
        "The correct candidate must satisfy both directions: the reference entails "
        "the candidate and the candidate entails the reference, at the level of "
        "alignment-relevant facts and boundaries. Reject an option if it drops a "
        "reference fact or introduces an unsupported fact, even if the difference "
        "is small. Check negation, entities, attributes, numbers, time, and event "
        "order. Reply with only the best option letter."
    ),
}


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("observer_mcq_for_prompt", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MCQ module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request_chat(
    endpoint: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
    keep_alive: str,
) -> tuple[dict[str, Any], float]:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": OPTIONS,
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:500]}") from exc
    return result, time.perf_counter() - started


def seconds(payload: dict[str, Any], key: str) -> float:
    return float(payload.get(key, 0)) / 1_000_000_000.0


def subset_baseline(
    module: Any,
    baseline_path: Path,
    keys: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    rows = module.read_jsonl(baseline_path)
    selected = [row for row in rows if (row["dataset"], row["case_id"]) in keys]
    if len(selected) != len(keys):
        raise ValueError("baseline does not cover selected corpus keys")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--baseline-answers", required=True)
    parser.add_argument("--variant", choices=sorted(PROMPTS), required=True)
    parser.add_argument(
        "--split", choices=("prompt_tuning", "prompt_check"), required=True
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--keep-alive", default="10m")
    parser.add_argument("--progress-every", type=int, default=50)
    args = parser.parse_args()

    module = load_module(Path(args.mcq_script).resolve())
    corpus_path = Path(args.corpus).resolve()
    selected = [
        row
        for row in module.read_jsonl(corpus_path)
        if row["prompt_split"] == args.split
    ]
    keys = {(row["dataset"], row["case_id"]) for row in selected}
    baseline_path = Path(args.baseline_answers).resolve()
    baseline = subset_baseline(module, baseline_path, keys)
    system_prompt = PROMPTS[args.variant]

    warmup, warmup_wall = request_chat(
        args.endpoint,
        system_prompt,
        module.warmup_prompt(),
        args.timeout,
        args.keep_alive,
    )
    warmup_text = str(warmup.get("message", {}).get("content", ""))
    if module.parse_response(warmup_text, ["A", "B"]) != "A":
        raise RuntimeError("warmup did not return the expected letter")

    rows = []
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, question in enumerate(selected, 1):
            response, wall = request_chat(
                args.endpoint,
                system_prompt,
                question["user_prompt"],
                args.timeout,
                args.keep_alive,
            )
            response_text = str(response.get("message", {}).get("content", ""))
            predicted = module.parse_response(response_text, question["valid_letters"])
            row = {
                "schema": "dualign-observer-prompt-answer/v1",
                "model": MODEL,
                "prompt_variant": args.variant,
                "prompt_split": args.split,
                "system_prompt_sha256": hashlib.sha256(
                    system_prompt.encode("utf-8")
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
                "response_sha256": hashlib.sha256(
                    response_text.encode("utf-8")
                ).hexdigest(),
                "response_chars": len(response_text),
                "wall_seconds": wall,
                "api_total_seconds": seconds(response, "total_duration"),
                "load_seconds": seconds(response, "load_duration"),
                "prompt_eval_seconds": seconds(response, "prompt_eval_duration"),
                "eval_seconds": seconds(response, "eval_duration"),
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
                            "variant": args.variant,
                            "split": args.split,
                            "completed": index,
                            "target": len(selected),
                        }
                    ),
                    flush=True,
                )

    receipt = {
        "schema": "dualign-observer-prompt-ablation-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "model": MODEL,
        "prompt_variant": args.variant,
        "prompt_split": args.split,
        "system_prompt": system_prompt,
        "system_prompt_sha256": hashlib.sha256(
            system_prompt.encode("utf-8")
        ).hexdigest(),
        "corpus": {
            "path": str(corpus_path),
            "bytes": corpus_path.stat().st_size,
            "sha256": module.sha256_file(corpus_path),
        },
        "baseline_answers": {
            "path": str(baseline_path),
            "bytes": baseline_path.stat().st_size,
            "sha256": module.sha256_file(baseline_path),
        },
        "answer_file": {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": module.sha256_file(output_path),
        },
        "generation": {**OPTIONS, "think": False, "keep_alive": args.keep_alive},
        "warmup": {
            "wall_seconds": warmup_wall,
            "load_seconds": seconds(warmup, "load_duration"),
            "response_chars": len(warmup_text),
        },
        "summary": module.summarize_rows(rows),
        "baseline_summary": module.summarize_rows(baseline),
        "paired_vs_baseline": module.paired_comparison(baseline, rows),
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    module.write_json(Path(args.receipt).resolve(), receipt)
    print(
        json.dumps(
            {
                "receipt": str(Path(args.receipt).resolve()),
                "accuracy": receipt["summary"]["overall"]["accuracy"],
                "paired": receipt["paired_vs_baseline"]["overall"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
