from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "build_observer_wrong_union.py"
SPEC = importlib.util.spec_from_file_location("observer_wrong_union", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def answer(correct: bool) -> dict[str, object]:
    return {"correct": correct, "predicted_letter": "A" if correct else "B"}


def test_error_pattern_covers_union_only() -> None:
    assert MODULE.error_pattern(answer(False), answer(False)) == "both_wrong"
    assert MODULE.error_pattern(answer(False), answer(True)) == "qwen3.5_2b_wrong_only"
    assert MODULE.error_pattern(answer(True), answer(False)) == "qwen3.5_4b_wrong_only"
    assert MODULE.error_pattern(answer(True), answer(True)) is None


def test_split_is_deterministic_and_stratified() -> None:
    rows = [
        {"dataset": "d", "error_pattern": "both_wrong", "case_id": str(index)}
        for index in range(10)
    ]
    copy = [dict(row) for row in rows]
    MODULE.split_rows(rows)
    MODULE.split_rows(copy)
    assert rows == copy
    assert sum(row["prompt_split"] == "prompt_tuning" for row in rows) == 7
