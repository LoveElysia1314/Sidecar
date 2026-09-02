"""Dualign — 数据模型（统一公共 API 面）"""

from dualign.models.state import (
    AlignmentSnapshot,
    ChapterState,
    MISSING,
    OpT,
    RelationGroup,
    RelationRow,
)
from dualign.models.action import RepairAction, AiProposal, AiProposalStore
from dualign.models.alignment_pair import (
    AlignmentLink,
    AlignmentPair,
    AlignmentPairValidationError,
    DocumentReference,
)
from dualign.models.pair_editing import (
    BlockLink,
    EditableDocument,
    PairEditingState,
)
from dualign.models.relation_status import (
    RelationAnomaly,
    RelationStatus,
    RelationReviewInfo,
    project_relation_statuses,
    relation_status_to_info,
)
from dualign.models.source import (
    ALL_EFFECTIVE_SOURCES,
    SOURCE_AI,
    SOURCE_AUTO,
    SOURCE_LABELS,
    SOURCE_NONE,
    SOURCE_USER,
)

__all__ = [
    "AlignmentSnapshot",
    "OpT",
    "MISSING",
    "RepairAction",
    "AiProposal",
    "AiProposalStore",
    "AlignmentLink",
    "AlignmentPair",
    "AlignmentPairValidationError",
    "DocumentReference",
    "BlockLink",
    "EditableDocument",
    "PairEditingState",
    "RelationRow",
    "RelationGroup",
    "ChapterState",
    "RelationStatus",
    "RelationAnomaly",
    "RelationReviewInfo",
    "project_relation_statuses",
    "relation_status_to_info",
    "SOURCE_NONE",
    "SOURCE_AUTO",
    "SOURCE_AI",
    "SOURCE_USER",
    "ALL_EFFECTIVE_SOURCES",
    "SOURCE_LABELS",
]
