"""Declared observation space for cosine similarities used by MDL.

Embedding coordinates and all downstream code-length arithmetic keep their
native precision.  Only semantic cosine observations are projected onto the
finite binary16 lattice.  Exact duplicate logical texts share one computed
cell before the matrix is expanded, so arithmetic accumulation order cannot
manufacture different ranks for the same text pair.
"""

from __future__ import annotations

import numpy as np

COSINE_OBSERVATION_ID = "binary16-exact-text-pair-v1"


def _unique_text_vectors(
    texts: list[str], vectors: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return first-occurrence representatives and an inverse row index."""

    matrix = np.asarray(vectors)
    if matrix.ndim != 2 or matrix.shape[0] != len(texts):
        raise ValueError("文本与嵌入向量行数不一致")

    positions: dict[str, int] = {}
    representative_rows: list[int] = []
    inverse = np.empty(len(texts), dtype=np.intp)
    for row, text in enumerate(texts):
        position = positions.get(text)
        if position is None:
            position = len(representative_rows)
            positions[text] = position
            representative_rows.append(row)
        inverse[row] = position
    return matrix[representative_rows], inverse


def observed_cosine_matrix(
    texts_a: list[str],
    texts_b: list[str],
    normalized_a: np.ndarray,
    normalized_b: np.ndarray,
) -> np.ndarray:
    """Return the binary16 cosine observations for two logical-text axes.

    Text identity is exact equality after the caller's logical-line parsing;
    punctuation and other content are deliberately not normalized here.
    Repeated text on either axis is represented once, making every repeated
    ordered text pair an alias of the same score cell.

    The vectors are expected to be row-normalized.  Quantization happens only
    after the dot product, while rank evidence and MDL arithmetic may safely
    promote the returned values without recovering discarded precision.
    """

    source, source_inverse = _unique_text_vectors(texts_a, normalized_a)
    target, target_inverse = _unique_text_vectors(texts_b, normalized_b)
    if source.ndim != 2 or target.ndim != 2 or source.shape[1] != target.shape[1]:
        raise ValueError("两侧嵌入向量维度不一致")
    if not texts_a or not texts_b:
        return np.empty((len(texts_a), len(texts_b)), dtype=np.float16)

    raw = np.asarray(np.dot(source, target.T))
    np.clip(raw, -1.0, 1.0, out=raw)
    observed = raw.astype(np.float16)
    return observed[np.ix_(source_inverse, target_inverse)]
