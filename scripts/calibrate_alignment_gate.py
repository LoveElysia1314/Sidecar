#!/usr/bin/env python
"""Build the deterministic calibration artifact for the production MDL gate."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from dualign.common import load_text_lines
from dualign.config import get_embedding_cache_path
from dualign.algorithms.mdl import (
    compare_monotone_evidence,
    conformal_upper_p,
    mutual_rank_code_evidence,
    normalize_embeddings,
    symmetric_nearest_score,
)
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.embedding import _try_lazy_load_model
from dualign.services.embedding_cache import EmbeddingCache


def _block_order(size: int, mode: str) -> np.ndarray:
    """Return one of two declared four-block stress transformations."""

    boundaries = np.linspace(0, size, 5, dtype=int)
    blocks = [
        np.arange(boundaries[index], boundaries[index + 1], dtype=np.int32)
        for index in range(4)
    ]
    permutation = (0, 2, 1, 3) if mode == "middle_swap" else (3, 2, 1, 0)
    return np.concatenate([blocks[index] for index in permutation])


def _evaluate(scores: np.ndarray) -> dict:
    evidence = mutual_rank_code_evidence(scores)
    order = compare_monotone_evidence(evidence)
    return {
        "shape": list(scores.shape),
        "nearest_score": symmetric_nearest_score(scores),
        "order": {
            "order_free_evidence_bits": order.order_free_bits,
            "monotone_evidence_bits": order.monotone_bits,
            "monotone_evidence_loss": order.relative_loss,
            "order_free_pairs": len(order.order_free_pairs),
            "monotone_pairs": len(order.monotone_pairs),
        },
    }


def _status(
    item: dict,
    existence_null: np.ndarray,
    acceptable_monotone_losses: np.ndarray,
    alpha: float,
) -> tuple[bool, str, float, float]:
    existence_p = conformal_upper_p(item["nearest_score"], existence_null)
    order_p = conformal_upper_p(
        item["order"]["monotone_evidence_loss"],
        acceptable_monotone_losses,
    )
    if existence_p > alpha:
        accepted, reason = False, "no_correspondence"
    elif order_p <= alpha:
        accepted, reason = False, "order_incompatible"
    else:
        accepted, reason = True, ""
    return accepted, reason, existence_p, order_p


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument(
        "--reorder-cases",
        type=int,
        nargs="*",
        help="仅调试时限制块乱序案例；默认系统地测试全部校准文档",
    )
    parser.add_argument(
        "--acceptable-report",
        type=Path,
        action="append",
        default=[],
        help="加入经审阅仍可产生单调路径的困难正例报告；可重复指定",
    )
    args = parser.parse_args()
    if not 0.0 < args.alpha < 1.0:
        raise ValueError("alpha 必须位于 (0,1)")

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    model = _try_lazy_load_model()
    if model is None:
        raise RuntimeError("无法加载嵌入模型")

    documents = []
    with EmbeddingCache(get_embedding_cache_path()) as cache:
        encoder = CachedEncoder(model, cache)
        for case in audit["cases"]:
            report_path = Path(case["report"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report_documents = report.get("documents") or {}
            raw = report_path.parent.parent / "raw"
            lines_a = load_text_lines(raw / report_documents["a"]["path"])
            lines_b = load_text_lines(raw / report_documents["b"]["path"])
            documents.append(
                {
                    "case": case["number"],
                    "report": str(report_path),
                    "a": normalize_embeddings(encoder.encode(lines_a)),
                    "b": normalize_embeddings(encoder.encode(lines_b)),
                }
            )

        parallel = []
        nonparallel = []
        score_matrices = {}
        for index, document in enumerate(documents):
            scores = np.dot(document["a"], document["b"].T)
            score_matrices[document["case"]] = scores
            parallel.append(
                {
                    "kind": "parallel",
                    "case_a": document["case"],
                    "case_b": document["case"],
                    "report": document["report"],
                    **_evaluate(scores),
                }
            )

            # The cyclic derangement uses every document exactly once on both
            # sides, never pairs a document with itself, and has no random seed
            # or searched pairing. It is calibration, not a held-out estimate.
            other = documents[(index + 1) % len(documents)]
            mismatch_scores = np.dot(document["a"], other["b"].T)
            nonparallel.append(
                {
                    "kind": "nonparallel",
                    "case_a": document["case"],
                    "case_b": other["case"],
                    **_evaluate(mismatch_scores),
                }
            )

        existence_null = np.array(
            [item["nearest_score"] for item in nonparallel], dtype=np.float64
        )
        acceptable_hard = []
        for report_path in args.acceptable_report:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report_documents = report.get("documents") or {}
            raw = report_path.parent.parent / "raw"
            lines_a = load_text_lines(raw / report_documents["a"]["path"])
            lines_b = load_text_lines(raw / report_documents["b"]["path"])
            scores = np.dot(
                normalize_embeddings(encoder.encode(lines_a)),
                normalize_embeddings(encoder.encode(lines_b)).T,
            )
            acceptable_hard.append(
                {
                    "kind": "acceptable_hard",
                    "report": str(report_path),
                    **_evaluate(scores),
                }
            )
        acceptable_monotone_losses = np.asarray(
            [
                item["order"]["monotone_evidence_loss"]
                for item in [*parallel, *acceptable_hard]
            ],
            dtype=np.float64,
        )

        selected_cases = (
            set(args.reorder_cases)
            if args.reorder_cases is not None
            else {document["case"] for document in documents}
        )
        reordered = []
        for document in documents:
            case = document["case"]
            if case not in selected_cases:
                continue
            scores = score_matrices[case]
            original = next(item for item in parallel if item["case_a"] == case)
            for mode in ("middle_swap", "reverse_blocks"):
                order = _block_order(scores.shape[1], mode)
                item = {
                    "kind": "reordered",
                    "mode": mode,
                    "case_a": case,
                    "case_b": case,
                    **_evaluate(scores[:, order]),
                }
                # Reordering preserves the multiset behind this statistic.
                item["nearest_score"] = original["nearest_score"]
                reordered.append(item)

        groups = {
            "parallel": parallel,
            "acceptable_hard": acceptable_hard,
            "nonparallel": nonparallel,
            "reordered": reordered,
        }
        summary = {}
        for name, items in groups.items():
            statuses = Counter()
            rejection_reasons = Counter()
            for item in items:
                accepted, reason, existence_p, order_p = _status(
                    item,
                    existence_null,
                    acceptable_monotone_losses,
                    args.alpha,
                )
                status = "accepted" if accepted else "rejected"
                item["gate"] = {
                    "status": status,
                    "reason": reason or None,
                    "existence_p": existence_p,
                    "order_compatibility_p": order_p,
                }
                statuses[status] += 1
                if reason:
                    rejection_reasons[reason] += 1
            summary[name] = {
                "cases": len(items),
                "gate_counts": dict(sorted(statuses.items())),
                "rejection_reasons": dict(sorted(rejection_reasons.items())),
            }

        payload = {
            "experiment": "minimal deterministic alignment-gate calibration",
            "alpha": args.alpha,
            "null_pairing": "cyclic_next_derangement",
            "reorder_stress": "four equal blocks; middle swap and reverse",
            "calibration_resolution": 1.0 / (len(nonparallel) + 1),
            "order_model": {
                "family": "conformal_upper_tail",
                "acceptable_monotone_losses": acceptable_monotone_losses.tolist(),
            },
            **groups,
            "summary": summary,
            "cache": {
                "hits": encoder.hit_count,
                "misses": encoder.miss_count,
                "hit_rate": encoder.cache_hit_rate,
            },
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
