#!/usr/bin/env python
"""Benchmark production MDL or frozen legacy on cached real document pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from dualign.algorithms.mdl import align_mdl_pipeline
from dualign.common import load_text_lines
from dualign.config import get_embedding_cache_path
from dualign.core.legacy_anchor_aligner import align as align_legacy_anchor
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.embedding import _try_lazy_load_model
from dualign.services.embedding_cache import EmbeddingCache


def _path_digest(operations) -> str:
    payload = [[list(source), list(target)] for source, target, _score in operations]
    canonical = json.dumps(payload, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(".artifacts/production-anomaly-inventory.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--numbers", type=int, nargs="*")
    parser.add_argument(
        "--algorithm",
        choices=("mdl-v1", "legacy-anchor-v1"),
        default="mdl-v1",
    )
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    documents = list(enumerate(inventory["documents"], 1))
    if args.numbers:
        selected = set(args.numbers)
        documents = [item for item in documents if item[0] in selected]
    if args.limit is not None:
        documents = documents[: args.limit]

    model = _try_lazy_load_model()
    if model is None:
        raise RuntimeError("无法加载嵌入模型")
    results = []
    started = time.perf_counter()
    with EmbeddingCache(get_embedding_cache_path()) as cache:
        encoder = CachedEncoder(model, cache)
        for number, document in documents:
            lines_a = load_text_lines(document["document_a"])
            lines_b = load_text_lines(document["document_b"])
            vectors_a = encoder.encode(lines_a)
            vectors_b = encoder.encode(lines_b)
            solve_started = time.perf_counter()
            if args.algorithm == "mdl-v1":
                result = align_mdl_pipeline(
                    lines_a,
                    lines_b,
                    vectors_a,
                    vectors_b,
                    encoder.encode,
                )
                status = result.status
                alternative_digest = _path_digest(result.alternative_ops)
            else:
                result = align_legacy_anchor(
                    lines_a,
                    lines_b,
                    vectors_a,
                    vectors_b,
                    encode_fn=encoder.encode,
                    silent=True,
                )
                status = "legacy"
                alternative_digest = ""
            seconds = time.perf_counter() - solve_started
            results.append(
                {
                    "number": number,
                    "line_counts": [len(lines_a), len(lines_b)],
                    "status": status,
                    "path_sha256": _path_digest(result.all_ops),
                    "alternative_path_sha256": alternative_digest,
                    "seconds": seconds,
                    "stats": result.stats,
                }
            )
    timings = [item["seconds"] for item in results]
    output = {
        "algorithm": args.algorithm,
        "documents": len(results),
        "wall_seconds": time.perf_counter() - started,
        "solver_seconds": sum(timings),
        "median_seconds": statistics.median(timings) if timings else 0.0,
        "p95_seconds": (
            sorted(timings)[max(0, round(0.95 * len(timings)) - 1)] if timings else 0.0
        ),
        "results": results,
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
