from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "run_observer_bakeoff.py"
SPEC = importlib.util.spec_from_file_location("observer_bakeoff", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_quantile_linear_interpolation() -> None:
    assert MODULE.quantile([0.0, 10.0], 0.1) == 1.0
    assert MODULE.quantile([3.0], 0.1) == 3.0


def test_metric_summary_uses_strict_positive_margin() -> None:
    summary = MODULE.metric_summary(
        [
            {"margin": 0.2, "positive_top1": True},
            {"margin": 0.0, "positive_top1": False},
        ]
    )
    assert summary["top1_correct"] == 1
    assert summary["top1_rate"] == 0.5
    assert summary["margin_min"] == 0.0


def test_paired_flips_are_directional() -> None:
    base = {
        "cases": [
            {"dataset": "d", "case_id": "a", "positive_top1": False},
            {"dataset": "d", "case_id": "b", "positive_top1": True},
        ]
    }
    other = {
        "cases": [
            {"dataset": "d", "case_id": "a", "positive_top1": True},
            {"dataset": "d", "case_id": "b", "positive_top1": False},
        ]
    }
    flips = MODULE.paired_flips(base, other)["d"]
    assert flips["wrong_to_correct"] == 1
    assert flips["correct_to_wrong"] == 1
    assert flips["wrong_to_correct_ids"] == ["a"]
    assert flips["correct_to_wrong_ids"] == ["b"]


def test_reranker_instructions_are_distinct() -> None:
    assert MODULE.RETRIEVAL_INSTRUCTION != MODULE.STRICT_EQUIVALENCE_INSTRUCTION
    assert "omission" in MODULE.STRICT_EQUIVALENCE_INSTRUCTION
    assert "addition" in MODULE.STRICT_EQUIVALENCE_INSTRUCTION


def test_extract_hashed_text_rejects_metadata_stringification() -> None:
    text = "body"
    value = {"text": text, "sha256": MODULE.sha256_text(text)}
    assert MODULE.extract_hashed_text(value, "fixture") == text
    try:
        MODULE.extract_hashed_text({"text": text, "sha256": "wrong"}, "fixture")
    except ValueError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("hash mismatch was not rejected")
