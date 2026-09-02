from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Iterable

DIRECTIONS = ("en-zh", "zh-en")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pre(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    questions = read_jsonl(args.questions)
    answers = read_jsonl(args.answers)
    question_by_id = {row["case_id"]: row for row in questions}
    answer_by_id = {row["case_id"]: row for row in answers}
    if question_by_id.keys() != answer_by_id.keys():
        raise ValueError("question and answer case IDs differ")

    selected: list[dict[str, Any]] = []
    direction_totals: dict[str, dict[str, int | float]] = {}
    for direction in DIRECTIONS:
        direction_answers = [row for row in answers if row["direction"] == direction]
        wrong = [row for row in direction_answers if not row["correct"]]
        direction_totals[direction] = {
            "questions": len(direction_answers),
            "wrong": len(wrong),
            "correct": len(direction_answers) - len(wrong),
            "accuracy": (len(direction_answers) - len(wrong)) / len(direction_answers),
        }
        for answer in wrong:
            question = question_by_id[answer["case_id"]]
            selected.append(
                {
                    "schema": "dualign-observer-direction-error/v1",
                    "case_id": answer["case_id"],
                    "dataset": answer["dataset"],
                    "role": answer["role"],
                    "direction": answer["direction"],
                    "family": answer["family"],
                    "candidate_count": answer["candidate_count"],
                    "anchor": question["anchor"],
                    "anchor_sha256": question["anchor_sha256"],
                    "options": question["options"],
                    "gold_letter": answer["answer_letter"],
                    "predicted_letter": answer["predicted_letter"],
                    "model": answer["model"],
                    "prompt_kind": "architecture_forced_choice",
                }
            )
    selected.sort(
        key=lambda row: (
            DIRECTIONS.index(row["direction"]),
            row["dataset"],
            row["family"],
            row["case_id"],
        )
    )
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_jsonl, selected)

    family_counts = collections.Counter(row["family"] for row in selected)
    dataset_counts = collections.Counter(row["dataset"] for row in selected)
    combined_questions = sum(int(row["questions"]) for row in direction_totals.values())
    combined_wrong = len(selected)
    lines = [
        "# qwen3.5:4b 最优提示词中英错误集",
        "",
        "> 私有人工审阅材料：包含语料正文，不得提交到公开仓库。每题答案默认折叠，可先盲选后展开。",
        "",
        "## 概览",
        "",
        f"- 筛选方向：`en-zh`、`zh-en`",
        f"- 题目总数：{combined_questions}",
        f"- 错题：{combined_wrong}",
        f"- 合并正确率：{100 * (combined_questions - combined_wrong) / combined_questions:.2f}%",
        f"- 合并错误率：{100 * combined_wrong / combined_questions:.2f}%",
        f"- 问题包 SHA-256：`{sha256_file(args.questions)}`",
        f"- 回答文件 SHA-256：`{sha256_file(args.answers)}`",
        "",
        "| 方向 | 总题数 | 错题 | 正确率 |",
        "|---|---:|---:|---:|",
    ]
    for direction in DIRECTIONS:
        stats = direction_totals[direction]
        lines.append(
            f"| {direction} | {stats['questions']} | {stats['wrong']} | {100 * float(stats['accuracy']):.2f}% |"
        )
    lines.extend(
        [
            "",
            "按来源："
            + "；".join(
                f"`{key}` {value}题" for key, value in sorted(dataset_counts.items())
            ),
            "",
            "按错误族：",
            "",
        ]
    )
    for family, count in family_counts.most_common():
        lines.append(f"- `{family}`：{count}题")

    serial = 0
    for direction in DIRECTIONS:
        direction_rows = [row for row in selected if row["direction"] == direction]
        lines.extend(["", f"## {direction}（{len(direction_rows)}题）", ""])
        for row in direction_rows:
            serial += 1
            lines.extend(
                [
                    f"### {serial:02d}. `{row['case_id']}`",
                    "",
                    f"来源：`{row['dataset']}`　错误族：`{row['family']}`　候选数：{row['candidate_count']}",
                    "",
                    "**参考文本**",
                    "",
                    pre(row["anchor"]),
                    "",
                ]
            )
            for option in row["options"]:
                lines.extend(
                    [f"**选项 {option['letter']}**", "", pre(option["text"]), ""]
                )
            gold_option = next(
                option
                for option in row["options"]
                if option["letter"] == row["gold_letter"]
            )
            predicted_option = next(
                option
                for option in row["options"]
                if option["letter"] == row["predicted_letter"]
            )
            lines.extend(
                [
                    "<details>",
                    "<summary>展开答案</summary>",
                    "",
                    f"- 模型选择：**{row['predicted_letter']}**（`{predicted_option['candidate_id']}`）",
                    f"- 标准答案：**{row['gold_letter']}**（`{gold_option['candidate_id']}`）",
                    "",
                    "</details>",
                    "",
                    "---",
                    "",
                ]
            )
    args.output_markdown.write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )

    print(
        json.dumps(
            {
                "questions": combined_questions,
                "errors": combined_wrong,
                "direction_totals": direction_totals,
                "output_jsonl": str(args.output_jsonl),
                "output_markdown": str(args.output_markdown),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
