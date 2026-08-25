from pathlib import Path

import pytest

from dualign.services import report_io
from dualign.services.report_io import build_report, load_report, save_report


def _report(tmp_path: Path):
    document_a = tmp_path / "a.md"
    document_b = tmp_path / "b.md"
    document_a.write_text("甲\n", encoding="utf-8")
    document_b.write_text("A\n", encoding="utf-8")
    return build_report(
        chapter_id="pair",
        document_a_path=document_a,
        document_b_path=document_b,
        operations=[((0,), (0,), 0.9)],
        stats={"n_source": 1, "n_target": 1, "n_ops": 1},
        quality={"level": "ok"},
        provenance={"tool": "test"},
    )


def test_save_report_retries_a_transient_replace_denial(tmp_path, monkeypatch):
    target = tmp_path / "pair.report.json"
    save_report(_report(tmp_path), target)
    real_replace = report_io.os.replace
    attempts = []
    delays = []

    def intermittently_locked(source, destination):
        attempts.append((Path(source), Path(destination)))
        if len(attempts) <= 3:
            raise PermissionError(13, "target is temporarily in use", destination)
        real_replace(source, destination)

    monkeypatch.setattr(report_io.os, "replace", intermittently_locked)
    monkeypatch.setattr(report_io.time, "sleep", delays.append)

    updated = _report(tmp_path)
    updated["ai_review"] = {"status": "skipped"}
    save_report(updated, target)

    assert len(attempts) == 4
    assert delays == list(report_io._REPLACE_RETRY_DELAYS[:3])
    assert load_report(target)["ai_review"]["status"] == "skipped"
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_report_reraises_a_persistent_replace_denial(tmp_path, monkeypatch):
    target = tmp_path / "pair.report.json"
    save_report(_report(tmp_path), target)
    attempts = 0

    def persistently_locked(_source, destination):
        nonlocal attempts
        attempts += 1
        raise PermissionError(13, "target remains locked", destination)

    monkeypatch.setattr(report_io.os, "replace", persistently_locked)
    monkeypatch.setattr(report_io.time, "sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="target remains locked"):
        save_report(_report(tmp_path), target)

    assert attempts == len(report_io._REPLACE_RETRY_DELAYS) + 1
    assert list(tmp_path.glob("*.tmp")) == []
