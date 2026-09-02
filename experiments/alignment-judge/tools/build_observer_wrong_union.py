"""Build a private raw corpus from the union of two observer MCQ error sets."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "dualign-observer-wrong-union/v1"
SPLIT_SEED = "dualign-observer-wrong-union-prompt-split/v1"


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("observer_mcq_for_union", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MCQ module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def index_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index = {(str(row["dataset"]), str(row["case_id"])): row for row in rows}
    if len(index) != len(rows):
        raise ValueError("duplicate dataset/case key")
    return index


def error_pattern(first: dict[str, Any], second: dict[str, Any]) -> str | None:
    first_wrong = not bool(first["correct"])
    second_wrong = not bool(second["correct"])
    if first_wrong and second_wrong:
        return "both_wrong"
    if first_wrong:
        return "qwen3.5_2b_wrong_only"
    if second_wrong:
        return "qwen3.5_4b_wrong_only"
    return None


def split_rows(rows: list[dict[str, Any]], tuning_fraction: float = 0.70) -> None:
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strata[(row["dataset"], row["error_pattern"])].append(row)
    for stratum, members in sorted(strata.items()):
        ordered = sorted(
            members,
            key=lambda row: hashlib.sha256(
                f"{SPLIT_SEED}|{row['dataset']}|{row['case_id']}".encode("utf-8")
            ).hexdigest(),
        )
        tuning_count = round(len(ordered) * tuning_fraction)
        for index, row in enumerate(ordered):
            row["prompt_split"] = (
                "prompt_tuning" if index < tuning_count else "prompt_check"
            )
            row["prompt_split_stratum"] = f"{stratum[0]}|{stratum[1]}"


def build_union(
    questions: list[dict[str, Any]],
    first_answers: list[dict[str, Any]],
    second_answers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    question_index = index_rows(questions)
    first_index = index_rows(first_answers)
    second_index = index_rows(second_answers)
    if set(question_index) != set(first_index) or set(question_index) != set(
        second_index
    ):
        raise ValueError("question and answer key sets differ")
    union: list[dict[str, Any]] = []
    for key in sorted(question_index):
        first = first_index[key]
        second = second_index[key]
        pattern = error_pattern(first, second)
        if pattern is None:
            continue
        question = dict(question_index[key])
        question.update(
            {
                "schema": SCHEMA,
                "selection_rule": "qwen3.5:2b_wrong_or_qwen3.5:4b_wrong",
                "error_pattern": pattern,
                "baseline_answers": {
                    "qwen3.5:2b": {
                        "predicted_letter": first["predicted_letter"],
                        "correct": bool(first["correct"]),
                    },
                    "qwen3.5:4b": {
                        "predicted_letter": second["predicted_letter"],
                        "correct": bool(second["correct"]),
                    },
                },
            }
        )
        union.append(question)
    split_rows(union)
    return sorted(
        union, key=lambda row: (row["prompt_split"], row["dataset"], row["case_id"])
    )


def public_row(module: Any, row: dict[str, Any]) -> dict[str, Any]:
    public = module.public_question(row)
    public.update(
        {
            "selection_rule": row["selection_rule"],
            "error_pattern": row["error_pattern"],
            "prompt_split": row["prompt_split"],
            "prompt_split_stratum": row["prompt_split_stratum"],
            "baseline_answers": row["baseline_answers"],
        }
    )
    return public


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--first-answers", required=True)
    parser.add_argument("--second-answers", required=True)
    parser.add_argument("--private-output", required=True)
    parser.add_argument("--public-output", required=True)
    args = parser.parse_args()

    module = load_module(Path(args.mcq_script).resolve())
    paths = {
        "questions": Path(args.questions).resolve(),
        "qwen3.5_2b_answers": Path(args.first_answers).resolve(),
        "qwen3.5_4b_answers": Path(args.second_answers).resolve(),
    }
    union = build_union(
        read_jsonl(paths["questions"]),
        read_jsonl(paths["qwen3.5_2b_answers"]),
        read_jsonl(paths["qwen3.5_4b_answers"]),
    )
    counts = Counter(row["error_pattern"] for row in union)
    split_counts = Counter(row["prompt_split"] for row in union)
    if len(union) != 422 or counts != {
        "both_wrong": 145,
        "qwen3.5_2b_wrong_only": 247,
        "qwen3.5_4b_wrong_only": 30,
    }:
        raise ValueError(
            f"unexpected union counts: total={len(union)}, patterns={dict(counts)}"
        )
    if split_counts != {"prompt_tuning": 296, "prompt_check": 126}:
        raise ValueError(f"unexpected prompt split counts: {dict(split_counts)}")

    private_output = Path(args.private_output).resolve()
    public_output = Path(args.public_output).resolve()
    write_jsonl(private_output, union)
    manifest = {
        "schema": "dualign-observer-wrong-union-manifest/v1",
        "created_at_unix": time.time(),
        "contains_body_text": False,
        "selection_rule": "qwen3.5:2b_wrong_or_qwen3.5:4b_wrong",
        "selection_is_error_mined_and_not_fresh_evaluation": True,
        "split_seed": SPLIT_SEED,
        "tuning_fraction_within_dataset_and_error_pattern": 0.70,
        "counts": {
            "total": len(union),
            "by_error_pattern": dict(sorted(counts.items())),
            "by_prompt_split": dict(sorted(split_counts.items())),
            "by_dataset": dict(
                sorted(Counter(row["dataset"] for row in union).items())
            ),
        },
        "inputs": {
            name: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": module.sha256_file(path),
            }
            for name, path in paths.items()
        },
        "private_raw_corpus": {
            "path": str(private_output),
            "bytes": private_output.stat().st_size,
            "sha256": module.sha256_file(private_output),
            "contains_body_text": True,
        },
        "rows": [public_row(module, row) for row in union],
    }
    module.write_json(public_output, manifest)
    print(
        json.dumps(
            {
                "private": str(private_output),
                "public": str(public_output),
                "counts": manifest["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
