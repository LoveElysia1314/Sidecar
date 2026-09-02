from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1] / "tools" / "audit_observer_architecture_prompt.py"
)
SPEC = importlib.util.spec_from_file_location(
    "audit_observer_architecture_prompt", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_position_summary_groups_by_gold_letter() -> None:
    rows = [
        {"answer_letter": "A", "predicted_letter": "A", "correct": True},
        {"answer_letter": "A", "predicted_letter": "B", "correct": False},
        {"answer_letter": "B", "predicted_letter": "B", "correct": True},
    ]
    summary = MODULE.position_summary(rows)
    assert summary["A"] == {"questions": 2, "correct": 1, "accuracy": 0.5}
    assert summary["B"] == {"questions": 1, "correct": 1, "accuracy": 1.0}
    assert MODULE.predicted_distribution(rows) == {"A": 1, "B": 2}
