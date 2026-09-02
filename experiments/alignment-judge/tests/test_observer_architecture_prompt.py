from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1] / "tools" / "run_observer_architecture_prompt.py"
)
SPEC = importlib.util.spec_from_file_location(
    "observer_architecture_prompt", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_prompt_matches_forced_choice_architecture() -> None:
    prompt = MODULE.SYSTEM_PROMPT
    assert "bilingual or multilingual" in prompt
    assert "Choose the one candidate" in prompt
    assert "only the best option letter" in prompt
    assert "Do not rewrite or explain" in prompt
    assert "AMBIGUOUS" not in prompt.upper()
    assert "`NONE`" not in prompt.upper()
    assert "candidate ID" not in prompt


def test_replacement_gate_requires_dataset_and_family_nonregression() -> None:
    metric = lambda accuracy: {
        "accuracy": accuracy,
        "questions": 1,
        "parse_failures": 0,
    }
    baseline = {
        "overall": metric(0.5),
        "by_dataset": {"d": metric(0.5)},
        "by_family": {"adjacent_addition+unrelated": metric(0.5)},
    }
    candidate = {
        "overall": metric(0.6),
        "by_dataset": {"d": metric(0.6)},
        "by_family": {"adjacent_addition+unrelated": metric(0.4)},
    }
    gate = MODULE.replacement_gate(baseline, candidate)
    assert gate["checks"]["overall_accuracy_improved"]
    assert not gate["checks"]["all_critical_families_nonregressed"]
    assert not gate["passed"]
