from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "run_observer_prompt_ablation.py"
SPEC = importlib.util.spec_from_file_location("observer_prompt_ablation", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_ablation_is_locked_to_4b() -> None:
    assert MODULE.MODEL == "qwen3.5:4b"


def test_prompt_variants_are_distinct_and_letter_only() -> None:
    assert len(MODULE.PROMPTS) == 3
    assert len(set(MODULE.PROMPTS.values())) == 3
    assert MODULE.OPTIONS["num_ctx"] == 8192
    for prompt in MODULE.PROMPTS.values():
        assert "only" in prompt.lower()
        assert "letter" in prompt.lower()
