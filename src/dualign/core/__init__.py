"""Dualign 核心算法模块（无状态纯函数）。"""

from dualign.core.aligner import (
    ALGORITHM_MDL_V1,
    ALIGN_CACHE_REVISION,
    AlignConfig,
    AlignmentResult,
    align,
    alignment_payload,
    ALIGN_CORE_VERSION,
)
from dualign.core.text import op_type_str

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
    "ALGORITHM_MDL_V1",
    "AlignConfig",
    "AlignmentResult",
    "align",
    "alignment_payload",
    "op_type_str",
    "ALIGN_CORE_VERSION",
    "PunctuationHandler",
    "UniversalSplitter",
    "calculate_punctuation_similarity",
    "detect_language_mix",
    "FilePairMatcher",
    "MatchRule",
    "MatchedPair",
]
