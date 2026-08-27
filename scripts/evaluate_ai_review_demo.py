"""Run the bundled real-text Demo through the production AI-review contract.

This is an opt-in live evaluation. It creates a disposable Demo workspace,
runs alignment, and then calls the configured AI-review provider. The command
may incur API cost; ordinary tests never import or execute it.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from dualign.demo import create_demo_working_pair
from dualign.providers import active_repair_agent
from dualign.services.ai_repair_agent import AiRepairAgent, build_agent_review_session
from dualign.services.cli_pipeline import align_documents
from dualign.services.embedding import _try_lazy_load_model
from dualign.services.report_io import load_report, repair_state_from_report

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {
    1: {"edit"},
    6: {"edit", "merge"},
    8: {"edit"},
    21: {"edit", "merge"},
    32: {"delete"},
    38: {"edit", "split"},
}


def _action_ordinals(state, action) -> list[int]:
    return list(state.action_ordinals(action))


def run_demo(output: Path) -> dict:
    provider = active_repair_agent()
    if provider is None or not provider.key_plain:
        raise RuntimeError("未配置可用的 AI 审校提供方或 API Key")
    model = _try_lazy_load_model()
    if model is None:
        raise RuntimeError("嵌入模型未加载")

    document_a, document_b, workspace = create_demo_working_pair()
    report_path = workspace / "sample.report.json"
    aligned = align_documents(
        str(document_a),
        str(document_b),
        str(report_path),
        model=model,
        strategy="src",
    )
    if not aligned.get("success"):
        raise RuntimeError(aligned.get("error", "Demo 对齐失败"))

    state = repair_state_from_report(
        load_report(report_path), str(document_a), str(document_b)
    )
    session = build_agent_review_session(
        state,
        strategy="src",
        model=model,
        chapter_id="sample",
        chapter_title="与天使相遇",
    )
    usage = {"prompt": 0, "cache": 0, "completion": 0}
    tool_calls: list[dict] = []

    def on_event(event) -> None:
        if event.type == "llm_response":
            usage["prompt"] += int(event.usage.get("prompt_tokens", 0))
            usage["cache"] += int(event.usage.get("cached_tokens", 0))
            usage["completion"] += int(event.usage.get("completion_tokens", 0))
        elif event.type == "tool_call":
            tool_calls.append(
                {"turn": event.turn, "name": event.tool_name, "args": event.tool_args}
            )

    agent = AiRepairAgent(
        backend="deepseek",
        max_turns=20,
        verbose=False,
        strategy="src",
        model_name=provider.model_name,
        base_url=provider.base_url,
        api_key=provider.key_plain,
        temperature=provider.temperature,
        max_tokens=provider.max_tokens,
        request_timeout=provider.request_timeout,
    )
    started = time.perf_counter()
    try:
        result = agent.run(
            session.context,
            on_event=on_event,
            initial_state=session.proposed_state,
        )
    finally:
        agent.close()
    elapsed = time.perf_counter() - started

    actual: dict[int, set[str]] = {ordinal: set() for ordinal in EXPECTED}
    action_payloads: list[dict] = []
    for action in result.actions:
        ordinals = _action_ordinals(session.proposed_state, action)
        for ordinal in ordinals:
            if ordinal in actual:
                actual[ordinal].add(action.kind)
        action_payloads.append(
            {
                "kind": action.kind,
                "ordinals": ordinals,
                "source": action.source,
                "data": action.data,
            }
        )
    checks = [
        {
            "relation": ordinal,
            "expected": sorted(kinds),
            "actual": sorted(actual[ordinal]),
            "passed": bool(kinds.intersection(actual[ordinal])),
        }
        for ordinal, kinds in EXPECTED.items()
    ]
    credit_target = "\n".join(
        line
        for action in action_payloads
        if 1 in action["ordinals"]
        for line in action["data"].get("new_tgt_lines", [])
    )
    credit_check = next(check for check in checks if check["relation"] == 1)
    credit_check["text_checks"] = {
        "translated_name": "light novel" in credit_target.casefold(),
        "no_source_script": re.search(r"[\u3400-\u9fff]", credit_target) is None,
    }
    credit_check["passed"] = credit_check["passed"] and all(
        credit_check["text_checks"].values()
    )
    report = {
        "workspace": str(workspace),
        "model": provider.model_name,
        "status": result.status,
        "turns": result.turns,
        "elapsed_seconds": round(elapsed, 3),
        "usage": usage,
        "reviewable_relations": list(session.context.reviewable_ids),
        "score": {
            "passed": sum(check["passed"] for check in checks),
            "total": len(checks),
        },
        "checks": checks,
        "actions": action_payloads,
        "tool_calls": tool_calls,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts" / "ai-prompt-eval" / "demo.json",
    )
    args = parser.parse_args()
    report = run_demo(args.output)
    score = report["score"]
    print(
        f"{score['passed']}/{score['total']}, "
        f"{report['elapsed_seconds']:.1f}s, {report['turns']} turns, "
        f"status={report['status']}"
    )
    for check in report["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(
            f"[{mark}] relation {check['relation']}: "
            f"{check['actual']} (expected {check['expected']})"
        )
    print(f"report: {args.output}")
    return 0 if score["passed"] == score["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
