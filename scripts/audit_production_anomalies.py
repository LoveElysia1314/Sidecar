#!/usr/bin/env python
"""Inventory every production relation classified as anomalous by Dualign.

The scan is read-only.  Only reports whose document hashes still match the
current source files enter the evaluation corpus; stale and unresolved reports
are reported separately.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from dualign.common import load_text_lines
from dualign.core import detect_language_mix
from dualign.services.alignment_io import document_sha256
from dualign.services.anomaly_detection import is_statistical_low_score


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
            tuple(int(index) for index in operation.get("s") or ()),
            tuple(int(index) for index in operation.get("t") or ()),
            float(operation.get("sc") or 0.0),
        )
        for operation in report.get("ops", ())
    ]


def _text(lines: list[str], indices: tuple[int, ...]) -> list[str]:
    return [lines[index] for index in indices if 0 <= index < len(lines)]


def _anomaly_types(operation, scores_11, lines_b) -> list[str]:
    source, target, score = operation
    result = []
    if len(source) != 1 or len(target) != 1:
        result.append("NON_1TO1")
    if (
        len(source) == 1
        and len(target) == 1
        and is_statistical_low_score(score, scores_11)
    ):
        result.append("LOW_SCORE")
    if any(
        0 <= index < len(lines_b) and detect_language_mix(lines_b[index])
        for index in target
    ):
        result.append("MIX")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    documents = []
    stale = []
    unresolved = []
    scanned = 0
    anomaly_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()

    for report_path in sorted(args.data_root.rglob("*.report.json")):
        scanned += 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
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
        scores_11 = [
            score
            for source, target, score in operations
            if len(source) == 1 and len(target) == 1
        ]
        anomalies = []
        for position, operation in enumerate(operations):
            types = _anomaly_types(operation, scores_11, lines_b)
            if not types:
                continue
            source, target, score = operation
            anomaly_counts.update(types)
            relation = f"{len(source)}:{len(target)}"
            relation_counts[relation] += 1
            anomalies.append(
                {
                    "position": position,
                    "types": types,
                    "relation": relation,
                    "source_indices": source,
                    "target_indices": target,
                    "score": round(score, 6),
                    "document_a": _text(lines_a, source),
                    "document_b": _text(lines_b, target),
                }
            )
        if anomalies:
            documents.append(
                {
                    "report": str(report_path),
                    "document_a": str(paths[0]),
                    "document_b": str(paths[1]),
                    "line_counts": [len(lines_a), len(lines_b)],
                    "production_operations": len(operations),
                    "anomalies": anomalies,
                }
            )

    payload = {
        "data_root": str(args.data_root.resolve()),
        "definition": ["NON_1TO1", "LOW_SCORE", "MIX"],
        "summary": {
            "reports_scanned": scanned,
            "eligible_documents": len(documents),
            "anomalous_relations": sum(len(item["anomalies"]) for item in documents),
            "anomaly_type_counts": dict(sorted(anomaly_counts.items())),
            "relation_counts": dict(sorted(relation_counts.items())),
            "stale_reports": len(stale),
            "unresolved_reports": len(unresolved),
        },
        "documents": documents,
        "stale_reports": stale,
        "unresolved_reports": unresolved,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"result={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
