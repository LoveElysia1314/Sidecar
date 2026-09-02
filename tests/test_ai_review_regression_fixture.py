from __future__ import annotations

import json
from pathlib import Path

from dualign.common import load_text_lines
from dualign.services.ai_repair_agent import _get_tools_openai, _load_system_prompt

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "demo" / "ai_review_regression"


def _manifest() -> dict:
    return json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


def test_regression_fixture_is_a_complete_300_by_300_snapshot() -> None:
    manifest = _manifest()
    source = load_text_lines(FIXTURE / "regression.source.md")
    target = load_text_lines(FIXTURE / "regression.target.md")

    assert manifest["logical_line_count"] == 300
    assert len(source) == len(target) == 300
    assert len(manifest["cases"]) == 22

    source_indices = [
        index for operation in manifest["operations"] for index in operation["source"]
    ]
    target_indices = [
        index for operation in manifest["operations"] for index in operation["target"]
    ]
    assert source_indices == list(range(300))
    assert target_indices == list(range(300))


def test_regression_case_index_is_unique_and_self_consistent() -> None:
    manifest = _manifest()
    cases = manifest["cases"]
    case_ids = [case["id"] for case in cases]
    relation_count = len(manifest["operations"])
    expected_review_relations = sorted(
        {
            relation
            for case in cases
            for relation in case.get("review_relations", case["relations"])
        }
    )

    assert len(case_ids) == len(set(case_ids))
    assert manifest["review_relations"] == expected_review_relations
    assert all(0 <= relation < relation_count for relation in expected_review_relations)
    assert {action["kind"] for action in manifest["pre_actions"]} == {"flag"}


def test_regression_fixture_covers_contextual_completeness() -> None:
    cases = {case["id"]: case for case in _manifest()["cases"]}
    long_note = cases["source_long_note_missing"]

    assert long_note["category"] == "contextual_completeness"
    assert set(long_note["expected"]["pair_count_any"]) == {1, 2}
    assert {"translator", "silver"}.issubset(
        set(long_note["expected"]["target_contains_all"])
    )


def test_regression_fixture_covers_relocation_from_an_unflagged_neighbor() -> None:
    cases = {case["id"]: case for case in _manifest()["cases"]}
    relocation = cases["context_relocation_from_previous"]

    assert len(relocation["relations"]) == 2
    assert relocation["review_relations"] == [relocation["relations"][1]]
    assert relocation["expected"]["target_occurrences"] == {"Yuigahama murmured": 1}


def test_prompt_expresses_editorial_goal_instead_of_storage_shape() -> None:
    prompt = _load_system_prompt("src")

    assert "结构平行" in prompt
    assert "正确的语境和位置完整对应" in prompt
    assert "原字形本身正被引用或说明" in prompt
    assert "且不再附带原字形" in prompt
    assert "最终 1:1" not in prompt
    assert "各出现一次" not in prompt
    assert "专名" not in prompt
    assert "对应内容已落在邻文时应搬移" in prompt


def test_edit_region_contract_preserves_independent_units() -> None:
    tools = {tool["name"]: tool for tool in _get_tools_openai()}
    edit_description = tools["edit_region"]["description"]

    assert "one naturally indivisible publishable block" in edit_description
    assert "preserve independent paragraphs or sentences as separate units" in (
        edit_description
    )
    assert "not a container for packing independent blocks together" in (
        edit_description
    )
    assert "relocate it instead of copying it" in edit_description
