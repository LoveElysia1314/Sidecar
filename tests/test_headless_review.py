from __future__ import annotations

import json

import pytest

from dualign.services.headless_review import (
    REVIEW_DECISIONS_SCHEMA,
    apply_review_decisions,
    export_review_bundle,
)
from dualign.services.report_io import build_report, load_report, save_report


def _fixture(tmp_path):
    document_a = tmp_path / "a.md"
    document_b = tmp_path / "b.md"
    report_path = tmp_path / "pair.report.json"
    document_a.write_text("甲\n\n乙\n", encoding="utf-8")
    document_b.write_text("A\n\nB\n", encoding="utf-8")
    report = build_report(
        chapter_id="pair",
        document_a_path=document_a,
        document_b_path=document_b,
        operations=[((0,), (0,), 0.9), ((1,), (1,), 0.8)],
        stats={"n_source": 2, "n_target": 2},
        quality={"level": "ok"},
        provenance={"tool": "test"},
    )
    save_report(report, report_path)
    return document_a, document_b, report_path


def test_headless_review_export_and_hash_bound_apply(tmp_path) -> None:
    document_a, document_b, report_path = _fixture(tmp_path)
    bundle = export_review_bundle(document_a, document_b, report_path)
    decisions = {
        "schema": REVIEW_DECISIONS_SCHEMA,
        "report_sha256": bundle["report_sha256"],
        "reviewer": "test-reviewer",
        "decisions": [
            {"kind": "ok", "relation_ids": [relation["relation_id"]]}
            for relation in bundle["relations"]
        ],
    }

    preview = apply_review_decisions(
        document_a, document_b, report_path, decisions, apply=False
    )
    applied = apply_review_decisions(
        document_a, document_b, report_path, decisions, apply=True
    )
    report = load_report(report_path)

    assert bundle["relations"][0]["source_lines"] == ["甲"]
    assert bundle["relations"][1]["target_lines"] == ["B"]
    assert preview["applied"] is False
    assert applied["reviewed_relation_count"] == 2
    assert report["ai_review"]["reviewer"] == "test-reviewer"
    assert {action["source"] for action in report["repair_log"]} == {"ai"}


def test_headless_review_rejects_stale_report_hash(tmp_path) -> None:
    document_a, document_b, report_path = _fixture(tmp_path)
    decisions = {
        "schema": REVIEW_DECISIONS_SCHEMA,
        "report_sha256": "0" * 64,
        "reviewer": "test-reviewer",
        "decisions": [],
    }

    with pytest.raises(ValueError, match="SHA-256"):
        apply_review_decisions(document_a, document_b, report_path, decisions)


def test_headless_review_rejects_nonconsecutive_merge(tmp_path) -> None:
    document_a, document_b, report_path = _fixture(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["ops"].append({"id": "L000003", "s": [], "t": [], "sc": 0.0})
    # Keep this test focused on decision validation by using the real two relations.
    bundle = export_review_bundle(document_a, document_b, report_path)
    decisions = {
        "schema": REVIEW_DECISIONS_SCHEMA,
        "report_sha256": bundle["report_sha256"],
        "reviewer": "test-reviewer",
        "decisions": [
            {
                "kind": "merge",
                "relation_ids": [
                    bundle["relations"][1]["relation_id"],
                    bundle["relations"][0]["relation_id"],
                ],
            }
        ],
    }

    with pytest.raises(ValueError, match="consecutive"):
        apply_review_decisions(document_a, document_b, report_path, decisions)
