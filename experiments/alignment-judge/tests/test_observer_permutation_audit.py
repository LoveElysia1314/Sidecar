from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BUILD_PATH = Path(__file__).parents[1] / "tools" / "build_observer_permutation_audit.py"
SCORE_PATH = Path(__file__).parents[1] / "tools" / "run_observer_permutation_audit.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILD = load(BUILD_PATH, "build_observer_permutation_audit")
SCORE = load(SCORE_PATH, "run_observer_permutation_audit")


def test_selected_candidate_id_uses_letter_mapping() -> None:
    question = {
        "options": [
            {"letter": "A", "candidate_id": "x"},
            {"letter": "B", "candidate_id": "y"},
        ]
    }
    assert SCORE.selected_candidate_id(question, "B") == "y"
    assert SCORE.selected_candidate_id(question, None) is None


def test_take_is_deterministic() -> None:
    rows = [{"dataset": "d", "case_id": str(index)} for index in range(10)]
    assert BUILD.take(rows, 4) == BUILD.take(list(reversed(rows)), 4)
