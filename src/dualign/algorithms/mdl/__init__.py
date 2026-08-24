"""Statistically gated sparse-MDL alignment implementation."""

from dualign.algorithms.mdl.mdl_aligner import (
    MDLAlignmentResult,
    align_evidence_lattice_mdl,
    align_similarity_lattices_mdl,
    mutual_rank_code_evidence,
    normalize_embeddings,
)
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
from dualign.algorithms.mdl.robustness import (
    MonotoneOrderEvidence,
    beta_binomial_upper_p,
    conformal_upper_p,
    fit_beta_binomial_order_model,
    monotone_order_evidence,
    mutual_best_pairs,
    mutual_monotone_chain,
    symmetric_nearest_score,
)
from dualign.algorithms.mdl.pipeline import (
    AlignmentCalibration,
    AlignmentGateDecision,
    MDLPipelineResult,
    align_mdl_pipeline,
    assess_alignment_applicability,
)

__all__ = [
    "MDLAlignmentResult",
    "align_evidence_lattice_mdl",
    "align_similarity_lattices_mdl",
    "mutual_rank_code_evidence",
    "normalize_embeddings",
    "CenteredFrontierMDLResult",
    "align_centered_frontier_mdl",
    "CandidateEdge",
    "ConditionalRankEvidence",
    "CounterfactualCompositionResult",
    "ExplicitMDLResult",
    "align_counterfactual_composition_mdl",
    "align_explicit_evidence_mdl",
    "conditional_rank_evidence",
    "counterfactual_diagnostics",
    "decision_relevant_candidates",
    "MonotoneOrderEvidence",
    "beta_binomial_upper_p",
    "conformal_upper_p",
    "fit_beta_binomial_order_model",
    "monotone_order_evidence",
    "mutual_best_pairs",
    "mutual_monotone_chain",
    "symmetric_nearest_score",
    "AlignmentCalibration",
    "AlignmentGateDecision",
    "MDLPipelineResult",
    "align_mdl_pipeline",
    "assess_alignment_applicability",
]
