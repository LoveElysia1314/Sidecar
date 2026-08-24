#!/usr/bin/env python
"""Evaluate the production MDL pipeline on every legacy-anomaly document."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from dualign.common import load_text_lines
from dualign.config import get_embedding_cache_path
from dualign.algorithms.mdl import (
    AlignmentCalibration,
    align_mdl_pipeline,
)
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.embedding import _try_lazy_load_model
from dualign.services.embedding_cache import EmbeddingCache


def _operations(report: dict):
    return [
        (
            tuple(int(index) for index in operation.get("s") or ()),
            tuple(int(index) for index in operation.get("t") or ()),
            float(operation.get("sc") or 0.0),
        )
        for operation in report.get("ops", ())
    ]


def _signature(operations):
    return tuple((tuple(source), tuple(target)) for source, target, _score in operations)


def _serialize(operations, lines_a, lines_b):
    return [
        {
            "s": source,
            "t": target,
            "relation": f"{len(source)}:{len(target)}",
            "score": round(float(score), 6),
            "a": [lines_a[index] for index in source],
            "b": [lines_b[index] for index in target],
        }
        for source, target, score in operations
    ]


def _path_edges(operations):
    cursor = (0, 0)
    edges = []
    for position, operation in enumerate(operations):
        source, target, _score = operation
        end = (cursor[0] + len(source), cursor[1] + len(target))
        edges.append((cursor, end, position, operation))
        cursor = end
    return edges, cursor


def _difference_islands(old_operations, new_operations, lines_a, lines_b):
    old_edges, old_end = _path_edges(old_operations)
    new_edges, new_end = _path_edges(new_operations)
    if old_end != new_end:
        raise ValueError(f"新旧路径覆盖终点不一致: {old_end} != {new_end}")
    old_vertices = {old_edges[0][0] if old_edges else (0, 0), old_end}
    new_vertices = {new_edges[0][0] if new_edges else (0, 0), new_end}
    old_vertices.update(edge[1] for edge in old_edges)
    new_vertices.update(edge[1] for edge in new_edges)
    common = sorted(old_vertices & new_vertices, key=lambda item: (item[0] + item[1], item[0]))
    islands = []
    for start, end in zip(common, common[1:]):
        old_segment = [
            edge
            for edge in old_edges
            if edge[0][0] >= start[0]
            and edge[0][1] >= start[1]
            and edge[1][0] <= end[0]
            and edge[1][1] <= end[1]
        ]
        new_segment = [
            edge
            for edge in new_edges
            if edge[0][0] >= start[0]
            and edge[0][1] >= start[1]
            and edge[1][0] <= end[0]
            and edge[1][1] <= end[1]
        ]
        old_ops = [edge[3] for edge in old_segment]
        new_ops = [edge[3] for edge in new_segment]
        if _signature(old_ops) == _signature(new_ops):
            continue
        islands.append(
            {
                "number": len(islands) + 1,
                "start": start,
                "end": end,
                "old_positions": [edge[2] for edge in old_segment],
                "production": _serialize(old_ops, lines_a, lines_b),
                "mdl": _serialize(new_ops, lines_a, lines_b),
            }
        )
    return islands


def _operation_counts(operations):
    return dict(
        sorted(
            Counter(f"{len(source)}:{len(target)}" for source, target, _ in operations).items()
        )
    )


def _gate_payload(gate):
    return {
        "status": gate.status,
        "existence_score": round(gate.existence_score, 6),
        "existence_p": gate.existence_p,
        "order_coverage": gate.order.coverage,
        "order_compatibility_p": gate.order_compatibility_p,
        "mutual_pairs": gate.order.mutual_pairs,
        "chain_length": gate.order.chain_length,
        "kendall_tau": gate.order.kendall_tau,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--numbers", type=int, nargs="*")
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    calibration_artifact = json.loads(args.calibration.read_text(encoding="utf-8"))
    existence_null = np.array(
        [item["nearest_score"] for item in calibration_artifact["nonparallel"]],
        dtype=np.float64,
    )
    order_counts = np.array(
        [
            [
                item["order"]["mutual_pairs"] - item["order"]["chain_length"],
                item["order"]["mutual_pairs"],
            ]
            for item in calibration_artifact["parallel"]
        ],
        dtype=np.int32,
    )
    documents = list(enumerate(inventory["documents"], 1))
    if args.numbers:
        selected_numbers = set(args.numbers)
        documents = [item for item in documents if item[0] in selected_numbers]
    if args.limit is not None:
        documents = documents[: args.limit]

    model = _try_lazy_load_model()
    if model is None:
        raise RuntimeError("无法加载嵌入模型")

    results = []
    gate_counts: Counter[str] = Counter()
    changed_anomalies = 0
    total_islands = 0
    with EmbeddingCache(get_embedding_cache_path()) as cache:
        encoder = CachedEncoder(model, cache)
        for sequence, (document_number, document) in enumerate(documents, 1):
            report_path = Path(document["report"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            lines_a = load_text_lines(document["document_a"])
            lines_b = load_text_lines(document["document_b"])
            old_operations = _operations(report)
            before_hits, before_misses = encoder.hit_count, encoder.miss_count
            calibration = AlignmentCalibration(
                existence_null=existence_null,
                parallel_order_counts=order_counts,
                alpha=args.alpha,
            )
            result = align_mdl_pipeline(
                lines_a,
                lines_b,
                encoder.encode(lines_a),
                encoder.encode(lines_b),
                encoder.encode,
                calibration,
            )
            gate_counts[result.gate.status] += 1
            exact_new = {
                (tuple(source), tuple(target))
                for source, target, _score in result.all_ops
            }
            anomaly_reviews = []
            for anomaly in document["anomalies"]:
                relation = (
                    tuple(anomaly["source_indices"]),
                    tuple(anomaly["target_indices"]),
                )
                if not result.gate.accepted:
                    comparison = "document_rejected"
                elif relation in exact_new:
                    comparison = "preserved_exactly"
                else:
                    comparison = "realigned"
                    changed_anomalies += 1
                anomaly_reviews.append({**anomaly, "comparison": comparison})

            if result.gate.accepted:
                islands = _difference_islands(
                    old_operations, result.all_ops, lines_a, lines_b
                )
                composition_islands = _difference_islands(
                    result.atomic_ops, result.all_ops, lines_a, lines_b
                )
                alternative_islands = _difference_islands(
                    result.all_ops, result.alternative_ops, lines_a, lines_b
                )
                total_islands += len(islands)
                atomic_changed = _signature(old_operations) != _signature(result.atomic_ops)
                final_changed = _signature(old_operations) != _signature(result.all_ops)
                atomic_vs_final = _signature(result.atomic_ops) != _signature(result.all_ops)
            else:
                islands = []
                composition_islands = []
                alternative_islands = []
                atomic_changed = final_changed = atomic_vs_final = False

            results.append(
                {
                    "number": document_number,
                    "report": str(report_path),
                    "document_a": document["document_a"],
                    "document_b": document["document_b"],
                    "line_counts": document["line_counts"],
                    "gate": _gate_payload(result.gate),
                    "result_status": result.status,
                    "production_counts": _operation_counts(old_operations),
                    "mdl_counts": _operation_counts(result.all_ops),
                    "atomic_changed": atomic_changed,
                    "final_changed": final_changed,
                    "composition_changed_atomic": atomic_vs_final,
                    "scaffold_pairs": len(result.scaffold),
                    "candidate_edges": (
                        result.centered.composition_stats["candidate_edges"]
                        if result.centered
                        else 0
                    ),
                    "composition_candidates": (
                        result.composition.composition_candidates
                        if result.composition
                        else 0
                    ),
                    "composition_texts": (
                        result.composition.encoded_texts if result.composition else 0
                    ),
                    "composition_diagnostics": (
                        result.composition.diagnostics if result.composition else ()
                    ),
                    "composition_solver": (
                        result.composition.alignment.solver_stats
                        if result.composition
                        else {}
                    ),
                    "alternative_composition_diagnostics": (
                        result.alternative_composition.diagnostics
                        if result.alternative_composition
                        else ()
                    ),
                    "uncertain_regions": result.uncertain_regions,
                    "timing": result.stats,
                    "cache": {
                        "hits": encoder.hit_count - before_hits,
                        "misses": encoder.miss_count - before_misses,
                    },
                    "anomaly_reviews": anomaly_reviews,
                    "difference_islands": islands,
                    "composition_difference_islands": composition_islands,
                    "composition_model_difference_islands": alternative_islands,
                }
            )
            print(
                f"[{sequence}/{len(documents)}] {report_path.name} "
                f"gate={result.gate.status} result={result.status} islands={len(islands)} "
                f"composition={result.composition.encoded_texts if result.composition else 0}",
                flush=True,
            )

    payload = {
        "algorithm": "converged gated unified-gap-quotient composition MDL",
        "inventory": str(args.inventory),
        "calibration": str(args.calibration),
        "alpha": args.alpha,
        "summary": {
            "documents": len(results),
            "production_anomalies": sum(
                len(item["anomaly_reviews"]) for item in results
            ),
            "gate_counts": dict(sorted(gate_counts.items())),
            "changed_documents": sum(item["final_changed"] for item in results),
            "changed_anomalies": changed_anomalies,
            "difference_islands": total_islands,
            "composition_changed_documents": sum(
                item["composition_changed_atomic"] for item in results
            ),
            "composition_texts": sum(item["composition_texts"] for item in results),
            "cache_hits": encoder.hit_count,
            "cache_misses": encoder.miss_count,
        },
        "documents": results,
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
