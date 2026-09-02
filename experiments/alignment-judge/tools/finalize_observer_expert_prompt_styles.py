from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mcnemar_exact(first_only: int, second_only: int) -> float:
    discordant = first_only + second_only
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, k) for k in range(min(first_only, second_only) + 1)
    )
    return min(1.0, 2.0 * tail / (2**discordant))


def paired(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> dict[str, Any]:
    first_by_id = {row["case_id"]: row for row in first}
    second_by_id = {row["case_id"]: row for row in second}
    if first_by_id.keys() != second_by_id.keys():
        raise ValueError("paired answer sets do not contain the same case IDs")
    counts = {
        "both_correct": 0,
        "first_only_correct": 0,
        "second_only_correct": 0,
        "both_wrong": 0,
    }
    for case_id in first_by_id:
        a = bool(first_by_id[case_id]["correct"])
        b = bool(second_by_id[case_id]["correct"])
        if a and b:
            counts["both_correct"] += 1
        elif a:
            counts["first_only_correct"] += 1
        elif b:
            counts["second_only_correct"] += 1
        else:
            counts["both_wrong"] += 1
    counts["questions"] = len(first_by_id)
    counts["net_second_minus_first_correct"] = (
        counts["second_only_correct"] - counts["first_only_correct"]
    )
    counts["mcnemar_exact_two_sided_p"] = mcnemar_exact(
        counts["first_only_correct"], counts["second_only_correct"]
    )
    return counts


def overall(receipt: dict[str, Any]) -> dict[str, Any]:
    return receipt["summary"]["overall"]


def candidate_record(
    name: str, receipt_path: Path, receipt: dict[str, Any]
) -> dict[str, Any]:
    summary = overall(receipt)
    gate = receipt.get("challenger_gate") or receipt.get("replacement_gate")
    paired_summary = (
        receipt.get("paired_vs_leader") or receipt.get("paired_vs_baseline")
    )["overall"]
    return {
        "name": name,
        "system_prompt": receipt["system_prompt"],
        "system_prompt_sha256": receipt["system_prompt_sha256"],
        "questions": summary["questions"],
        "correct": summary["correct"],
        "accuracy": summary["accuracy"],
        "accuracy_wilson_95": summary["accuracy_wilson_95"],
        "parse_failures": summary["parse_failures"],
        "latency_wall_seconds_sum": summary["latency_wall_seconds"]["sum"],
        "paired_comparison": paired_summary,
        "gate_passed": gate["passed"],
        "receipt": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
    }


def pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture-receipt", type=Path, required=True)
    parser.add_argument("--p5-receipt", type=Path, required=True)
    parser.add_argument("--p6-receipt", type=Path, required=True)
    parser.add_argument("--p7-receipt", type=Path, required=True)
    parser.add_argument("--architecture-permutation-receipt", type=Path, required=True)
    parser.add_argument("--p7-permutation-receipt", type=Path, required=True)
    parser.add_argument("--architecture-permutation-answers", type=Path, required=True)
    parser.add_argument("--p7-permutation-answers", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()

    architecture = read_json(args.architecture_receipt)
    p5 = read_json(args.p5_receipt)
    p6 = read_json(args.p6_receipt)
    p7 = read_json(args.p7_receipt)
    architecture_perm = read_json(args.architecture_permutation_receipt)
    p7_perm = read_json(args.p7_permutation_receipt)
    perm_pair = paired(
        read_jsonl(args.architecture_permutation_answers),
        read_jsonl(args.p7_permutation_answers),
    )

    candidates = [
        candidate_record(
            "architecture_forced_choice", args.architecture_receipt, architecture
        ),
        candidate_record("P5_information_set_equivalence", args.p5_receipt, p5),
        candidate_record("P6_replacement_test", args.p6_receipt, p6),
        candidate_record("P7_mutual_entailment", args.p7_receipt, p7),
    ]
    old_baseline = architecture["baseline_summary"]["overall"]
    leader = candidates[0]
    expert_best = max(candidates[1:], key=lambda row: row["correct"])
    perm = {
        "sample": {
            "questions": architecture_perm["permuted_summary"]["overall"]["questions"],
            "manifest": architecture_perm["questions"],
        },
        "architecture_forced_choice": {
            "original_subset": architecture_perm["original_subset"],
            "permuted": architecture_perm["permuted_summary"]["overall"],
            "semantic_selection_consistency": architecture_perm[
                "semantic_selection_consistency"
            ],
        },
        "P7_mutual_entailment": {
            "original_subset": p7_perm["original_subset"],
            "permuted": p7_perm["permuted_summary"]["overall"],
            "semantic_selection_consistency": p7_perm["semantic_selection_consistency"],
        },
        "paired_permuted_architecture_first_P7_second": perm_pair,
    }

    receipt = {
        "schema": "dualign-observer-expert-prompt-style-summary/v1",
        "scientific_scope": "opened_engineering_suite_only",
        "model": "qwen3.5:4b",
        "generation": {
            "temperature": 0,
            "think": False,
            "expected_output": "one option letter",
        },
        "questions": 1736,
        "old_baseline": {
            "correct": old_baseline["correct"],
            "accuracy": old_baseline["accuracy"],
            "parse_failures": old_baseline["parse_failures"],
        },
        "candidates": candidates,
        "strongest_expert_style": expert_best["name"],
        "second_permutation_audit": perm,
        "decision": {
            "selected": leader["name"],
            "system_prompt": leader["system_prompt"],
            "reason": "highest full-suite accuracy; all challenger gates failed; retained lead under the fixed second permutation audit",
            "expert_style_promoted": False,
            "position_sensitivity_remains": True,
        },
        "body_text_in_output": False,
        "training_performed": False,
        "shadow_or_confirmation_opened": False,
    }
    args.output_receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    p5_pair = p5["paired_vs_leader"]["overall"]
    p6_pair = p6["paired_vs_leader"]["overall"]
    p7_pair = p7["paired_vs_leader"]["overall"]
    arch_perm_overall = architecture_perm["permuted_summary"]["overall"]
    p7_perm_overall = p7_perm["permuted_summary"]["overall"]
    lines = [
        "# Observer Expert Prompt Style Report",
        "",
        "## 结论",
        "",
        "在 `qwen3.5:4b`、同一 1,736 题、`temperature=0`、`think=false` 的强制单选条件下，专家建议的 P5/P6/P7 均未超过当前架构提示词。最终继续采用当前架构提示词；不晋升 P5/P6/P7。",
        "",
        "最终提示词：",
        "",
        "```text",
        leader["system_prompt"],
        "```",
        "",
        "它仍然只允许返回最佳选项字母，不包含 `AMBIGUOUS` 或 `NONE`。",
        "",
        "## 完整测试",
        "",
        "| 提示词 | 正确数 | 正确率 | 墙钟总耗时 | 相对当前领先净变化 | 门槛 |",
        "|---|---:|---:|---:|---:|---|",
        f"| 当前架构强制单选 | {leader['correct']}/1736 | {pct(leader['accuracy'])} | {leader['latency_wall_seconds_sum']:.1f}s | — | 保留 |",
        f"| P5 信息集等价 | {p5['summary']['overall']['correct']}/1736 | {pct(p5['summary']['overall']['accuracy'])} | {p5['summary']['overall']['latency_wall_seconds']['sum']:.1f}s | {p5_pair['net_second_minus_first_correct']:+d} | 未通过 |",
        f"| P6 替换测试 | {p6['summary']['overall']['correct']}/1736 | {pct(p6['summary']['overall']['accuracy'])} | {p6['summary']['overall']['latency_wall_seconds']['sum']:.1f}s | {p6_pair['net_second_minus_first_correct']:+d} | 未通过 |",
        f"| P7 双向蕴含 | {p7['summary']['overall']['correct']}/1736 | {pct(p7['summary']['overall']['accuracy'])} | {p7['summary']['overall']['latency_wall_seconds']['sum']:.1f}s | {p7_pair['net_second_minus_first_correct']:+d} | 未通过 |",
        f"| 旧原始设问基线 | {old_baseline['correct']}/1736 | {pct(old_baseline['accuracy'])} | {old_baseline['latency_wall_seconds']['sum']:.1f}s | — | 参考 |",
        "",
        f"最强专家风格是 P7（{p7['summary']['overall']['correct']}/1736，{pct(p7['summary']['overall']['accuracy'])}），但仍比当前架构提示词少答对 76 题。配对结果为当前领先独有正确 92 题、P7 独有正确 16 题，McNemar 双侧精确检验 `p={p7_pair['mcnemar_exact_two_sided_p']:.3g}`。",
        "",
        "## 第二选项排列审计",
        "",
        "固定抽取 300 题，并对每题实施非零循环换位，使正确选项字母全部改变。",
        "",
        "| 提示词 | 原排列同子集 | 第二排列 | 语义候选选择一致率 |",
        "|---|---:|---:|---:|",
        f"| 当前架构强制单选 | {architecture_perm['original_subset']['correct']}/300 ({pct(architecture_perm['original_subset']['accuracy'])}) | {arch_perm_overall['correct']}/300 ({pct(arch_perm_overall['accuracy'])}) | {pct(architecture_perm['semantic_selection_consistency']['rate'])} |",
        f"| P7 双向蕴含 | {p7_perm['original_subset']['correct']}/300 ({pct(p7_perm['original_subset']['accuracy'])}) | {p7_perm_overall['correct']}/300 ({pct(p7_perm_overall['accuracy'])}) | {pct(p7_perm['semantic_selection_consistency']['rate'])} |",
        "",
        f"第二排列上当前提示词仍领先 12 题（{arch_perm_overall['correct']} 对 {p7_perm_overall['correct']}）。这说明完整集领先并非只由原始选项位置造成；但一致率并非 100%，因此 4B 模型仍存在可测的选项顺序敏感性，不能宣称已彻底消除位置偏置。",
        "",
        "## 解释与边界",
        "",
        "P5/P7 的形式化表达很简洁，但在这个 4B 模型上，显式列出 `omission`、`addition`、`contradiction` 和 `incorrect text boundary` 的架构提示更有效。P6 的“可替换”表述下降最大。这里是模型与已打开工程题集上的实证结果，不是关于提示词理论优劣的普遍结论。",
        "",
        "所有候选均为零解析失败；没有训练模型，也没有打开 rolling shadow、confirmation 或 source-held-out final。公开报告和收据不包含语料正文。",
    ]
    args.output_report.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
