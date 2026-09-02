from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).parents[1] / "tools" / "run_observer_ollama_embedding.py"
SPEC = importlib.util.spec_from_file_location("observer_ollama_embedding", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    text: str


@dataclass(frozen=True)
class Case:
    dataset: str
    case_id: str
    anchor: str
    candidates: tuple[Candidate, ...]


def test_production_instruction_is_bilateral_parallel_instruction() -> None:
    assert (
        MODULE.INSTRUCTION_TEXT
        == "Instruct: Identify parallel sentences across languages\nQuery: "
    )


def test_unique_texts_and_cosine_scores_use_shared_embeddings() -> None:
    case = Case(
        "d",
        "c",
        "anchor",
        (Candidate("good", "candidate"), Candidate("same", "anchor")),
    )
    items = MODULE.unique_text_items([case])
    assert len(items) == 2
    embeddings = {
        MODULE.sha256_text("anchor"): np.array([1.0, 0.0], dtype=np.float32),
        MODULE.sha256_text("candidate"): np.array([0.5, 0.5], dtype=np.float32),
    }
    scores = MODULE.scores_from_embeddings([case], embeddings)
    assert scores[("d", "c", "same")] == 1.0
    assert scores[("d", "c", "good")] == 0.5


def test_compact_sources_removes_only_paths() -> None:
    compact = MODULE.compact_sources(
        {"source": {"path": "local", "sha256": "abc"}, "total": 1}
    )
    assert compact == {"source": {"sha256": "abc"}, "total": 1}


def test_model_receipt_uses_safe_detail_allowlist(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "models": [
                    {
                        "name": "embedding:4b",
                        "digest": "abc",
                        "size": 42,
                        "details": {
                            "parameter_size": "4B",
                            "quantization_level": "Q4_K_M",
                            "embedding_length": 2560,
                            "parent_model": "/private/local/model/blob",
                        },
                    }
                ]
            }

    monkeypatch.setattr(MODULE.requests, "get", lambda *args, **kwargs: Response())
    receipt = MODULE.ollama_model_receipt("http://localhost:11434", "embedding:4b")
    assert receipt["details"] == {
        "embedding_length": 2560,
        "parameter_size": "4B",
        "quantization_level": "Q4_K_M",
    }
    assert "parent_model" not in receipt["details"]
