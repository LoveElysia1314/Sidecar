"""Build and score deterministic exact-equivalence MCQs with local Ollama models.

Question packets containing source text are private. Public/local result artifacts
contain only stable IDs, hashes, option letters, timings, and aggregate metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import platform
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

PROMPT_VERSION = "dualign-exact-equivalence-mcq/v1"
SYSTEM_PROMPT = (
    "You are judging bilingual or multilingual text alignment. Choose the one "
    "candidate that conveys exactly the same alignment-relevant information as "
    "the reference. Penalize every omission, addition, contradiction, boundary "
    "shift, or unsupported detail. Reply with only the option letter."
)
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
RESPONSE_PATTERN = re.compile(
    r"^\s*(?:(?:answer|option|choice|答案|选项|选择)\s*[:：]?\s*)?"
    r"[\(\[（【]?\s*([A-Z])\s*[\)\]）】]?[\.!。]?\s*$",
    re.IGNORECASE,
)


def load_bakeoff_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("observer_bakeoff_for_mcq", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load observer bakeoff module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
    return rows


def add_sources(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bakeoff-script", required=True)
    parser.add_argument("--private-groups", required=True)
    parser.add_argument("--private-split", required=True)
    parser.add_argument("--natural-cases", required=True)
    parser.add_argument("--validation-development", required=True)


def load_cases(args: argparse.Namespace) -> tuple[Any, list[Any], dict[str, Any]]:
    module = load_bakeoff_module(Path(args.bakeoff_script).resolve())
    cases, source_receipt = module.load_cases(args)
    return module, cases, source_receipt


def option_order(case: Any) -> list[Any]:
    return sorted(
        case.candidates,
        key=lambda candidate: sha256_text(
            f"{PROMPT_VERSION}|{case.dataset}|{case.case_id}|{candidate.candidate_id}"
        ),
    )


def family_label(case: Any) -> str:
    families = sorted(
        {candidate.family for candidate in case.candidates if not candidate.exact}
    )
    return "+".join(families)


def build_question(case: Any) -> dict[str, Any]:
    candidates = option_order(case)
    if len(candidates) > len(LETTERS):
        raise ValueError(f"too many candidates for {case.dataset}/{case.case_id}")
    options = [
        {
            "letter": LETTERS[index],
            "candidate_id": candidate.candidate_id,
            "family": candidate.family,
            "text": candidate.text,
            "text_sha256": sha256_text(candidate.text),
            "exact": bool(candidate.exact),
        }
        for index, candidate in enumerate(candidates)
    ]
    exact_options = [option for option in options if option["exact"]]
    if len(exact_options) != 1:
        raise ValueError(f"expected one exact option for {case.dataset}/{case.case_id}")
    valid_letters = " / ".join(option["letter"] for option in options)
    prompt_lines = [
        "Reference:",
        case.anchor,
        "",
        "Candidates:",
    ]
    for option in options:
        prompt_lines.extend([f"{option['letter']}.", option["text"], ""])
    prompt_lines.append(f"Return only the best option letter ({valid_letters}).")
    prompt = "\n".join(prompt_lines)
    return {
        "schema": "dualign-private-mcq-question/v1",
        "prompt_version": PROMPT_VERSION,
        "dataset": case.dataset,
        "case_id": case.case_id,
        "direction": case.direction,
        "role": case.role,
        "work_or_cluster_id": case.work_or_cluster_id,
        "family": family_label(case),
        "anchor": case.anchor,
        "anchor_sha256": sha256_text(case.anchor),
        "options": options,
        "valid_letters": [option["letter"] for option in options],
        "answer_letter": exact_options[0]["letter"],
        "user_prompt": prompt,
        "user_prompt_sha256": sha256_text(prompt),
    }


def public_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset": question["dataset"],
        "case_id": question["case_id"],
        "direction": question["direction"],
        "role": question["role"],
        "work_or_cluster_id": question["work_or_cluster_id"],
        "family": question["family"],
        "anchor_sha256": question["anchor_sha256"],
        "options": [
            {
                "letter": option["letter"],
                "candidate_id": option["candidate_id"],
                "family": option["family"],
                "text_sha256": option["text_sha256"],
            }
            for option in question["options"]
        ],
        "valid_letters": question["valid_letters"],
        "answer_letter": question["answer_letter"],
        "user_prompt_sha256": question["user_prompt_sha256"],
    }


def deterministic_question_order(
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        questions,
        key=lambda question: sha256_text(
            f"{PROMPT_VERSION}|question-order|{question['dataset']}|{question['case_id']}"
        ),
    )


def parse_response(text: str, valid_letters: list[str]) -> str | None:
    match = RESPONSE_PATTERN.fullmatch(text)
    if not match:
        return None
    letter = match.group(1).upper()
    return letter if letter in valid_letters else None


def ollama_chat(
    endpoint: str,
    model: str,
    user_prompt: str,
    timeout_seconds: float,
    keep_alive: str,
) -> tuple[dict[str, Any], float]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0,
            "seed": 20260901,
            "num_predict": 8,
            "num_ctx": 8192,
        },
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {body[:500]}") from exc
    wall_seconds = time.perf_counter() - started
    return result, wall_seconds


def duration_seconds(payload: dict[str, Any], key: str) -> float:
    return float(payload.get(key, 0)) / 1_000_000_000.0


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson_interval(
    correct: int, total: int, z: float = 1.959963984540054
) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    p = correct / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = (
        z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    )
    return [center - half, center + half]


def accuracy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(bool(row["correct"]) for row in rows)
    parse_failures = sum(row["predicted_letter"] is None for row in rows)
    wall = [float(row["wall_seconds"]) for row in rows]
    api_total = [float(row["api_total_seconds"]) for row in rows]
    prompt_tokens = sum(int(row["prompt_eval_count"]) for row in rows)
    output_tokens = sum(int(row["eval_count"]) for row in rows)
    output_duration = sum(float(row["eval_seconds"]) for row in rows)
    return {
        "questions": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "accuracy_wilson_95": wilson_interval(correct, total),
        "parse_failures": parse_failures,
        "parse_failure_rate": parse_failures / total if total else 0.0,
        "latency_wall_seconds": {
            "sum": sum(wall),
            "mean": statistics.fmean(wall) if wall else 0.0,
            "p50": quantile(wall, 0.5) if wall else 0.0,
            "p95": quantile(wall, 0.95) if wall else 0.0,
            "p99": quantile(wall, 0.99) if wall else 0.0,
        },
        "api_total_seconds_sum": sum(api_total),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "output_tokens_per_second": (
            output_tokens / output_duration if output_duration else 0.0
        ),
    }


def grouped_summaries(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[field])].append(row)
    return {key: accuracy_summary(value) for key, value in sorted(grouped.items())}


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": accuracy_summary(rows),
        "by_dataset": grouped_summaries(rows, "dataset"),
        "by_direction": grouped_summaries(rows, "direction"),
        "by_family": grouped_summaries(rows, "family"),
        "by_role": grouped_summaries(rows, "role"),
        "by_candidate_count": grouped_summaries(rows, "candidate_count"),
    }


def paired_counts(
    rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]
) -> dict[str, Any]:
    index_a = {(row["dataset"], row["case_id"]): row for row in rows_a}
    index_b = {(row["dataset"], row["case_id"]): row for row in rows_b}
    if set(index_a) != set(index_b):
        raise ValueError("paired model result sets differ")
    counts = Counter(
        {
            "both_correct": 0,
            "first_only_correct": 0,
            "second_only_correct": 0,
            "both_wrong": 0,
            "same_prediction": 0,
        }
    )
    for key in sorted(index_a):
        first = index_a[key]
        second = index_b[key]
        first_correct = bool(first["correct"])
        second_correct = bool(second["correct"])
        if first_correct and second_correct:
            counts["both_correct"] += 1
        elif first_correct:
            counts["first_only_correct"] += 1
        elif second_correct:
            counts["second_only_correct"] += 1
        else:
            counts["both_wrong"] += 1
        if first["predicted_letter"] == second["predicted_letter"]:
            counts["same_prediction"] += 1
    discordant = counts["first_only_correct"] + counts["second_only_correct"]
    smaller = min(counts["first_only_correct"], counts["second_only_correct"])
    exact_p = (
        min(
            1.0,
            2.0
            * sum(math.comb(discordant, value) for value in range(smaller + 1))
            / (2.0**discordant),
        )
        if discordant
        else 1.0
    )
    return {
        "questions": len(index_a),
        **dict(counts),
        "prediction_agreement_rate": counts["same_prediction"] / len(index_a),
        "net_second_minus_first_correct": (
            counts["second_only_correct"] - counts["first_only_correct"]
        ),
        "mcnemar_exact_two_sided_p": exact_p,
    }


def paired_comparison(
    rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]
) -> dict[str, Any]:
    datasets = sorted({str(row["dataset"]) for row in rows_a})
    return {
        "overall": paired_counts(rows_a, rows_b),
        "by_dataset": {
            dataset: paired_counts(
                [row for row in rows_a if row["dataset"] == dataset],
                [row for row in rows_b if row["dataset"] == dataset],
            )
            for dataset in datasets
        },
    }


def command_prepare(args: argparse.Namespace) -> None:
    _, cases, sources = load_cases(args)
    questions = deterministic_question_order([build_question(case) for case in cases])
    private_output = Path(args.private_output).resolve()
    public_output = Path(args.public_output).resolve()
    write_jsonl(private_output, questions)
    public_payload = {
        "schema": "dualign-mcq-manifest/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
        "sources": sources,
        "question_count": len(questions),
        "candidate_count_distribution": dict(
            sorted(Counter(len(question["options"]) for question in questions).items())
        ),
        "private_packet": {
            "path": str(private_output),
            "bytes": private_output.stat().st_size,
            "sha256": sha256_file(private_output),
        },
        "questions": [public_question(question) for question in questions],
    }
    write_json(public_output, public_payload)
    print(
        json.dumps(
            {
                "private": str(private_output),
                "public": str(public_output),
                "questions": len(questions),
            },
            indent=2,
        )
    )


def load_questions(path: Path, limit: int | None) -> list[dict[str, Any]]:
    questions = read_jsonl(path)
    if any(question.get("prompt_version") != PROMPT_VERSION for question in questions):
        raise ValueError("question prompt version mismatch")
    return questions[:limit] if limit is not None else questions


def warmup_prompt() -> str:
    return (
        "Reference:\nThe cat sleeps.\n\nCandidates:\nA.\nThe cat is sleeping.\n\n"
        "B.\nThe dog runs.\n\nReturn only the best option letter (A / B)."
    )


def command_score(args: argparse.Namespace) -> None:
    question_path = Path(args.questions).resolve()
    output_path = Path(args.output).resolve()
    questions = load_questions(question_path, args.limit)
    existing = read_jsonl(output_path) if args.resume else []
    seen = {(row["dataset"], row["case_id"]) for row in existing}
    if any(
        row.get("model") != args.model or row.get("prompt_version") != PROMPT_VERSION
        for row in existing
    ):
        raise ValueError("resume output model or prompt version mismatch")

    warmup, warmup_wall = ollama_chat(
        args.endpoint, args.model, warmup_prompt(), args.timeout, args.keep_alive
    )
    warmup_text = str(warmup.get("message", {}).get("content", ""))
    warmup_letter = parse_response(warmup_text, ["A", "B"])
    warmup_receipt = {
        "model": args.model,
        "response_sha256": sha256_text(warmup_text),
        "response_chars": len(warmup_text),
        "parsed_letter": warmup_letter,
        "correct": warmup_letter == "A",
        "wall_seconds": warmup_wall,
        "api_total_seconds": duration_seconds(warmup, "total_duration"),
        "load_seconds": duration_seconds(warmup, "load_duration"),
    }
    if not warmup_receipt["correct"]:
        raise RuntimeError(f"warmup did not return A: {warmup_receipt}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if existing else "w"
    run_started = time.time()
    newly_scored = 0
    with output_path.open(mode, encoding="utf-8", newline="\n") as handle:
        for index, question in enumerate(questions, 1):
            key = (question["dataset"], question["case_id"])
            if key in seen:
                continue
            response, wall_seconds = ollama_chat(
                args.endpoint,
                args.model,
                question["user_prompt"],
                args.timeout,
                args.keep_alive,
            )
            response_text = str(response.get("message", {}).get("content", ""))
            predicted = parse_response(response_text, question["valid_letters"])
            row = {
                "schema": "dualign-mcq-answer/v1",
                "prompt_version": PROMPT_VERSION,
                "model": args.model,
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
                "response_sha256": sha256_text(response_text),
                "response_chars": len(response_text),
                "wall_seconds": wall_seconds,
                "api_total_seconds": duration_seconds(response, "total_duration"),
                "load_seconds": duration_seconds(response, "load_duration"),
                "prompt_eval_seconds": duration_seconds(
                    response, "prompt_eval_duration"
                ),
                "eval_seconds": duration_seconds(response, "eval_duration"),
                "prompt_eval_count": int(response.get("prompt_eval_count", 0)),
                "eval_count": int(response.get("eval_count", 0)),
                "done_reason": response.get("done_reason"),
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            newly_scored += 1
            if newly_scored % args.progress_every == 0:
                print(
                    json.dumps(
                        {
                            "model": args.model,
                            "completed": len(existing) + newly_scored,
                            "target": len(questions),
                            "elapsed_seconds": time.time() - run_started,
                        }
                    ),
                    flush=True,
                )

    rows = read_jsonl(output_path)
    expected_keys = {
        (question["dataset"], question["case_id"]) for question in questions
    }
    result_keys = {(row["dataset"], row["case_id"]) for row in rows}
    if result_keys != expected_keys:
        raise ValueError(
            f"result question set mismatch: expected={len(expected_keys)}, actual={len(result_keys)}"
        )
    receipt = {
        "schema": "dualign-mcq-model-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "training_performed": False,
        "model": args.model,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
        "question_packet": {
            "path": str(question_path),
            "bytes": question_path.stat().st_size,
            "sha256": sha256_file(question_path),
        },
        "answer_file": {
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        },
        "ollama": {
            "endpoint": args.endpoint,
            "temperature": 0,
            "seed": 20260901,
            "num_predict": 8,
            "num_ctx": 8192,
            "think": False,
            "keep_alive": args.keep_alive,
        },
        "warmup": warmup_receipt,
        "evaluation_wall_seconds": sum(float(row["wall_seconds"]) for row in rows),
        "summary": summarize_rows(rows),
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    receipt_path = Path(args.receipt).resolve()
    write_json(receipt_path, receipt)
    print(
        json.dumps(
            {"receipt": str(receipt_path), "summary": receipt["summary"]["overall"]},
            ensure_ascii=False,
            indent=2,
        )
    )


def command_summarize(args: argparse.Namespace) -> None:
    model_receipts: dict[str, Any] = {}
    answer_rows: dict[str, list[dict[str, Any]]] = {}
    for value in args.model_receipts:
        path = Path(value).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        answer_path = Path(payload["answer_file"]["path"])
        answer_rows[payload["model"]] = read_jsonl(answer_path)
        model_receipts[payload["model"]] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "warmup": payload["warmup"],
            "ollama": payload["ollama"],
            "summary": payload["summary"],
        }
    comparisons = {}
    for first, second in combinations(sorted(answer_rows), 2):
        comparisons[f"{first}__vs__{second}"] = {
            "first_model": first,
            "second_model": second,
            **paired_comparison(answer_rows[first], answer_rows[second]),
        }
    receipt = {
        "schema": "dualign-mcq-bakeoff-receipt/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "training_performed": False,
        "shadow_or_confirmation_opened": False,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
        "manifest": json.loads(Path(args.manifest).read_text(encoding="utf-8")),
        "models": dict(sorted(model_receipts.items())),
        "paired_comparisons": comparisons,
    }
    write_json(Path(args.output).resolve(), receipt)
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "models": sorted(model_receipts),
            },
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    add_sources(prepare)
    prepare.add_argument("--private-output", required=True)
    prepare.add_argument("--public-output", required=True)
    prepare.set_defaults(function=command_prepare)

    score = subparsers.add_parser("score")
    score.add_argument("--questions", required=True)
    score.add_argument("--model", required=True)
    score.add_argument("--output", required=True)
    score.add_argument("--receipt", required=True)
    score.add_argument("--endpoint", default="http://127.0.0.1:11434")
    score.add_argument("--timeout", type=float, default=180.0)
    score.add_argument("--keep-alive", default="10m")
    score.add_argument("--limit", type=int)
    score.add_argument("--resume", action="store_true")
    score.add_argument("--progress-every", type=int, default=50)
    score.set_defaults(function=command_score)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--manifest", required=True)
    summarize.add_argument("--model-receipts", nargs="+", required=True)
    summarize.add_argument("--output", required=True)
    summarize.set_defaults(function=command_summarize)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
