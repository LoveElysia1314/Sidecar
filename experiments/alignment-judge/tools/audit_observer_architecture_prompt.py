"""Create a body-free option-position audit for an observer prompt comparison."""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "observer_mcq_for_position_audit", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MCQ module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def position_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        grouped[str(row["answer_letter"])].append(row)
    return {
        letter: {
            "questions": len(values),
            "correct": sum(bool(row["correct"]) for row in values),
            "accuracy": sum(bool(row["correct"]) for row in values) / len(values),
        }
        for letter, values in sorted(grouped.items())
    }


def predicted_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        sorted(collections.Counter(row["predicted_letter"] for row in rows).items())
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--baseline-answers", required=True)
    parser.add_argument("--candidate-answers", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    module = load_module(Path(args.mcq_script).resolve())
    baseline_path = Path(args.baseline_answers).resolve()
    candidate_path = Path(args.candidate_answers).resolve()
    baseline = module.read_jsonl(baseline_path)
    candidate = module.read_jsonl(candidate_path)
    base_index = {(row["dataset"], row["case_id"]): row for row in baseline}
    cand_index = {(row["dataset"], row["case_id"]): row for row in candidate}
    if set(base_index) != set(cand_index) or len(base_index) != 1736:
        raise ValueError("answer key sets differ or do not contain 1736 cases")

    paired_by_gold: dict[str, Any] = {}
    for letter in sorted({row["answer_letter"] for row in baseline}):
        base_rows = [row for row in baseline if row["answer_letter"] == letter]
        keys = {(row["dataset"], row["case_id"]) for row in base_rows}
        cand_rows = [
            row for row in candidate if (row["dataset"], row["case_id"]) in keys
        ]
        paired_by_gold[letter] = module.paired_counts(base_rows, cand_rows)

    payload = {
        "schema": "dualign-observer-option-position-audit/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "same_permutation_used_for_both_prompts": True,
        "baseline_file": {
            "path": str(baseline_path),
            "bytes": baseline_path.stat().st_size,
            "sha256": module.sha256_file(baseline_path),
        },
        "candidate_file": {
            "path": str(candidate_path),
            "bytes": candidate_path.stat().st_size,
            "sha256": module.sha256_file(candidate_path),
        },
        "gold_position_counts": dict(
            sorted(
                collections.Counter(row["answer_letter"] for row in baseline).items()
            )
        ),
        "baseline": {
            "by_gold_position": position_summary(baseline),
            "predicted_position_counts": predicted_distribution(baseline),
        },
        "candidate": {
            "by_gold_position": position_summary(candidate),
            "predicted_position_counts": predicted_distribution(candidate),
        },
        "paired_by_gold_position": paired_by_gold,
        "interpretation": (
            "The fixed-permutation paired gain may include reduced option-symbol bias. "
            "A separate re-permutation audit is required before claiming position invariance."
        ),
    }
    module.write_json(Path(args.output).resolve(), payload)
    print(
        json.dumps(
            {"output": str(Path(args.output).resolve()), "paired": paired_by_gold},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
