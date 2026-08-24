import numpy as np
import pytest

from dualign.experiments.contextual_evidence import (
    contextual_embeddings,
    direct_context_texts,
)


def test_direct_context_uses_only_immediate_neighbours():
    full, ablated = direct_context_texts(["left", "middle", "right"])

    assert full == ["left middle", "left middle right", "middle right"]
    assert ablated == ["middle", "left right", "middle"]


def test_contextual_residual_subtracts_the_no_current_baseline():
    mapping = {
        "left middle": (2.0, 1.0),
        "left middle right": (1.0, 2.0),
        "middle right": (2.0, 2.0),
        "middle": (1.0, 0.0),
        "left right": (0.0, 1.0),
    }

    def encode(texts):
        return np.asarray([mapping[text] for text in texts], dtype=np.float64)

    full = contextual_embeddings(["left", "middle", "right"], encode, residual=False)
    residual = contextual_embeddings(["left", "middle", "right"], encode, residual=True)

    assert full.shape == residual.shape == (3, 2)
    assert np.linalg.norm(residual, axis=1) == pytest.approx([1.0, 1.0, 1.0])
    assert not np.allclose(full, residual)
