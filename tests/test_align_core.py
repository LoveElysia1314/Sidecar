"""
Dualign — 对齐核心算法测试
"""

import numpy as np
import pytest
from dualign.core.legacy_anchor_aligner import (
    LegacyAnchorConfig,
    AlignmentResult,
    align,
    _enumerate_merge_combos,
    ALIGN_CORE_VERSION,
)
from dualign.core.text import op_type_str


class TestOpTypeStr:
    def test_1to1(self):
        assert op_type_str((0,), (0,)) == "1:1"

    def test_2to1(self):
        assert op_type_str((0, 1), (0,)) == "2:1"

    def test_1to3(self):
        assert op_type_str((0,), (0, 1, 2)) == "1:3"

    def test_general_many_to_many(self):
        assert op_type_str((0, 1), (0, 1, 2)) == "2:3"

    def test_delete(self):
        assert op_type_str((0,), ()) == "1:0"

    def test_insert(self):
        assert op_type_str((), (0,)) == "0:1"

    def test_multi_delete(self):
        assert op_type_str((0, 1, 2), ()) == "3:0"

    def test_multi_insert(self):
        assert op_type_str((), (0, 1)) == "0:2"


class TestAlignEmpty:
    def test_both_empty(self):
        result = align([], [], np.empty((0, 3)), np.empty((0, 3)))
        assert len(result.all_ops) == 0
        assert result.stats["n_source"] == 0
        assert result.stats["n_target"] == 0

    def test_single_line(self):
        emb = np.array([[1.0]], dtype=np.float64)
        result = align(["hello"], ["你好"], emb, emb)
        assert len(result.all_ops) >= 1

    def test_src_empty_tgt_nonempty(self):
        emb = np.eye(3)
        result = align([], ["a", "b", "c"], np.empty((0, 3)), emb)
        assert result.all_ops == [
            ((), (0,), 0.0),
            ((), (1,), 0.0),
            ((), (2,), 0.0),
        ]
        assert result.stats["n_insert"] == 3

    def test_tgt_empty_src_nonempty(self):
        emb = np.eye(3)
        result = align(["a", "b", "c"], [], emb, np.empty((0, 3)))
        assert result.all_ops == [
            ((0,), (), 0.0),
            ((1,), (), 0.0),
            ((2,), (), 0.0),
        ]
        assert result.stats["n_delete"] == 3

    def test_empty_side_respects_disabled_gap_operation(self):
        with pytest.raises(ValueError, match="无法完整覆盖"):
            align(
                ["a"],
                [],
                np.ones((1, 1)),
                np.empty((0, 1)),
                LegacyAnchorConfig(allow_deletions=False),
            )


class TestMergeCombinationEnumeration:
    def test_includes_free_lines_on_both_sides_of_one_baseline(self):
        anchors = [((2,), (1,), 0.9)]

        source, target = _enumerate_merge_combos(anchors, n=5, m=3)

        assert ((1, 2, 3), (1,)) in source
        assert ((2,), (0, 1, 2)) in target

    def test_never_crosses_a_neighbouring_baseline(self):
        anchors = [((1,), (1,), 0.9), ((3,), (3,), 0.9)]

        source, target = _enumerate_merge_combos(anchors, n=5, m=5)

        assert all(not ({1, 3} <= set(span)) for span, _ in source)
        assert all(not ({1, 3} <= set(span)) for _, span in target)


class TestAlignConfig:
    def test_default_config(self):
        cfg = LegacyAnchorConfig()
        assert cfg.allow_insertions is True
        assert cfg.allow_deletions is True

    def test_custom_config(self):
        cfg = LegacyAnchorConfig(allow_insertions=False, allow_deletions=False)
        assert cfg.allow_insertions is False
        assert cfg.allow_deletions is False


class TestAlignStats:
    def test_stats_keys(self):
        emb = np.eye(3)
        result = align(["a", "b", "c"], ["x", "y", "z"], emb, emb)
        required = {"n_source", "n_target", "n_1to1", "avg_similarity"}
        assert required.issubset(result.stats.keys())

    def test_version_present(self):
        assert len(ALIGN_CORE_VERSION) > 0
        assert "." in ALIGN_CORE_VERSION

    def test_large_unanchored_gap_skips_merge_encoding(self):
        target_embeddings = np.eye(102, dtype=np.float64)
        source_embeddings = np.vstack(
            (
                target_embeddings[:51],
                np.zeros((100, 102), dtype=np.float64),
                target_embeddings[51:],
            )
        )

        def expensive_encode(_texts):
            raise AssertionError("large structural gaps must fail preflight")

        result = align(
            [f"s{i}" for i in range(202)],
            [f"t{i}" for i in range(102)],
            source_embeddings,
            target_embeddings,
            encode_fn=expensive_encode,
        )

        assert result.stats["max_anchor_gap"] == 100
        assert result.stats["merge_scoring_skipped"] is True
        assert "large_anchor_gap" in result.stats["merge_skip_reasons"]
