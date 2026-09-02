"""Production sparse-MDL alignment implementation."""

from dualign.algorithms.mdl.candidate_graph import (
    CenteredFrontierMDLResult,
    align_centered_frontier_mdl,
)
from dualign.algorithms.mdl.composition_mdl import (
    CandidateEdge,
    ConditionalRankEvidence,
    CounterfactualCompositionResult,
    ExplicitMDLResult,
    align_counterfactual_composition_mdl,
    align_explicit_evidence_mdl,
    conditional_rank_evidence,
    counterfactual_diagnostics,
    decision_relevant_candidates,
)
from dualign.algorithms.mdl.mdl_aligner import (
    MDLAlignmentResult,
    align_evidence_lattice_mdl,
    align_similarity_lattices_mdl,
    mutual_rank_code_evidence,
    normalize_embeddings,
)
from dualign.algorithms.mdl.pipeline import MDLPipelineResult, align_mdl_pipeline
from dualign.algorithms.mdl.robustness import maximum_monotone_evidence

__all__ = [
    "CandidateEdge",
    "CenteredFrontierMDLResult",
    "ConditionalRankEvidence",
    "CounterfactualCompositionResult",
    "ExplicitMDLResult",
    "MDLAlignmentResult",
    "MDLPipelineResult",
    "align_centered_frontier_mdl",
    "align_counterfactual_composition_mdl",
    "align_evidence_lattice_mdl",
    "align_explicit_evidence_mdl",
    "align_mdl_pipeline",
    "align_similarity_lattices_mdl",
    "conditional_rank_evidence",
    "counterfactual_diagnostics",
    "decision_relevant_candidates",
    "maximum_monotone_evidence",
    "mutual_rank_code_evidence",
    "normalize_embeddings",
]
