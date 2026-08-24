"""Context-conditioned embeddings for semantically weak atomic lines.

The construction is deliberately length agnostic.  Every line is represented
by the marginal embedding contribution of inserting it between its immediate
predecessor and successor.  Short utterances benefit most, while the ablated
context prevents neighbouring translated prose from becoming the entire
signal for an unrelated inserted line.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from dualign.core import _smart_join_lines
from dualign.algorithms.mdl import normalize_embeddings


def direct_context_texts(lines: list[str]) -> tuple[list[str], list[str]]:
    """Return three-line contexts and their current-line ablations."""

    full = []
    ablated = []
    for index in range(len(lines)):
        previous = lines[index - 1 : index]
        following = lines[index + 1 : index + 2]
        full.append(_smart_join_lines([*previous, lines[index], *following]))
        ablated.append(_smart_join_lines([*previous, *following]))
    return full, ablated


def contextual_embeddings(
    lines: list[str],
    encode_fn: Callable[[list[str]], np.ndarray],
    *,
    residual: bool,
) -> np.ndarray:
    """Encode direct context, optionally subtracting the no-current baseline."""

    if not lines:
        return np.empty((0, 0), dtype=np.float64)
    full, ablated = direct_context_texts(lines)
    texts = list(dict.fromkeys([*full, *ablated] if residual else full))
    vectors = normalize_embeddings(encode_fn(texts))
    by_text = dict(zip(texts, vectors))
    full_vectors = np.vstack([by_text[text] for text in full])
    if not residual:
        return full_vectors
    ablated_vectors = np.vstack([by_text[text] for text in ablated])
    return normalize_embeddings(full_vectors - ablated_vectors)
