from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "run_observer_mcq.py"
SPEC = importlib.util.spec_from_file_location("observer_mcq", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    text: str
    exact: bool


@dataclass(frozen=True)
class Case:
    dataset: str
    case_id: str
    direction: str
    work_or_cluster_id: str
    role: str
    anchor: str
    candidates: tuple[Candidate, ...]


def fixture_case() -> Case:
    return Case(
        dataset="fixture",
        case_id="case-1",
        direction="zh-en",
        work_or_cluster_id="cluster",
        role="development",
        anchor="猫在睡觉。",
        candidates=(
            Candidate("exact", "exact", "The cat is sleeping.", True),
            Candidate("partial", "omission", "The cat.", False),
            Candidate("other", "unrelated", "The dog runs.", False),
        ),
    )


def test_question_order_and_answer_are_deterministic() -> None:
    first = MODULE.build_question(fixture_case())
    second = MODULE.build_question(fixture_case())
    assert first == second
    assert first["answer_letter"] in first["valid_letters"]
    assert sum(option["exact"] for option in first["options"]) == 1


def test_public_question_contains_no_body_text() -> None:
    public = MODULE.public_question(MODULE.build_question(fixture_case()))
    encoded = str(public)
    assert "猫在睡觉" not in encoded
    assert "The cat is sleeping" not in encoded
    assert "anchor_sha256" in public


def test_parser_is_strict_but_accepts_declared_wrappers() -> None:
    assert MODULE.parse_response("A", ["A", "B"]) == "A"
    assert MODULE.parse_response("Answer: (b).", ["A", "B"]) == "B"
    assert MODULE.parse_response("答案：A", ["A", "B"]) == "A"
    assert MODULE.parse_response("I think A", ["A", "B"]) is None
    assert MODULE.parse_response("C", ["A", "B"]) is None


def test_wilson_interval_contains_observed_accuracy() -> None:
    lower, upper = MODULE.wilson_interval(8, 10)
    assert lower < 0.8 < upper


def test_accuracy_counts_parse_failure_as_wrong() -> None:
    rows = [
        {
            "correct": True,
            "predicted_letter": "A",
            "wall_seconds": 1.0,
            "api_total_seconds": 0.9,
            "prompt_eval_count": 10,
            "eval_count": 1,
            "eval_seconds": 0.1,
        },
        {
            "correct": False,
            "predicted_letter": None,
            "wall_seconds": 2.0,
            "api_total_seconds": 1.9,
            "prompt_eval_count": 20,
            "eval_count": 2,
            "eval_seconds": 0.2,
        },
    ]
    summary = MODULE.accuracy_summary(rows)
    assert summary["accuracy"] == 0.5
    assert summary["parse_failures"] == 1
    assert summary["latency_wall_seconds"]["sum"] == 3.0


def test_paired_counts_are_directional() -> None:
    first = [
        {"dataset": "d", "case_id": "a", "correct": True, "predicted_letter": "A"},
        {"dataset": "d", "case_id": "b", "correct": False, "predicted_letter": "B"},
    ]
    second = [
        {"dataset": "d", "case_id": "a", "correct": False, "predicted_letter": "B"},
        {"dataset": "d", "case_id": "b", "correct": True, "predicted_letter": "A"},
    ]
    result = MODULE.paired_counts(first, second)
    assert result["first_only_correct"] == 1
    assert result["second_only_correct"] == 1
    assert result["net_second_minus_first_correct"] == 0
    assert result["mcnemar_exact_two_sided_p"] == 1.0
