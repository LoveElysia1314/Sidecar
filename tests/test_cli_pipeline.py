from __future__ import annotations

import json

import numpy as np

from dualign.core import AlignmentResult
from dualign.core.legacy_anchor_aligner import LegacyAnchorConfig
from dualign.models.action import RepairAction
from dualign.services.cli_pipeline import align_documents as _align_documents
from dualign.services.cli_pipeline import _auto_repair_state
from dualign.models.state import AlignmentSnapshot
from dualign.services.repair import RepairService, RepairState
from dualign.services.report_io import (
    AlignmentKey,
    load_report,
    materialize_reader_rows,
    save_report,
)


class MockEncoder:
    _model = "mock-diagonal"

    def encode(self, texts, normalize_embeddings=True, **_kwargs):
        if isinstance(texts, str):
            texts = [texts]
        vectors = np.eye(max(len(texts), 1), 8, dtype=np.float32)[: len(texts)]
        return vectors


class ContentEncoder:
    _model = "mock-content"

    def encode(self, texts, normalize_embeddings=True, **_kwargs):
        if isinstance(texts, str):
            texts = [texts]
        vectors = np.zeros((len(texts), 8), dtype=np.float32)
        for row, value in enumerate(texts):
            key = value.strip().rstrip(".!！").casefold()
            vectors[row, 0 if key == "a" else 1] = 1.0
        return vectors


def align_documents(*args, **kwargs):
    """Historical report lifecycle cases exercise the explicit legacy CLI."""

    kwargs.setdefault("config", LegacyAnchorConfig())
    return _align_documents(*args, **kwargs)


def _pair(tmp_path):
    source = tmp_path / "chapter.source.md"
    target = tmp_path / "chapter.target.md"
    source.write_text("A\n\nB\n", encoding="utf-8")
    target.write_text("a\n\nb\n", encoding="utf-8")
    return source, target


def test_document_a_first_split_reuses_embedding_cache(monkeypatch):
    snapshot = AlignmentSnapshot.from_alignment(
        [((0, 1), (0,), 0.5)],
        ["A1", "A2"],
        ["B1. B2."],
    )
    state = RepairState(snapshot)
    encoder = MockEncoder()
    cache = object()
    captured = {}

    class CacheContext:
        def __init__(self, _path):
            pass

        def __enter__(self):
            return cache

        def __exit__(self, *_args):
            return False

    def fake_auto_repair(state_arg, **kwargs):
        captured.update(kwargs)
        return state_arg

    monkeypatch.setattr("dualign.services.cli_pipeline.EmbeddingCache", CacheContext)
    monkeypatch.setattr(RepairService, "auto_repair", fake_auto_repair)

    result = _auto_repair_state(
        state,
        "src",
        encoder,
        {"level": "diagnostic_only"},
    )

    assert result is state
    assert captured == {
        "strategy": "src",
        "model": encoder,
        "unresolved_only": False,
        "cache": cache,
    }


