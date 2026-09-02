from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).parents[1]
REPO_ROOT = Path(__file__).parents[3]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_canonical_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_tracked_migration_hashes_match() -> None:
    manifest = json.loads(
        (EXPERIMENT_ROOT / "MIGRATION.json").read_text(encoding="utf-8")
    )
    for row in manifest["tracked_imports"]:
        path = REPO_ROOT / row["destination"]
        assert path.is_file(), row["destination"]
        assert sha256_canonical_text(path) == row.get(
            "destination_sha256", row.get("sha256")
        )
    for row in manifest["derived_tracked_files"]:
        path = REPO_ROOT / row["destination"]
        assert path.is_file(), row["destination"]
        assert sha256_canonical_text(path) == row["sha256"]


def test_private_migration_hashes_match_when_present() -> None:
    manifest = json.loads(
        (EXPERIMENT_ROOT / "MIGRATION.json").read_text(encoding="utf-8")
    )
    present = 0
    for row in manifest["private_imports"]:
        path = REPO_ROOT / row["destination"]
        if not path.exists():
            continue
        present += 1
        assert sha256_file(path) == row["sha256"]
    assert present in {0, len(manifest["private_imports"])}


def test_tracked_experiment_files_have_no_machine_local_windows_paths() -> None:
    pattern = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:\\")
    offenders = []
    for path in (REPO_ROOT / "experiments").rglob("*"):
        if (
            not path.is_file()
            or "private" in path.parts
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []


def test_private_tree_is_explicitly_ignored() -> None:
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/experiments/alignment-judge/private/*" in ignore
    assert "!/experiments/alignment-judge/private/README.md" in ignore


def test_frozen_question_and_final_prompt_receipts_are_coherent() -> None:
    datasets = json.loads(
        (EXPERIMENT_ROOT / "evidence" / "DATASET-INDEX.json").read_text(
            encoding="utf-8"
        )
    )
    summary = json.loads(
        (
            EXPERIMENT_ROOT / "evidence" / "OBSERVER-EXPERT-PROMPT-STYLES-SUMMARY.json"
        ).read_text(encoding="utf-8")
    )
    assert datasets["mcq"]["question_count"] == 1736
    assert summary["decision"]["selected"] == "architecture_forced_choice"
    assert summary["candidates"][0]["correct"] == 1667
    prompt = summary["decision"]["system_prompt"]
    assert "only the best option letter" in prompt
    assert "AMBIGUOUS" not in prompt
    assert "`NONE`" not in prompt
