"""Run the tracked AI-review prompt corpus against a configured backend.

This is an opt-in live evaluation: it uses the active AI-review provider and
therefore may incur API cost.  The fixture bypasses embedding alignment on
purpose so the score isolates Agent prompting and tool behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dualign.common import load_text_lines
from dualign.core.text import smart_join_lines
from dualign.models.action import CONTENT_ACTION_KINDS, RepairAction
from dualign.models.state import AlignmentSnapshot
from dualign.providers import active_repair_agent
from dualign.services import ai_repair_agent as agent_module
from dualign.services.ai_repair_agent import AiRepairAgent, build_agent_review_session
from dualign.services.repair import RepairState

DEFAULT_FIXTURE = ROOT / "demo" / "ai_review_regression"


def _prompt_body(path: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) == 3:
            content = parts[2].strip()
    return content


def load_fixture(path: Path) -> tuple[RepairState, dict]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    source = load_text_lines(path / "regression.source.md")
    target = load_text_lines(path / "regression.target.md")
    operations = [
        (item["source"], item["target"], item["score"])
        for item in manifest["operations"]
    ]
    snapshot = AlignmentSnapshot.from_alignment(operations, source, target)
    state = RepairState(snapshot)
    for raw in manifest.get("pre_actions", []):
        ordinals = tuple(int(value) for value in raw["relations"])
        action = state.make_action(
            raw["kind"],
            ordinals[0],
            ordinals=ordinals,
            source=raw.get("source", "auto"),
            **raw.get("data", {}),
        )
        state = state.apply(action)
    return state, manifest


def _current_units(state: RepairState, action: RepairAction) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    for ordinal in state.action_ordinals(action):
        group = state.current.group(ordinal)
        if group is None:
            continue
        units.extend(
            (row.src_text, row.tgt_text)
            for row in group.rows
            if row.src_text or row.tgt_text
        )
    return units


def _action_units(state: RepairState, action: RepairAction) -> list[tuple[str, str]]:
    if action.kind == "delete":
        return []
    if action.kind == "merge":
        source: list[str] = []
        target: list[str] = []
        for ordinal in state.action_ordinals(action):
            src_indices, tgt_indices, _score = state.snapshot.original_ops[ordinal]
            source.extend(state.snapshot.src_text(index) for index in src_indices)
            target.extend(state.snapshot.tgt_text(index) for index in tgt_indices)
        return [(smart_join_lines(source), smart_join_lines(target))]
    if action.kind in {"edit", "split"}:
        source = list(action.data.get("new_src_lines", []))
        target = list(action.data.get("new_tgt_lines", []))
        size = max(len(source), len(target))
        return [
            (
                source[index] if index < len(source) else "",
                target[index] if index < len(target) else "",
            )
            for index in range(size)
        ]
    return _current_units(state, action)


def _case_actions(
    state: RepairState, actions: list[RepairAction], ordinals: list[int]
) -> list[RepairAction]:
    relation_ids = {state.snapshot.relation_id(ordinal) for ordinal in ordinals}
    relevant = [
        action
        for action in actions
        if relation_ids.intersection(action.relation_ids) and action.kind != "flag"
    ]
    content = [action for action in relevant if action.kind in CONTENT_ACTION_KINDS]
    return content or relevant


def _initial_units(state: RepairState, ordinals: list[int]) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    for ordinal in ordinals:
        src_indices, tgt_indices, _score = state.snapshot.original_ops[ordinal]
        size = max(len(src_indices), len(tgt_indices))
        units.extend(
            (
                (
                    state.snapshot.src_text(src_indices[index])
                    if index < len(src_indices)
                    else ""
                ),
                (
                    state.snapshot.tgt_text(tgt_indices[index])
                    if index < len(tgt_indices)
                    else ""
                ),
            )
            for index in range(size)
        )
    return units


def grade_cases(
    state: RepairState, manifest: dict, actions: list[RepairAction]
) -> list[dict]:
    graded: list[dict] = []
    for case in manifest["cases"]:
        expected = case["expected"]
        case_actions = _case_actions(state, actions, case["relations"])
        units = [
            unit for action in case_actions for unit in _action_units(state, action)
        ]
        source_text = "\n".join(source for source, _target in units)
        target_text = "\n".join(target for _source, target in units)
        kinds = [action.kind for action in case_actions]
        checks: list[tuple[str, bool]] = []

        allowed = set(expected.get("allowed_kinds", []))
        if allowed:
            checks.append(
                ("action", bool(kinds) and all(kind in allowed for kind in kinds))
            )
        if "pair_count" in expected:
            checks.append(("pair_count", len(units) == int(expected["pair_count"])))
        if "pair_count_any" in expected:
            allowed_counts = {int(value) for value in expected["pair_count_any"]}
            checks.append(("pair_count", len(units) in allowed_counts))
        if expected.get("unchanged"):
            checks.append(
                ("unchanged", units == _initial_units(state, case["relations"]))
            )
        for value in expected.get("source_contains_all", []):
            checks.append((f"source contains {value!r}", value in source_text))
        for value in expected.get("target_contains_all", []):
            checks.append(
                (
                    f"target contains {value!r}",
                    value.casefold() in target_text.casefold(),
                )
            )
        for value in expected.get("target_forbidden", []):
            checks.append(
                (
                    f"target excludes {value!r}",
                    value.casefold() not in target_text.casefold(),
                )
            )
        for values in expected.get("target_forbidden_all", []):
            checks.append(
                (
                    f"target does not contain all of {values!r}",
                    not all(
                        value.casefold() in target_text.casefold() for value in values
                    ),
                )
            )
        for value, count in expected.get("target_occurrences", {}).items():
            checks.append(
                (
                    f"target count {value!r}={count}",
                    target_text.casefold().count(value.casefold()) == int(count),
                )
            )
        for value, count in expected.get("target_max_occurrences", {}).items():
            checks.append(
                (
                    f"target count {value!r}<={count}",
                    target_text.casefold().count(value.casefold()) <= int(count),
                )
            )
        passed = bool(checks) and all(ok for _label, ok in checks)
        graded.append(
            {
                "id": case["id"],
                "title": case["title"],
                "category": case["category"],
                "passed": passed,
                "actions": kinds,
                "failed_checks": [label for label, ok in checks if not ok],
                "units": [{"src": source, "tgt": target} for source, target in units],
            }
        )
    return graded


def run_evaluation(
    *,
    fixture: Path,
    prompt: Path,
    max_turns: int,
    output: Path,
    case_ids: list[str] | None = None,
) -> dict:
    state, manifest = load_fixture(fixture)
    if case_ids:
        selected = set(case_ids)
        cases = [case for case in manifest["cases"] if case["id"] in selected]
        missing = selected.difference(case["id"] for case in cases)
        if missing:
            raise ValueError(f"未知案例: {', '.join(sorted(missing))}")
        manifest["cases"] = cases
        manifest["review_relations"] = sorted(
            {
                ordinal
                for case in cases
                for ordinal in case.get("review_relations", case["relations"])
            }
        )
    session = build_agent_review_session(
        state,
        strategy=manifest.get("strategy", "src"),
        model=None,
        chapter_id="ai-review-regression",
        chapter_title="AI 审校专用回归语料",
        reviewable_ids=manifest["review_relations"],
    )
    provider = active_repair_agent()
    if provider is None or not provider.key_plain:
        raise RuntimeError("未配置可用的 AI 审校提供方或 API Key")

    prompt_text = _prompt_body(prompt)
    original_loader = agent_module._load_system_prompt
    usage = {"prompt": 0, "cache": 0, "completion": 0}
    tool_calls: list[dict] = []
    turn_log: list[dict] = []

    def on_event(event) -> None:
        if event.type == "llm_response":
            usage["prompt"] += int(event.usage.get("prompt_tokens", 0))
            usage["cache"] += int(event.usage.get("cached_tokens", 0))
            usage["completion"] += int(event.usage.get("completion_tokens", 0))
        elif event.type == "tool_call":
            tool_calls.append(
                {"turn": event.turn, "name": event.tool_name, "args": event.tool_args}
            )
        elif event.type == "done":
            turn_log[:] = list(event.turn_log)

    started = time.perf_counter()
    agent_module._load_system_prompt = lambda _strategy="src": prompt_text
    agent = AiRepairAgent(
        backend="deepseek",
        max_turns=max_turns,
        verbose=False,
        strategy=manifest.get("strategy", "src"),
        model_name=provider.model_name,
        base_url=provider.base_url,
        api_key=provider.key_plain,
        temperature=provider.temperature,
        max_tokens=provider.max_tokens,
        request_timeout=provider.request_timeout,
    )
    try:
        result = agent.run(
            session.context,
            on_event=on_event,
            initial_state=session.proposed_state,
        )
    finally:
        agent.close()
        agent_module._load_system_prompt = original_loader
    elapsed = time.perf_counter() - started
    cases = grade_cases(session.proposed_state, manifest, result.actions)
    passed = sum(case["passed"] for case in cases)
    report = {
        "fixture": str(fixture),
        "prompt": str(prompt),
        "model": provider.model_name,
        "status": result.status,
        "turns": result.turns,
        "elapsed_seconds": round(elapsed, 3),
        "usage": usage,
        "reviewed_relations": list(result.reviewed_ids),
        "pending_relations": list(result.pending_ids),
        "score": {"passed": passed, "total": len(cases), "rate": passed / len(cases)},
        "cases": cases,
        "tool_calls": tool_calls,
        "turn_log": turn_log,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--prompt",
        type=Path,
        default=ROOT / "src" / "dualign" / "services" / "prompts" / "agent-prompt.md",
    )
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="只运行指定案例 ID；可重复传入。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts" / "ai-prompt-eval" / "latest.json",
    )
    args = parser.parse_args()
    report = run_evaluation(
        fixture=args.fixture,
        prompt=args.prompt,
        max_turns=args.max_turns,
        output=args.output,
        case_ids=args.case_ids,
    )
    score = report["score"]
    print(
        f"{score['passed']}/{score['total']} ({score['rate']:.1%}), "
        f"{report['elapsed_seconds']:.1f}s, {report['turns']} turns, "
        f"status={report['status']}"
    )
    for case in report["cases"]:
        mark = "PASS" if case["passed"] else "FAIL"
        detail = ", ".join(case["failed_checks"])
        print(f"[{mark}] {case['id']}: {detail}")
    print(f"report: {args.output}")
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
