import numpy as np
import pytest

from dualign.services.local_realign import (
    LOCAL_REALIGN_ALIGNED,
    LOCAL_REALIGN_NEEDS_REVIEW,
    LOCAL_REASON_COMPOSITION_TIE,
    align_split_region,
    materialize_local_path,
)


def test_production_adapter_allows_recursive_merge_after_split():
    source = ["alpha first", "alpha second", "beta"]
    target = ["Alpha.", "Beta."]
    vectors = {
        "alpha first": (1.0, 0.0),
        "alpha second": (0.9, 0.1),
        "beta": (0.0, 1.0),
        "Alpha.": (1.0, 0.0),
        "Beta.": (0.0, 1.0),
        "alpha first alpha second": (1.0, 0.0),
        "alpha second beta": (0.2, 0.8),
    }

    def encode(texts):
        return np.asarray([vectors.get(text, (0.5, 0.5)) for text in texts])

    result = align_split_region(
        source,
        target,
        encode(source),
        encode(target),
        encode,
    )

    assert result.status == LOCAL_REALIGN_ALIGNED
    assert [(a, b) for a, b, _score in result.operations] == [
        ((0, 1), (0,)),
        ((2,), (1,)),
    ]
    assert materialize_local_path(result.operations, source, target)[:2] == (
        ["alpha first alpha second", "beta"],
        ["Alpha.", "Beta."],
    )


def test_production_adapter_returns_review_on_exact_composition_tie():
    source = ["same", "same", "same"]
    target = ["same", "same"]

    def encode(texts):
        return np.ones((len(texts), 2), dtype=np.float64)

    result = align_split_region(
        source,
        target,
        encode(source),
        encode(target),
        encode,
    )

    assert result.status == LOCAL_REALIGN_NEEDS_REVIEW
    assert result.reason == LOCAL_REASON_COMPOSITION_TIE
    assert result.operations == ()


@pytest.mark.parametrize(
    "operations",
    [
        [((0,), (), 0.0), ((), (0,), 0.0)],
        [((0, 1), (0, 1), 1.0)],
        [((1,), (0,), 1.0), ((0,), (1,), 1.0)],
    ],
)
def test_materialization_rejects_paths_outside_the_local_grammar(operations):
    with pytest.raises(RuntimeError):
        materialize_local_path(operations, ["a", "b"], ["A", "B"])
