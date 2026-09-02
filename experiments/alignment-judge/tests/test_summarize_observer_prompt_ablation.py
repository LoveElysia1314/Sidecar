from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1] / "tools" / "summarize_observer_prompt_ablation.py"
)
SPEC = importlib.util.spec_from_file_location(
    "summarize_observer_prompt_ablation", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def receipt(accuracy: float, net: int, wall: float) -> dict:
    return {
        "summary": {
            "overall": {"accuracy": accuracy, "latency_wall_seconds": {"sum": wall}}
        },
        "paired_vs_baseline": {"overall": {"net_second_minus_first_correct": net}},
    }


def test_selection_key_prefers_accuracy_then_net_then_speed() -> None:
    assert MODULE.selection_key(receipt(0.7, 1, 10)) > MODULE.selection_key(
        receipt(0.6, 99, 1)
    )
    assert MODULE.selection_key(receipt(0.7, 2, 10)) > MODULE.selection_key(
        receipt(0.7, 1, 1)
    )
    assert MODULE.selection_key(receipt(0.7, 2, 9)) > MODULE.selection_key(
        receipt(0.7, 2, 10)
    )
