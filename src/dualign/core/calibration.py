"""Versioned empirical calibration bound to an embedding identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files

import numpy as np


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model: str
    instruction_sha256: str


@dataclass(frozen=True)
class ResolvedCalibration:
    calibration_id: str
    status: str
    calibration: object
    metadata: dict


def embedding_identity(model=None) -> EmbeddingIdentity:
    """Resolve only fields that can change the embedding coordinate system."""

    provider = ""
    model_name = str(getattr(model, "_model", "") or "")
    instruction = str(getattr(model, "_instruction", "") or "")
    try:
        from dualign.providers import ProviderManager

        ProviderManager.load()
        active = ProviderManager.active()
        if active is not None:
            provider = str(active.provider_id)
            model_name = model_name or str(active.model_name)
            instruction = instruction or str(active.instruction_text or "")
            if not instruction and provider == "ollama":
                from dualign.config import INSTRUCTION_TEXT

                instruction = INSTRUCTION_TEXT
    except (OSError, ValueError):
        pass
    digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    return EmbeddingIdentity(provider, model_name, digest)


def _load_resources() -> list[dict]:
    resource = files("dualign.resources").joinpath(
        "alignment_calibration_harrier_0_6b_v2.json"
    )
    return [json.loads(resource.read_text(encoding="utf-8"))]


def resolve_alignment_calibration(
    model=None, *, calibration_id: str = ""
) -> ResolvedCalibration | None:
    """Return an exact identity match; never guess or cross-model fallback."""

    identity = embedding_identity(model)
    matches = []
    for metadata in _load_resources():
        if calibration_id and metadata["id"] != calibration_id:
            continue
        if (
            metadata["provider"] == identity.provider
            and metadata["model"] == identity.model
            and metadata["instruction_sha256"] == identity.instruction_sha256
        ):
            matches.append(metadata)
    if len(matches) != 1:
        return None
    metadata = matches[0]
    from dualign.algorithms.mdl import AlignmentCalibration

    calibration = AlignmentCalibration(
        existence_null=np.asarray(metadata["existence_null"], dtype=np.float64),
        acceptable_monotone_losses=np.asarray(
            metadata["acceptable_monotone_losses"], dtype=np.float64
        ),
        alpha=float(metadata["alpha"]),
    )
    return ResolvedCalibration(
        calibration_id=str(metadata["id"]),
        status=str(metadata["status"]),
        calibration=calibration,
        metadata=metadata,
    )
