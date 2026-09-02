"""Build a private 300-case second-permutation observer audit packet."""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

SEED = "dualign-observer-second-permutation-audit/v1"


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("observer_mcq_for_permutation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MCQ module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def hash_key(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        f"{SEED}|select|{row['dataset']}|{row['case_id']}".encode()
    ).hexdigest()


def take(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=hash_key)
    if len(ordered) < count:
        raise ValueError(f"stratum has {len(ordered)} rows but needs {count}")
    return ordered[:count]


def select_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [row for row in rows if row["dataset"] == "internal_v1_k3"]
    natural = [row for row in rows if row["dataset"] == "internal_reader_natural"]
    natural_strata: dict[tuple[str, str], list[dict[str, Any]]] = (
        collections.defaultdict(list)
    )
    for row in natural:
        natural_strata[(row["direction"], row["family"])].append(row)
    if len(natural_strata) != 4:
        raise ValueError(f"expected four natural strata, got {sorted(natural_strata)}")
    for values in natural_strata.values():
        selected.extend(take(values, 20))
    validation = [row for row in rows if row["dataset"] == "validation_v4_development"]
    validation_families: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in validation:
        validation_families[row["family"]].append(row)
    if len(validation_families) != 10:
        raise ValueError(
            f"expected ten validation families, got {len(validation_families)}"
        )
    for values in validation_families.values():
        selected.extend(take(values, 18))
    if len(selected) != 300:
        raise ValueError(f"expected 300 selected cases, got {len(selected)}")
    return sorted(selected, key=hash_key)


def permute_question(module: Any, row: dict[str, Any]) -> dict[str, Any]:
    options = [dict(option) for option in row["options"]]
    n = len(options)
    digest = hashlib.sha256(
        f"{SEED}|rotate|{row['dataset']}|{row['case_id']}".encode()
    ).digest()
    shift = 1 + int.from_bytes(digest[:4], "big") % (n - 1)
    rotated = options[shift:] + options[:shift]
    for index, option in enumerate(rotated):
        option["letter"] = module.LETTERS[index]
    exact = [option for option in rotated if option["exact"]]
    if len(exact) != 1:
        raise ValueError("permuted question does not have one exact answer")
    lines = ["Reference:", row["anchor"], "", "Candidates:"]
    for option in rotated:
        lines.extend([f"{option['letter']}.", option["text"], ""])
    valid_letters = [option["letter"] for option in rotated]
    lines.append(f"Return only the best option letter ({' / '.join(valid_letters)}).")
    prompt = "\n".join(lines)
    output = dict(row)
    output.update(
        {
            "schema": "dualign-private-mcq-permutation-audit/v1",
            "permutation_seed": SEED,
            "permutation_shift": shift,
            "original_answer_letter": row["answer_letter"],
            "original_user_prompt_sha256": row["user_prompt_sha256"],
            "options": rotated,
            "valid_letters": valid_letters,
            "answer_letter": exact[0]["letter"],
            "user_prompt": prompt,
            "user_prompt_sha256": module.sha256_text(prompt),
        }
    )
    if output["answer_letter"] == output["original_answer_letter"]:
        raise ValueError("second permutation did not move the gold position")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcq-script", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--private-output", required=True)
    parser.add_argument("--public-output", required=True)
    args = parser.parse_args()
    module = load_module(Path(args.mcq_script).resolve())
    source = Path(args.questions).resolve()
    rows = module.read_jsonl(source)
    selected = select_cases(rows)
    permuted = [permute_question(module, row) for row in selected]
    private_output = Path(args.private_output).resolve()
    module.write_jsonl(private_output, permuted)
    manifest = {
        "schema": "dualign-observer-permutation-audit-manifest/v1",
        "created_at_unix": time.time(),
        "body_text_in_output": False,
        "selection_seed": SEED,
        "source": {
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": module.sha256_file(source),
        },
        "private_packet": {
            "path": str(private_output),
            "bytes": private_output.stat().st_size,
            "sha256": module.sha256_file(private_output),
        },
        "counts": {
            "total": len(permuted),
            "by_dataset": dict(
                sorted(collections.Counter(row["dataset"] for row in permuted).items())
            ),
            "by_candidate_count": dict(
                sorted(
                    collections.Counter(len(row["options"]) for row in permuted).items()
                )
            ),
            "original_gold_position": dict(
                sorted(
                    collections.Counter(
                        row["original_answer_letter"] for row in permuted
                    ).items()
                )
            ),
            "permuted_gold_position": dict(
                sorted(
                    collections.Counter(
                        row["answer_letter"] for row in permuted
                    ).items()
                )
            ),
        },
        "rows": [
            {
                **module.public_question(row),
                "permutation_seed": row["permutation_seed"],
                "permutation_shift": row["permutation_shift"],
                "original_answer_letter": row["original_answer_letter"],
                "original_user_prompt_sha256": row["original_user_prompt_sha256"],
            }
            for row in permuted
        ],
    }
    module.write_json(Path(args.public_output).resolve(), manifest)
    print(
        json.dumps(
            {
                "private": str(private_output),
                "public": str(Path(args.public_output).resolve()),
                "counts": manifest["counts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
