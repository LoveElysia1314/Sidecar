from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

from dualign.config import INSTRUCTION_TEXT
from dualign.services.embedding import OllamaEncoder


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_sources(sources: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in sources.items():
        if isinstance(value, dict):
            compact[key] = {
                item_key: item for item_key, item in value.items() if item_key != "path"
            }
        else:
            compact[key] = value
    return compact


def compact_model_receipt(item: dict[str, Any]) -> dict[str, Any]:
    details = item.get("details") or {}
    safe_detail_keys = (
        "context_length",
        "embedding_length",
        "families",
        "family",
        "format",
        "parameter_size",
        "quantization_level",
    )
    return {
        "name": item["name"],
        "digest": item.get("digest"),
        "size": item.get("size"),
        "details": {key: details[key] for key in safe_detail_keys if key in details},
    }


def ollama_model_receipt(endpoint: str, model: str) -> dict[str, Any]:
    response = requests.get(f"{endpoint.rstrip('/')}/api/tags", timeout=30)
    response.raise_for_status()
    matches = [
        item for item in response.json().get("models", []) if item.get("name") == model
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one installed Ollama model named {model!r}, found {len(matches)}"
        )
    return compact_model_receipt(matches[0])


def ollama_residency(endpoint: str, model: str) -> dict[str, Any]:
    response = requests.get(f"{endpoint.rstrip('/')}/api/ps", timeout=30)
    response.raise_for_status()
    matches = [
        item for item in response.json().get("models", []) if item.get("name") == model
    ]
    if len(matches) != 1:
        return {"resident": False}
    item = matches[0]
    size = int(item.get("size") or 0)
    size_vram = int(item.get("size_vram") or 0)
    return {
        "resident": True,
        "size": size,
        "size_vram": size_vram,
        "vram_fraction": size_vram / size if size else None,
        "fully_gpu_resident": bool(size and size_vram / size >= 0.95),
        "expires_at": item.get("expires_at"),
    }


def unique_text_items(cases: list[Any], hash_text=sha256_text) -> list[tuple[str, str]]:
    texts_by_hash: dict[str, str] = {}
    for case in cases:
        texts_by_hash.setdefault(hash_text(case.anchor), case.anchor)
        for candidate in case.candidates:
            texts_by_hash.setdefault(hash_text(candidate.text), candidate.text)
    return sorted(texts_by_hash.items())


def scores_from_embeddings(
    cases: list[Any], embeddings: dict[str, np.ndarray], hash_text=sha256_text
) -> dict[tuple[str, str, str], float]:
    scores: dict[tuple[str, str, str], float] = {}
    for case in cases:
        anchor = embeddings[hash_text(case.anchor)]
        for candidate in case.candidates:
            scores[(case.dataset, case.case_id, candidate.candidate_id)] = float(
                anchor @ embeddings[hash_text(candidate.text)]
            )
    return scores


def paired_overall(base: dict[str, Any], other: dict[str, Any]) -> dict[str, int]:
    base_rows = {(row["dataset"], row["case_id"]): row for row in base["cases"]}
    other_rows = {(row["dataset"], row["case_id"]): row for row in other["cases"]}
    if base_rows.keys() != other_rows.keys():
        raise ValueError("baseline and candidate case sets differ")
    result = {
        "both_correct": 0,
        "baseline_only_correct": 0,
        "candidate_only_correct": 0,
        "both_wrong": 0,
    }
    for key in base_rows:
        before = bool(base_rows[key]["positive_top1"])
        after = bool(other_rows[key]["positive_top1"])
        if before and after:
            result["both_correct"] += 1
        elif before:
            result["baseline_only_correct"] += 1
        elif after:
            result["candidate_only_correct"] += 1
        else:
            result["both_wrong"] += 1
    result["net_candidate_minus_baseline_correct"] = (
        result["candidate_only_correct"] - result["baseline_only_correct"]
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bakeoff-script", type=Path, required=True)
    parser.add_argument("--private-groups", required=True)
    parser.add_argument("--private-split", required=True)
    parser.add_argument("--natural-cases", required=True)
    parser.add_argument("--validation-development", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--instruction", default=INSTRUCTION_TEXT)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--baseline-result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    bakeoff = load_module(args.bakeoff_script.resolve(), "observer_bakeoff_for_ollama")
    cases, source_receipt = bakeoff.load_cases(args)
    model_receipt = ollama_model_receipt(args.endpoint, args.model)
    encoder = OllamaEncoder(
        args.model, base_url=args.endpoint, instruction=args.instruction
    )

    warmup_start = time.perf_counter()
    warmup = encoder.encode(["Parallel text embedding warm-up."], batch_size=1)
    warmup_seconds = time.perf_counter() - warmup_start
    if warmup.shape[0] != 1:
        raise RuntimeError("Ollama warm-up did not return exactly one embedding")

    text_items = unique_text_items(cases, bakeoff.sha256_text)
    encode_start = time.perf_counter()
    vectors = encoder.encode(
        [text for _, text in text_items], batch_size=args.batch_size
    )
    encode_seconds = time.perf_counter() - encode_start
    if vectors.shape[0] != len(text_items):
        raise RuntimeError("embedding count differs from unique text count")
    embeddings = {
        text_hash: vector
        for (text_hash, _), vector in zip(text_items, vectors, strict=True)
    }
    scores = scores_from_embeddings(cases, embeddings, bakeoff.sha256_text)
    rows = bakeoff.evaluate_scores(cases, scores)
    summary = bakeoff.summarize_evaluation(rows)
    residency = ollama_residency(args.endpoint, args.model)

    payload: dict[str, Any] = {
        "schema": "dualign-observer-ollama-embedding-arm/v1",
        "arm": "ollama_application_bilateral_instruction",
        "body_text_in_output": False,
        "created_at_unix": time.time(),
        "sources": compact_sources(source_receipt),
        "model": model_receipt,
        "instruction": args.instruction,
        "instruction_sha256": sha256_text(args.instruction),
        "instruction_applied_to": "both_anchor_and_candidate",
        "score_protocol": "ollama_embedding_l2_cosine_strict_positive_margin",
        "runtime": {
            "warmup_seconds": warmup_seconds,
            "encode_seconds": encode_seconds,
            "batch_size_requested": args.batch_size,
            "unique_texts": len(text_items),
            "pairs": len(scores),
            "embedding_dimension": int(vectors.shape[1]),
            "milliseconds_per_unique_text": encode_seconds * 1000 / len(text_items),
            "milliseconds_per_pair_amortized": encode_seconds * 1000 / len(scores),
            "pairs_per_second_amortized": len(scores) / encode_seconds,
            "ollama_residency": residency,
        },
        "software": {"python": platform.python_version(), "numpy": np.__version__},
        "summary": summary,
        "cases": rows,
    }
    paired = None
    if args.baseline_result:
        baseline = json.loads(args.baseline_result.read_text(encoding="utf-8"))
        paired = {
            "baseline_model": compact_model_receipt(baseline["model"]),
            "overall": paired_overall(baseline, payload),
            "by_dataset": bakeoff.paired_flips(baseline, payload),
        }
        payload["paired_vs_baseline"] = paired

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bakeoff.write_json(args.output, payload)
    receipt = {
        "schema": "dualign-observer-ollama-embedding-receipt/v1",
        "body_text_in_output": False,
        "scientific_scope": "opened_engineering_suite_not_fresh_validation",
        "model": model_receipt,
        "instruction": args.instruction,
        "instruction_sha256": sha256_text(args.instruction),
        "instruction_applied_to": "both_anchor_and_candidate",
        "score_protocol": payload["score_protocol"],
        "sources": payload["sources"],
        "runtime": payload["runtime"],
        "summary": summary,
        "paired_vs_baseline": paired,
        "private_result": {
            "bytes": args.output.stat().st_size,
            "sha256": sha256_file(args.output),
        },
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    bakeoff.write_json(args.receipt, receipt)
    print(
        json.dumps(
            {
                "model": args.model,
                "instruction_sha256": receipt["instruction_sha256"],
                "overall": summary["overall"],
                "runtime": payload["runtime"],
                "paired_vs_baseline": paired,
                "output": str(args.output),
                "receipt": str(args.receipt),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
