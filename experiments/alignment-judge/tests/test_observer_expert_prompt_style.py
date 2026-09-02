from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1] / "tools" / "run_observer_expert_prompt_style.py"
)
SPEC = importlib.util.spec_from_file_location(
    "observer_expert_prompt_style", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_expert_prompts_are_three_distinct_single_letter_styles() -> None:
    assert set(MODULE.PROMPTS) == {
        "p5_semantic_set_equality",
        "p6_mutual_substitutability",
        "p7_compact_balanced_entailment",
    }
    assert len(set(MODULE.PROMPTS.values())) == 3
    for prompt in MODULE.PROMPTS.values():
        assert "only the best option letter" in prompt


def test_challenger_gate_protects_attribute_and_addition() -> None:
    metric = lambda accuracy: {"accuracy": accuracy, "parse_failures": 0}
    baseline = {
        "overall": metric(0.9),
        "by_dataset": {"d": metric(0.9)},
        "by_family": {
            "adjacent_addition+unrelated": metric(0.8),
            "attribute_counterfactual+unrelated": metric(0.9),
            "coverage_completeness": metric(0.7),
        },
    }
    candidate = {
        "overall": metric(0.91),
        "by_dataset": {"d": metric(0.91)},
        "by_family": {
            "adjacent_addition+unrelated": metric(0.81),
            "attribute_counterfactual+unrelated": metric(0.89),
            "coverage_completeness": metric(0.71),
        },
    }
    gate = MODULE.challenger_gate(
        baseline, candidate, {"net_second_minus_first_correct": 1}
    )
    assert not gate["protected_family_nonregression"][
        "attribute_counterfactual+unrelated"
    ]
    assert not gate["passed"]
