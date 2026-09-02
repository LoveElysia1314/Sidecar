"""Create a body-free receipt for the wrong-union prompt ablation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

EXPECTED_TUNING_VARIANTS = {
    "two_way_coverage",
    "near_miss_elimination",
    "bidirectional_entailment",
}


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "observer_mcq_for_prompt_summary", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MCQ module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_receipt(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def selection_key(receipt: dict[str, Any]) -> tuple[float, int, float]:
    overall = receipt["summary"]["overall"]
    paired = receipt["paired_vs_baseline"]["overall"]
    return (
        float(overall["accuracy"]),
        int(paired["net_second_minus_first_correct"]),
        -float(overall["latency_wall_seconds"]["sum"]),
    )


def public_arm(module: Any, path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    answer_path = Path(receipt["answer_file"]["path"])
    return {
        "receipt_file": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": module.sha256_file(path),
        },
        "answer_file": {
            "path": str(answer_path),
            "bytes": answer_path.stat().st_size,
            "sha256": module.sha256_file(answer_path),
        },
        "model": receipt["model"],
        "prompt_variant": receipt["prompt_variant"],
        "prompt_split": receipt["prompt_split"],
        "system_prompt": receipt["system_prompt"],
        "system_prompt_sha256": receipt["system_prompt_sha256"],
        "generation": receipt["generation"],
        "warmup": receipt["warmup"],
        "summary": receipt["summary"],
        "baseline_summary": receipt["baseline_summary"],
        "paired_vs_baseline": receipt["paired_vs_baseline"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--baseline-answers", required=True)
    parser.add_argument("--tuning-receipts", nargs="+", required=True)
    parser.add_argument("--check-receipt", required=True)
    parser.add_argument("--excluded-partials", nargs="*", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    module = load_module(Path(args.mcq_script).resolve())
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tuning: dict[str, tuple[Path, dict[str, Any]]] = {}
    for value in args.tuning_receipts:
        path = Path(value).resolve()
        receipt = load_receipt(path)
        if receipt["prompt_split"] != "prompt_tuning":
            raise ValueError(f"not a tuning receipt: {path}")
        tuning[receipt["prompt_variant"]] = (path, receipt)
    if set(tuning) != EXPECTED_TUNING_VARIANTS:
        raise ValueError(f"unexpected tuning variants: {sorted(tuning)}")

    winner = max(tuning, key=lambda name: selection_key(tuning[name][1]))
    check_path = Path(args.check_receipt).resolve()
    check = load_receipt(check_path)
    if check["prompt_split"] != "prompt_check" or check["prompt_variant"] != winner:
        raise ValueError("check receipt does not match the selected tuning winner")

    winner_tuning = tuning[winner][1]
    winner_rows = [
        *module.read_jsonl(Path(winner_tuning["answer_file"]["path"])),
        *module.read_jsonl(Path(check["answer_file"]["path"])),
    ]
    union_keys = {(row["dataset"], row["case_id"]) for row in winner_rows}
    if len(winner_rows) != 422 or len(union_keys) != 422:
        raise ValueError("winner tuning/check rows do not cover the 422-case union")
    baseline_path = Path(args.baseline_answers).resolve()
    baseline_rows = [
        row
        for row in module.read_jsonl(baseline_path)
        if (row["dataset"], row["case_id"]) in union_keys
    ]
    if len(baseline_rows) != 422:
        raise ValueError("baseline does not cover the 422-case union")

    excluded = []
    for value in args.excluded_partials:
        path = Path(value).resolve()
        excluded.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": module.sha256_file(path),
                "rows": len(module.read_jsonl(path)),
                "reason": "partial_cpu_offload_diagnostic_excluded_from_scientific_comparison",
            }
        )

    output = {
        "schema": "dualign-observer-prompt-ablation-summary/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "model": "qwen3.5:4b",
        "training_performed": False,
        "shadow_or_confirmation_opened": False,
        "scientific_scope": "error_mined_prompt_development_not_fresh_validation",
        "manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": module.sha256_file(manifest_path),
            "counts": manifest["counts"],
        },
        "baseline_answers": {
            "path": str(baseline_path),
            "bytes": baseline_path.stat().st_size,
            "sha256": module.sha256_file(baseline_path),
        },
        "selection_rule": "max_tuning_accuracy_then_paired_net_then_lower_wall_time",
        "tuning_arms": {
            name: public_arm(module, path, receipt)
            for name, (path, receipt) in sorted(tuning.items())
        },
        "selected_prompt_variant": winner,
        "prompt_check": public_arm(module, check_path, check),
        "selected_prompt_on_full_error_union_descriptive": {
            "summary": module.summarize_rows(winner_rows),
            "baseline_summary": module.summarize_rows(baseline_rows),
            "paired_vs_baseline": module.paired_comparison(baseline_rows, winner_rows),
        },
        "excluded_partial_runs": excluded,
        "interpretation_guardrails": [
            "The 422 cases were selected because at least one baseline model was wrong.",
            "Prompt-check reduces prompt-selection overfit but is still 4B-error-mined.",
            "Do not report full-corpus accuracy or sealed generalization from this experiment.",
            "No further prompt was designed after prompt-check was opened.",
        ],
    }
    module.write_json(Path(args.output).resolve(), output)
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "winner": winner,
                "tuning_accuracy": winner_tuning["summary"]["overall"]["accuracy"],
                "check_accuracy": check["summary"]["overall"]["accuracy"],
                "full_error_union": output[
                    "selected_prompt_on_full_error_union_descriptive"
                ]["summary"]["overall"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
