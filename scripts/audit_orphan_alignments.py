#!/usr/bin/env python
"""Inventory persisted reports containing deletions or orphan relations.

This command is read-only and algorithm-neutral. It writes affected reports,
document paths, and production neighbourhoods for later alignment experiments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dualign.common import load_text_lines
from dualign.services.alignment_io import document_sha256


def _affected(report: dict) -> bool:
    has_orphan = any(not op.get("s") or not op.get("t") for op in report.get("ops", ()))
    has_delete = any(
        action.get("kind") == "delete" for action in report.get("repair_log", ())
    )
    return has_orphan or has_delete


def _document_paths(report_path: Path, report: dict) -> tuple[Path, Path] | None:
    documents = report.get("documents") or {}
    names = (
        (documents.get("a") or {}).get("path"),
        (documents.get("b") or {}).get("path"),
    )
    if not all(names):
        chapter_id = str(report.get("chapter_id") or report_path.name.split(".")[0])
        legacy = (
            report_path.parent / f"{chapter_id}.source.md",
            report_path.parent / f"{chapter_id}.target.md",
        )
        return legacy if all(path.is_file() for path in legacy) else None
    for directory in (
        report_path.parent,
        report_path.parent.parent / "raw",
        report_path.parent.parent,
    ):
        paths = tuple(directory / str(name) for name in names)
        if all(path.is_file() for path in paths):
            return paths  # type: ignore[return-value]
    return None


def _matches_snapshot(report: dict, path_a: Path, path_b: Path) -> bool:
    documents = report.get("documents") or {}
    expected_a = (documents.get("a") or {}).get("sha256") or report.get("src_hash")
    expected_b = (documents.get("b") or {}).get("sha256") or report.get("tgt_hash")
    return bool(
        expected_a
        and expected_b
        and expected_a == document_sha256(path_a)
        and expected_b == document_sha256(path_b)
    )


def _operations(report: dict):
    return [
        (
            tuple(operation.get("s") or ()),
            tuple(operation.get("t") or ()),
            float(operation.get("sc") or 0.0),
        )
        for operation in report.get("ops", ())
    ]


def _text(lines: list[str], indices: tuple[int, ...]) -> list[str]:
    return [lines[index] for index in indices if 0 <= index < len(lines)]


def _neighbourhood(operations, position: int, lines_a, lines_b, radius: int):
    result = []
    for index in range(
        max(0, position - radius), min(len(operations), position + radius + 1)
    ):
        source, target, score = operations[index]
        result.append(
            {
                "position": index,
                "relation": f"{len(source)}:{len(target)}",
                "source_indices": source,
                "target_indices": target,
                "score": round(score, 6),
                "document_a": _text(lines_a, source),
                "document_b": _text(lines_b, target),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--radius", type=int, default=1)
    args = parser.parse_args()

    documents = []
    unresolved = []
    stale = []
    for report_path in args.data_root.rglob("*.report.json"):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not _affected(report):
            continue
        paths = _document_paths(report_path, report)
        if paths is None:
            unresolved.append(str(report_path))
            continue
        if not _matches_snapshot(report, *paths):
            stale.append(str(report_path))
            continue
        lines_a = load_text_lines(paths[0])
        lines_b = load_text_lines(paths[1])
        operations = _operations(report)
        orphan_positions = [
            index
            for index, (source, target, _score) in enumerate(operations)
            if not source or not target
        ]
        documents.append(
            {
                "report": str(report_path),
                "document_a": str(paths[0]),
                "document_b": str(paths[1]),
                "line_counts": [len(lines_a), len(lines_b)],
                "delete_actions": [
                    action
                    for action in report.get("repair_log", ())
                    if action.get("kind") == "delete"
                ],
                "production_orphans": len(orphan_positions),
                "orphan_neighbourhoods": [
                    _neighbourhood(
                        operations,
                        position,
                        lines_a,
                        lines_b,
                        args.radius,
                    )
                    for position in orphan_positions
                ],
            }
        )

    payload = {
        "data_root": str(args.data_root.resolve()),
        "documents": documents,
        "unresolved_reports": unresolved,
        "stale_reports": stale,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"documents={len(documents)}")
    print(f"result={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