def test_alignment_persists_only_a_report(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "alignment" / "chapter.report.json"

    result = align_documents(str(source), str(target), str(report), model=MockEncoder())

    assert result["success"]
    assert result["report_path"] == str(report)
    assert report.is_file()
    assert not list(tmp_path.rglob("*.align.yaml"))
    assert not (report.parent / "chapter.source.md").exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["format"] == "dualign-report/v1"
    assert data["documents"]["a"]["sha256"]
    assert data["snapshot_fingerprint"]
    assert data["provenance"]["embedding"]["model"] == "mock-diagonal"


def test_matching_report_skips_model_and_stale_document_invalidates_it(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    first = align_documents(str(source), str(target), str(report), model=encoder)
    second = align_documents(str(source), str(target), str(report), model=encoder)
    assert first["success"] and second["cache_hit"]

    source.write_text("changed\n", encoding="utf-8")
    third = align_documents(str(source), str(target), str(report), model=encoder)
    assert third["success"] and not third["cache_hit"]


def test_unversioned_report_is_recomputed_instead_of_migrated(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]
    stale = json.loads(report.read_text(encoding="utf-8"))
    stale["format"] = "dualign-report"
    report.write_text(json.dumps(stale), encoding="utf-8")

    rebuilt = align_documents(str(source), str(target), str(report), model=encoder)

    assert rebuilt["success"] and not rebuilt["cache_hit"]
    assert load_report(report)["format"] == "dualign-report/v1"


def test_alignment_configuration_is_part_of_report_cache_identity(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]

    changed = align_documents(
        str(source),
        str(target),
        str(report),
        model=encoder,
        config=LegacyAnchorConfig(anchor_min_score=0.42),
    )

    assert changed["success"] and not changed["cache_hit"]


def test_tool_release_metadata_does_not_invalidate_same_alignment(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]
    data = load_report(report)
    data["provenance"]["tool_version"] = "future-ui-release"
    save_report(data, report)

    reused = align_documents(str(source), str(target), str(report), model=encoder)

    assert reused["cache_hit"] is True


def test_historical_package_coupled_revision_reuses_same_cache_revision(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]
    data = load_report(report)
    data["provenance"]["algorithm"]["revision"] = "0.9.2"
    documents = data["documents"]
    data["alignment_key"] = AlignmentKey.from_values(
        documents["a"]["sha256"],
        documents["b"]["sha256"],
        data["provenance"],
    ).to_dict()
    save_report(data, report)

    reused = align_documents(str(source), str(target), str(report), model=encoder)

    assert reused["cache_hit"] is True


def test_changed_algorithm_cache_revision_still_invalidates_report(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]
    data = load_report(report)
    first_relation_id = data["ops"][0]["id"]
    data["repair_log"] = [
        RepairAction.make_flag(first_relation_id, "保留校订").to_dict()
    ]
    data["scores"] = {first_relation_id: {"0": 0.75}}
    data["ai_review"] = {"status": "completed", "model": "test"}
    data["provenance"]["algorithm"]["cache_revision"] = "different-relations"
    documents = data["documents"]
    data["alignment_key"] = AlignmentKey.from_values(
        documents["a"]["sha256"],
        documents["b"]["sha256"],
        data["provenance"],
    ).to_dict()
    save_report(data, report)

    rebuilt = align_documents(str(source), str(target), str(report), model=encoder)

    assert rebuilt["success"] and not rebuilt["cache_hit"]
    assert rebuilt["work_state_reconciliation"]["preserved_relations"] == len(
        rebuilt["ops"]
    )
    refreshed = load_report(report)
    assert any(
        action["kind"] == "flag" and action["relation_ids"] == [first_relation_id]
        for action in refreshed["repair_log"]
    )
    assert refreshed["scores"] == {first_relation_id: {"0": 0.75}}
    assert refreshed["ai_review"] == {"status": "completed", "model": "test"}


def test_document_punctuation_change_only_invalidates_affected_work(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = ContentEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]
    old = load_report(report)
    old_ids = tuple(item["id"] for item in old["ops"])
    assert len(old_ids) == 2
    old["repair_log"] = [
        RepairAction.make_flag(relation_id, relation_id).to_dict()
        for relation_id in old_ids
    ]
    old["scores"] = {
        relation_id: {"0": float(index)} for index, relation_id in enumerate(old_ids)
    }
    old["ai_review"] = {"status": "completed", "model": "test"}
    save_report(old, report)
    reusable_report = tmp_path / ".chapter.report.json.reuse"
    report.replace(reusable_report)

    source.write_text("A\n\nB!\n", encoding="utf-8")
    rebuilt = align_documents(
        str(source),
        str(target),
        str(report),
        model=encoder,
        previous_report_path=reusable_report,
    )

    assert rebuilt["success"] and not rebuilt["cache_hit"]
    assert rebuilt["work_state_reconciliation"]["preserved_relations"] == 1
    refreshed = load_report(report)
    assert [
        action["relation_ids"]
        for action in refreshed["repair_log"]
        if action["kind"] == "flag"
    ] == [[old_ids[0]]]
    assert refreshed["scores"] == {old_ids[0]: {"0": 0.0}}
    assert refreshed["ai_review"] == {}


def test_reset_work_state_reuses_alignment_but_discards_review_markers(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    first = align_documents(str(source), str(target), str(report), model=encoder)
    original_ops = first["ops"]
    stale = load_report(report)
    stale["repair_log"] = [RepairAction.make_flag("L000001", "旧标记").to_dict()]
    stale["ai_review"] = {"status": "completed"}
    stale["scores"] = {"0": 0.1}
    stale["history"] = [{"type": "old"}]
    save_report(stale, report)

    reset = align_documents(
        str(source),
        str(target),
        str(report),
        model=encoder,
        reset_work_state=True,
    )

    assert reset["success"] and reset["cache_hit"]
    assert reset["work_state_reset"]
    assert reset["ops"] == original_ops
    rebuilt = load_report(report)
    assert all(item["kind"] != "flag" for item in rebuilt["repair_log"])
    assert rebuilt["ai_review"] == {}
    assert rebuilt["scores"] == {}
    assert rebuilt["history"] == []


def test_disabling_alignment_reuse_recomputes_and_replaces_old_report(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    assert align_documents(str(source), str(target), str(report), model=encoder)[
        "success"
    ]
    stale = load_report(report)
    stale["ops"] = [{"id": "L000001", "s": [0, 1], "t": [0, 1], "sc": 0.01}]
    stale["repair_log"] = [RepairAction.make_flag("L000001", "旧标记").to_dict()]
    save_report(stale, report)

    rebuilt_result = align_documents(
        str(source),
        str(target),
        str(report),
        model=encoder,
        reset_work_state=True,
        reuse_alignment=False,
    )

    assert rebuilt_result["success"] and not rebuilt_result["cache_hit"]
    rebuilt = load_report(report)
    assert rebuilt["ops"] != stale["ops"]
    assert all(item["kind"] != "flag" for item in rebuilt["repair_log"])


def test_preserved_work_state_repairs_only_unresolved_relations(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    encoder = MockEncoder()
    first = align_documents(str(source), str(target), str(report), model=encoder)
    stale = load_report(report)
    stale["ops"] = [
        {"id": "L000001", "s": [0, 1], "t": [0], "sc": 0.5},
        {"id": "L000002", "s": [], "t": [1], "sc": 0.0},
    ]
    stale["repair_log"] = [
        RepairAction.make_flag("L000001", "仍需人工确认").to_dict(),
        RepairAction.make_ok("L000002").to_dict(),
    ]
    save_report(stale, report)

    result = align_documents(
        str(source),
        str(target),
        str(report),
        model=encoder,
        reset_work_state=True,
        reuse_alignment=True,
        preserve_work_state=True,
    )

    assert result["success"] and result["cache_hit"]
    actions = load_report(report)["repair_log"]
    assert [a["kind"] for a in actions if a["relation_ids"] == ["L000001"]] == [
        "merge",
        "flag",
    ]
    assert [a["kind"] for a in actions if a["relation_ids"] == ["L000002"]] == ["ok"]


def test_reader_rows_are_materialized_on_demand(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "chapter.report.json"
    assert align_documents(str(source), str(target), str(report), model=MockEncoder())[
        "success"
    ]

    source_rows, target_rows = materialize_reader_rows(report, source, target)

    assert len(source_rows) == len(target_rows)
    assert source_rows


def test_empty_document_still_produces_a_replayable_report(tmp_path):
    source = tmp_path / "empty.source.md"
    target = tmp_path / "empty.target.md"
    source.write_text("", encoding="utf-8")
    target.write_text("one\n", encoding="utf-8")
    report = tmp_path / "empty.report.json"

    result = align_documents(str(source), str(target), str(report), model=MockEncoder())

    assert result["success"]
    assert result["quality"] == "unreliable"
    assert json.loads(report.read_text(encoding="utf-8"))["ops"] == [
        {"id": "L000001", "s": [], "t": [0], "sc": 0.0}
    ]
    assert load_report(report)["repair_log"][0]["kind"] == "placeholder_src"


def test_new_default_abstains_when_embedding_calibration_is_unavailable(tmp_path):
    source, target = _pair(tmp_path)
    report = tmp_path / "uncalibrated.report.json"

    result = _align_documents(
        str(source), str(target), str(report), model=MockEncoder()
    )

    assert result["success"]
    assert result["status"] == "rejected"
    assert result["reason"] == "calibration_unavailable"
    assert result["ops"] == []


def test_review_disagreement_is_persisted_as_annotated_flags(tmp_path, monkeypatch):
    source, target = _pair(tmp_path)
    report = tmp_path / "review.report.json"
    ops = [((0,), (0,), 0.9), ((1,), (), 0.0), ((), (1,), 0.0)]
    result = AlignmentResult(
        all_ops=ops,
        stats={"n_source": 2, "n_target": 2},
        status="needs_review",
        uncertain_regions=(((0, 0), (2, 1)),),
        alternative_ops=[((0, 1), (0,), 0.8), ((), (1,), 0.0)],
    )
    monkeypatch.setattr("dualign.services.cli_pipeline.align", lambda *_a, **_k: result)

    saved = _align_documents(str(source), str(target), str(report), model=MockEncoder())

    assert saved["status"] == "needs_review"
    actions = load_report(report)["repair_log"]
    assert [(action["relation_ids"], action["kind"]) for action in actions] == [
        (["L000002"], "flag")
    ]
    assert actions[0]["data"]["reason"] == "composition_disagreement"
    assert actions[0]["data"]["current_structure"] == "1:1+1:0"
    assert actions[0]["data"]["alternative_structure"] == "2:1"

    reset = _align_documents(
        str(source),
        str(target),
        str(report),
        model=MockEncoder(),
        reset_work_state=True,
    )
    reset_actions = load_report(report)["repair_log"]
    assert reset["cache_hit"] is True
    assert [(action["relation_ids"], action["kind"]) for action in reset_actions] == [
        (["L000002"], "flag")
    ]
