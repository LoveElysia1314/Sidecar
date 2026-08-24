"""Dualign 服务层。"""

from dualign.services.repair import (
    RepairState,
    RepairService,
    replay,
    make_table_view,
    TableViewModel,
)
from dualign.services.ai_repair_agent import (
    AiRepairAgent,
    AgentReviewSession,
    build_agent_review_session,
    ChapterContext,
    AgentEvent,
    MaxTurnsExceeded,
    compute_cost,
    DEEPSEEK_PRICES,
)
from dualign.services.embedding_cache import EmbeddingCache
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.similarity import SimilarityScorer
from dualign.services.cli_pipeline import align_documents
from dualign.services.pair_save import (
    PairSaveConflictError,
    PairSaveError,
    PairSaveResult,
    recover_pending_pair_saves,
    save_pair_transaction,
)
from dualign.services.realignment import RebuiltAlignment, rebuild_alignment
from dualign.services.report_io import (
    AlignmentKey,
    ReportError,
    load_report,
    materialize_reader_rows,
    report_matches_alignment,
    save_report,
    set_ai_review,
)
from dualign.services.solidify import (
    BatchSolidificationPlan,
    BatchSolidificationResult,
    SOLIDIFY_PRESETS,
    SOLIDIFY_TYPES,
    SolidificationPlan,
    SolidifyPolicy,
    SolidifyTarget,
    apply_batch_solidification,
    build_solidification_plan,
    load_solidify_policy,
    plan_batch_solidification,
    plan_report_solidification,
    solidify_report,
)

__all__ = [
    # repair
    "RepairState",
    "RepairService",
    "replay",
    "make_table_view",
    "TableViewModel",
    # ai_repair_agent
    "AiRepairAgent",
    "AgentReviewSession",
    "build_agent_review_session",
    "ChapterContext",
    "AgentEvent",
    "MaxTurnsExceeded",
    "compute_cost",
    "DEEPSEEK_PRICES",
    # embedding_cache
    "EmbeddingCache",
    # cached_encoder
    "CachedEncoder",
    # similarity
    "SimilarityScorer",
    # cli_pipeline
    "align_documents",
    # solidification transaction
    "PairSaveConflictError",
    "PairSaveError",
    "PairSaveResult",
    "recover_pending_pair_saves",
    "save_pair_transaction",
    "RebuiltAlignment",
    "rebuild_alignment",
    # report_io
    "save_report",
    "load_report",
    "AlignmentKey",
    "report_matches_alignment",
    "set_ai_review",
    "ReportError",
    "materialize_reader_rows",
    # selective solidification
    "SOLIDIFY_PRESETS",
    "SOLIDIFY_TYPES",
    "BatchSolidificationPlan",
    "BatchSolidificationResult",
    "SolidificationPlan",
    "SolidifyPolicy",
    "SolidifyTarget",
    "apply_batch_solidification",
    "build_solidification_plan",
    "load_solidify_policy",
    "plan_batch_solidification",
    "plan_report_solidification",
    "solidify_report",
]
