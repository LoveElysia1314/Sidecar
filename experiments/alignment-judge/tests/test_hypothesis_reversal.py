from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1] / "tools" / "finalize_observer_hypothesis_reversal.py"
)
SPEC = importlib.util.spec_from_file_location(
    "observer_hypothesis_reversal", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_mcnemar_exact_matches_frozen_primary_comparison() -> None:
    assert MODULE.mcnemar_exact(65, 28) == 0.0001575707877910854
    assert MODULE.mcnemar_exact(0, 0) == 1.0


def test_paired_counts_are_directional() -> None:
    candidate = {
        ("d", "1"): True,
        ("d", "2"): True,
        ("d", "3"): False,
        ("d", "4"): False,
    }
    baseline = {
        ("d", "1"): True,
        ("d", "2"): False,
        ("d", "3"): True,
        ("d", "4"): False,
    }
    result = MODULE.paired(candidate, baseline)
    assert result["both_correct"] == 1
    assert result["candidate_only_correct"] == 1
    assert result["baseline_only_correct"] == 1
    assert result["both_wrong"] == 1
    assert result["net_candidate_minus_baseline_correct"] == 0
    assert result["mcnemar_exact_two_sided_p"] == 1.0


def test_compact_model_drops_local_parent_path() -> None:
    compact = MODULE.compact_model(
        {
            "name": "m",
            "digest": "d",
            "size": 1,
            "details": {"parameter_size": "4B", "parent_model": "/private/model"},
        }
    )
    assert compact["details"] == {"parameter_size": "4B"}
