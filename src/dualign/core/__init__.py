"""Dualign 核心算法模块（无状态纯函数）。"""

from dualign.core.aligner import (
    ALGORITHM_LEGACY_ANCHOR_V1,
    ALGORITHM_MDL_V1,
    ALIGN_CACHE_REVISION,
    AlignConfig,
    AlignmentResult,
    align,
    alignment_payload,
    op_type_str,
    count_punct_info,
    pair_score,
    find_bilateral_anchors,
    bilateral_trust_margin,
    select_monotonic_anchors_weighted,
    ALIGN_CORE_VERSION,
    _normalize,
    _smart_join_lines,
)
from dualign.core.legacy_anchor_aligner import LegacyAnchorConfig

from dualign.core.punctuation import (
    PunctuationHandler,
    UniversalSplitter,
    calculate_punctuation_similarity,
    detect_language_mix,
)

from dualign.core.file_pair_matcher import (
    FilePairMatcher,
    MatchRule,
    MatchedPair,
)

__all__ = [
    "ALIGN_CACHE_REVISION",
    "ALGORITHM_LEGACY_ANCHOR_V1",
    "ALGORITHM_MDL_V1",
    "AlignConfig",
    "LegacyAnchorConfig",
    "AlignmentResult",
    "align",
    "alignment_payload",
    "op_type_str",
    "count_punct_info",
    "pair_score",
    "find_bilateral_anchors",
    "bilateral_trust_margin",
    "select_monotonic_anchors_weighted",
    "ALIGN_CORE_VERSION",
    "_normalize",
    "_smart_join_lines",
    "PunctuationHandler",
    "UniversalSplitter",
    "calculate_punctuation_similarity",
    "detect_language_mix",
    "FilePairMatcher",
    "MatchRule",
    "MatchedPair",
]
