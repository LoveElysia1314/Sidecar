"""Public report-only alignment pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dualign.common import load_text_lines
from dualign.config import get_embedding_cache_path
from dualign.core import (
    ALGORITHM_MDL_V1,
    AlignConfig,
    AlignmentResult,
    align,
    alignment_payload,
)
from dualign.core.calibration import resolve_alignment_calibration
from dualign.services.cached_encoder import CachedEncoder
from dualign.services.embedding_cache import EmbeddingCache
from dualign.services.report_io import (
    ReportError,
    build_report,
    load_report,
    operations_from_report,
    relation_ids_from_report,
    report_matches_documents,
    report_matches_alignment,
    save_report,
)
from dualign.services.state_reconciliation import (
    reconcile_relation_state,
    relation_fingerprints,
    relation_fingerprints_from_report,
)

LEGACY_ALGORITHM = "legacy-anchor-v1"


def _algorithm_name(config) -> str:
    return str(getattr(config, "algorithm", ALGORITHM_MDL_V1))


def _run_alignment(
    lines_a,
    lines_b,
    embeddings_a,
    embeddings_b,
    config,
    encode_fn,
    calibration,
) -> AlignmentResult:
    """Keep the archived solver behind the explicit CLI configuration boundary."""

    if _algorithm_name(config) != LEGACY_ALGORITHM:
        return align(
            lines_a,
            lines_b,
            embeddings_a,
            embeddings_b,
            config,
            encode_fn=encode_fn,
            calibration=calibration,
        )

    from dualign.core.legacy_anchor_aligner import align as legacy_align

    legacy = legacy_align(
        lines_a,
        lines_b,
        embeddings_a,
        embeddings_b,
        config,
        encode_fn=encode_fn,
    )
    return AlignmentResult(
        all_ops=list(legacy.all_ops),
        stats=dict(legacy.stats),
        status="aligned",
        algorithm=LEGACY_ALGORITHM,
    )


def default_report_path(document_a_path: str | Path) -> Path:
    path = Path(document_a_path)
    stem = path.stem.removesuffix(".source").removesuffix(".target")
    return path.parent / f"{stem}.report.json"


def _review_flags_from_alignment(
    operations: list, alignment: dict, relation_ids=()
) -> list:
    from dualign.services.repair import review_flags_for_uncertain_regions

    regions = []
    for item in alignment.get("uncertain_regions", []):
        try:
            regions.append(
                (
                    (
                        int(item["start"]["source"]),
                        int(item["start"]["target"]),
                    ),
                    (
                        int(item["end"]["source"]),
                        int(item["end"]["target"]),
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    alternative_operations = []
    for item in alignment.get("alternative_ops", []):
        try:
            alternative_operations.append(
                (
                    tuple(int(index) for index in item["s"]),
                    tuple(int(index) for index in item["t"]),
                    float(item.get("sc", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return review_flags_for_uncertain_regions(
        operations,
        regions,
        alternative_operations=alternative_operations,
        relation_ids=relation_ids,
    )


def _provenance(model, config, calibration_id: str = "") -> dict:
    import hashlib
    import json

    from dualign import __version__

    algorithm_name = _algorithm_name(config)
    if not calibration_id and algorithm_name == ALGORITHM_MDL_V1:
        resolved = resolve_alignment_calibration(
            model, calibration_id=config.calibration_id
        )
        calibration_id = resolved.calibration_id if resolved is not None else ""
    if algorithm_name == LEGACY_ALGORITHM:
        from dualign.core.legacy_anchor_aligner import (
            ALIGN_CACHE_REVISION,
            ALIGN_CORE_VERSION,
        )

    else:
        from dualign.core import ALIGN_CACHE_REVISION, ALIGN_CORE_VERSION

    provider = ""
    endpoint = ""
    model_name = getattr(model, "_model", "") if model is not None else ""
    instruction = getattr(model, "_instruction", "") if model is not None else ""
    try:
        from dualign.providers import ProviderManager

        ProviderManager.load()
        active = ProviderManager.active()
        if active is not None:
            provider = active.provider_id
            endpoint = str(active.base_url).rstrip("/")
            model_name = model_name or active.model_name
            instruction = instruction or active.instruction_text
            if not instruction and active.provider_id == "ollama":
                from dualign.config import INSTRUCTION_TEXT

                instruction = INSTRUCTION_TEXT
    except (OSError, ValueError):
        pass
    config_values = {**vars(config), "resolved_calibration_id": calibration_id}
    config_payload = json.dumps(config_values, sort_keys=True, separators=(",", ":"))
    result = {
        "tool": "dualign",
        "tool_version": __version__,
        "algorithm": {
            "name": algorithm_name,
            "revision": ALIGN_CORE_VERSION,
            "cache_revision": ALIGN_CACHE_REVISION,
            "configuration_sha256": hashlib.sha256(
                config_payload.encode("utf-8")
            ).hexdigest(),
        },
        "embedding": {"provider": provider, "model": str(model_name)},
    }
    if endpoint:
        result["embedding"]["endpoint"] = endpoint
    if instruction:
        result["embedding"]["instruction_sha256"] = hashlib.sha256(
            instruction.encode("utf-8")
        ).hexdigest()
    if calibration_id:
        result["algorithm"]["calibration_id"] = calibration_id
    return result


def _empty_result(source_count: int, target_count: int, config) -> AlignmentResult:
    if _algorithm_name(config) != LEGACY_ALGORITHM:
        return AlignmentResult(
            all_ops=[],
            stats={"n_source": source_count, "n_target": target_count, "n_ops": 0},
            status="rejected",
            reason="empty_document",
            algorithm=ALGORITHM_MDL_V1,
        )
    operations = []
    if source_count and not target_count:
        operations = [((index,), (), 0.0) for index in range(source_count)]
    elif target_count and not source_count:
        operations = [((), (index,), 0.0) for index in range(target_count)]
    return AlignmentResult(
        all_ops=operations,
        stats={
            "n_source": source_count,
            "n_target": target_count,
            "n_ops": len(operations),
            "n_true_anchors": 0,
            "anchor_density": 0.0,
            "avg_similarity": 0.0,
        },
        algorithm=LEGACY_ALGORITHM,
    )


def _quality_diagnostics(result, source_count: int, target_count: int) -> dict:
    """Keep anomaly diagnostics separate from the mdl applicability decision."""

    if result.algorithm != LEGACY_ALGORITHM:
        return {
            "level": "diagnostic_only",
            "rejections": [],
            "indicators": {"alignment_status": result.status},
        }
    from dualign.core.legacy_anchor_quality import (
        _gap_row_ratio,
        assess_alignment_quality,
    )

    assessment = assess_alignment_quality(
        result.stats or {},
        source_count,
        target_count,
        _gap_row_ratio(result.all_ops, source_count, target_count),
        (result.stats or {}).get("n_overflow_rows", 0),
    )
    return {
        "level": assessment["quality"],
        "rejections": assessment.get("rejections", []),
        "indicators": assessment["indicators"],
    }


def _repair_mode(strategy: str, model, quality: dict) -> tuple[str, object]:
    """Apply frozen structural blockers only to explicit legacy results."""

    if quality.get("level") != "diagnostic_only":
        from dualign.core.legacy_anchor_quality import automatic_repair_blockers

        if automatic_repair_blockers(quality):
            return "minimal", None
    return strategy, model


def _auto_repair_state(
    state,
    strategy: str,
    model,
    quality: dict,
    *,
    unresolved_only: bool = False,
):
    """Apply the selected policy and cache embeddings required by split repair."""

    from dualign.services.repair import RepairService
    from dualign.services.repair_policy import choose_auto_repair

    repair_strategy, repair_model = _repair_mode(strategy, model, quality)
    kwargs = {
        "strategy": repair_strategy,
        "model": repair_model,
        "unresolved_only": unresolved_only,
    }
    needs_embeddings = repair_model is not None and any(
        (plan := choose_auto_repair(len(source), len(target), repair_strategy))
        is not None
        and plan.requires_model
        for source, target, _score in state.snapshot.original_ops
    )
    if not needs_embeddings:
        return RepairService.auto_repair(state, **kwargs)

    with EmbeddingCache(get_embedding_cache_path()) as cache:
        return RepairService.auto_repair(state, cache=cache, **kwargs)


def align_documents(
    document_a_path: str,
    document_b_path: str,
    report_path: str = "",
    *,
    model=None,
    config=None,
    strategy: str = "minimal",
    reset_work_state: bool = False,
    reuse_alignment: bool = True,
    preserve_work_state: bool = False,
    previous_report_path: str | Path = "",
) -> dict:
    """Align two documents and persist only their replayable work report.

    ``reuse_alignment`` controls whether a matching report may supply its
    expensive alignment relations. ``reset_work_state`` rebuilds the report;
    with ``preserve_work_state`` it retains existing review decisions and only
    auto-repairs unresolved relations, otherwise it starts from clean state.
    ``previous_report_path`` may supply non-authoritative work state archived
    by a caller after upstream text changed; it is never treated as a cache hit.
    """

    path_a = Path(document_a_path)
    path_b = Path(document_b_path)
    if not path_a.is_file():
        return {"success": False, "error": f"文档 A 不存在: {path_a}"}
    if not path_b.is_file():
        return {"success": False, "error": f"文档 B 不存在: {path_b}"}
    target = Path(report_path) if report_path else default_report_path(path_a)
    cfg = config or AlignConfig()
    lines_a = load_text_lines(str(path_a))
    lines_b = load_text_lines(str(path_b))

    encoder = model
    if lines_a and lines_b:
        encoder = _ensure_model(model)
        if encoder is None:
            return {"success": False, "error": "模型未加载"}
    resolved = None
    if _algorithm_name(cfg) == ALGORITHM_MDL_V1:
        resolved = resolve_alignment_calibration(
            encoder, calibration_id=cfg.calibration_id
        )
    calibration_id = resolved.calibration_id if resolved is not None else ""
    provenance = _provenance(encoder, cfg, calibration_id)

    existing_report = None
    state_sources = [target]
    if previous_report_path:
        previous_target = Path(previous_report_path)
        if previous_target != target:
            state_sources.append(previous_target)
    for state_source in state_sources:
        if not state_source.is_file():
            continue
        try:
            existing_report = load_report(state_source)
            break
        except ReportError:
            continue

    if reuse_alignment and target.is_file():
        try:
            cached = load_report(target)
            if report_matches_alignment(cached, path_a, path_b, provenance):
                cached_operations = operations_from_report(cached)
                cached_relation_ids = relation_ids_from_report(cached)
                cached_alignment = dict(cached.get("alignment") or {})
                if reset_work_state:
                    from dualign.models.action import RepairAction
                    from dualign.models.state import AlignmentSnapshot
                    from dualign.services.repair import RepairState

                    existing_actions = (
                        [
                            RepairAction.from_dict(item)
                            for item in cached.get("repair_log", [])
                        ]
                        if preserve_work_state
                        else []
                    )
                    quality = dict(cached.get("quality") or {})
                    repair_log = []
                    if cached_alignment.get("status", "aligned") == "aligned":
                        state = RepairState(
                            AlignmentSnapshot.from_alignment(
                                cached_operations,
                                lines_a,
                                lines_b,
                                cached_relation_ids,
                            ),
                            existing_actions,
                        )
                        repair_log = _auto_repair_state(
                            state,
                            strategy,
                            encoder,
                            quality,
                            unresolved_only=preserve_work_state,
                        ).repair_log
                    elif cached_alignment.get("status") == "needs_review":
                        repair_log = (
                            existing_actions
                            if preserve_work_state
                            else _review_flags_from_alignment(
                                cached_operations, cached_alignment
                            )
                        )
                    report = build_report(
                        chapter_id=path_a.stem.split(".")[0],
                        document_a_path=path_a,
                        document_b_path=path_b,
                        operations=cached_operations,
                        relation_ids=cached_relation_ids,
                        stats=dict(cached.get("stats") or {}),
                        quality=quality,
                        provenance=provenance,
                        alignment=cached_alignment,
                        repair_log=repair_log,
                        previous=cached if preserve_work_state else None,
                    )
                    save_report(report, target)
                    return {
                        "success": True,
                        "ops": cached_operations,
                        "report_path": str(target),
                        "quality": quality.get("level", ""),
                        "rejections": quality.get("rejections", []),
                        "status": cached_alignment.get("status", "aligned"),
                        "reason": cached_alignment.get("reason"),
                        "cache_hit": True,
                        "work_state_reset": True,
                        "work_state_preserved": preserve_work_state,
                    }
                return {
                    "success": True,
                    "ops": cached_operations,
                    "report_path": str(target),
                    "quality": (cached.get("quality") or {}).get("level", ""),
                    "rejections": (cached.get("quality") or {}).get("rejections", []),
                    "status": cached_alignment.get("status", "aligned"),
                    "reason": cached_alignment.get("reason"),
                    "cache_hit": True,
                }
        except ReportError:
            pass

    if lines_a and lines_b:
        with EmbeddingCache(get_embedding_cache_path()) as cache:
            cached_encoder = CachedEncoder(encoder, cache)
            result = _run_alignment(
                lines_a,
                lines_b,
                cached_encoder.encode(lines_a),
                cached_encoder.encode(lines_b),
                cfg,
                cached_encoder.encode,
                resolved.calibration if resolved is not None else None,
            )
    else:
        result = _empty_result(len(lines_a), len(lines_b), cfg)

    quality = _quality_diagnostics(result, len(lines_a), len(lines_b))
    alignment = alignment_payload(result, calibration_id=calibration_id)
    reconciliation = None
    relation_ids = ()
    previous = None
    if existing_report is not None and not reset_work_state:
        try:
            old_operations = operations_from_report(existing_report)
            old_relation_ids = relation_ids_from_report(existing_report)
            old_fingerprints = relation_fingerprints_from_report(
                existing_report, expected_count=len(old_operations)
            )
            documents_unchanged = report_matches_documents(
                existing_report, path_a, path_b
            )
            # Legacy v1 reports did not persist relation content.  They can be
            # migrated safely only while the exact documents are still here.
            if old_fingerprints is None and documents_unchanged:
                old_fingerprints = relation_fingerprints(
                    old_operations, lines_a, lines_b
                )
            if old_fingerprints is not None:
                reconciliation = reconcile_relation_state(
                    source_operations=old_operations,
                    source_relation_ids=old_relation_ids,
                    source_fingerprints=old_fingerprints,
                    target_operations=result.all_ops,
                    target_fingerprints=relation_fingerprints(
                        result.all_ops, lines_a, lines_b
                    ),
                    repair_log=existing_report.get("repair_log", ()),
                    ai_proposals=existing_report.get("ai_proposals"),
                    scores=existing_report.get("scores"),
                    positional_identity=documents_unchanged,
                    cause="alignment-refresh",
                )
                relation_ids = reconciliation.relation_ids
                previous = dict(existing_report)
                previous["ai_proposals"] = reconciliation.ai_proposals
                previous["scores"] = reconciliation.scores
                old_alignment = dict(existing_report.get("alignment") or {})
                preserve_ai_review = (
                    reconciliation.audit["invalidated_relations"] == 0
                    and reconciliation.audit["new_relations"] == 0
                    and old_alignment.get("status", "aligned") == "aligned"
                    and result.status == "aligned"
                )
                previous["ai_review"] = (
                    existing_report.get("ai_review", {}) if preserve_ai_review else {}
                )
                history = list(previous.get("history", []))
                history.append(
                    {
                        "type": "alignment-state-reconciliation",
                        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        **reconciliation.audit,
                        "preserved_ai_review": preserve_ai_review,
                    }
                )
                previous["history"] = history
        except (ReportError, ValueError):
            reconciliation = None
            relation_ids = ()
            previous = None

    repair_log = list(reconciliation.repair_log) if reconciliation else []
    if result.status == "aligned" and result.all_ops:
        from dualign.models.action import RepairAction
        from dualign.models.state import AlignmentSnapshot
        from dualign.services.repair import RepairState

        state = RepairState(
            AlignmentSnapshot.from_alignment(
                result.all_ops, lines_a, lines_b, relation_ids
            ),
            [RepairAction.from_dict(action) for action in repair_log],
        )
        repair_log = _auto_repair_state(
            state,
            strategy,
            encoder,
            quality,
            unresolved_only=reconciliation is not None,
        ).repair_log
    elif result.status == "needs_review" and result.all_ops:
        from dualign.services.repair import review_flags_for_uncertain_regions

        generated_flags = review_flags_for_uncertain_regions(
            result.all_ops,
            result.uncertain_regions,
            alternative_operations=result.alternative_ops,
            relation_ids=relation_ids,
        )
        already_owned = {
            relation_id
            for action in repair_log
            for relation_id in action.get("relation_ids", ())
        }
        repair_log.extend(
            action
            for action in generated_flags
            if not (set(action.relation_ids) & already_owned)
        )
    report = build_report(
        chapter_id=path_a.stem.split(".")[0],
        document_a_path=path_a,
        document_b_path=path_b,
        operations=result.all_ops,
        relation_ids=relation_ids,
        stats=result.stats or {},
        quality=quality,
        provenance=provenance,
        alignment=alignment,
        repair_log=repair_log,
        previous=previous,
        document_a_lines=lines_a,
        document_b_lines=lines_b,
    )
    save_report(report, target)
    return {
        "success": True,
        "ops": result.all_ops,
        "report_path": str(target),
        "quality": quality["level"],
        "rejections": quality["rejections"],
        "status": result.status,
        "reason": result.reason or None,
        "cache_hit": False,
        "work_state_reset": reset_work_state,
        "work_state_reconciliation": (
            dict(reconciliation.audit) if reconciliation is not None else None
        ),
    }


def _ensure_model(model):
    if model is not None:
        return model
    from dualign.services.embedding import _try_lazy_load_model, load_model_for_provider

    model = _try_lazy_load_model()
    if model is None:
        try:
            model = load_model_for_provider()
        except Exception:
            return None
    return model
