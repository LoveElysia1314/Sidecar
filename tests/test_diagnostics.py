from dualign import diagnostics


def test_crash_report_is_durable_and_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "get_cache_root", lambda: str(tmp_path))

    first = diagnostics.write_crash_report("first context", "first traceback")
    second = diagnostics.write_crash_report("second context", "second traceback")

    assert first == second
    content = (tmp_path / "logs" / "dualign-crash.log").read_text(encoding="utf-8")
    assert "first context" in content
    assert "first traceback" in content
    assert "second context" in content
    assert "second traceback" in content
