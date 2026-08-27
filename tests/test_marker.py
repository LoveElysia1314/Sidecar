"""
Dualign — Marker 编解码测试
"""

from dualign.models.marker import (
    from_kind,
    is_merge,
    is_split,
    is_edit,
    is_deleted,
    is_placeholder,
    is_flagged,
    is_approved,
    is_resolved_to_11,
    combine,
    has_tag,
    marker_atoms,
    mark_ai_reviewed,
    without_source_prefixes,
)


class TestMarkerConstruct:
    def test_basic_kind(self):
        assert from_kind("merge") == "[M]"
        assert from_kind("split") == "[S]"
        assert from_kind("edit") == "[E]"
        assert from_kind("delete") == "[D]"
        assert from_kind("flag") == "[F]"
        assert from_kind("ok") == ""
        assert from_kind("placeholder_src") == "[P]"

    def test_unknown_kind(self):
        assert from_kind("invalid") == ""

    def test_combine_ok_preserves_existing_source(self):
        assert combine("[AI][M]", "[OK]") == "[AI][M] [OK]"

    def test_combine_ok_removes_f(self):
        assert combine("[M] [F]", "[OK]") == "[M] [OK]"

    def test_combine_f_removes_ok(self):
        assert combine("[M] [OK]", "[F]") == "[M] [F]"

    def test_combine_flag_preserves_existing_source(self):
        assert combine("[AI][E]", "[F]") == "[AI][E] [F]"
        assert combine("[AI][M]", "[F]") == "[AI][M] [F]"

    def test_combine_ai_meta_keeps_its_source(self):
        assert combine("[M]", "[AI][OK]") == "[M] [AI][OK]"

    def test_ai_review_is_independent_provenance_not_ok(self):
        assert mark_ai_reviewed("[M]") == "[M] [AI]"
        assert marker_atoms("[M] [AI]") == ("[M]", "[AI]")
        assert without_source_prefixes("[M] [AI]") == "[M]"

    def test_ai_review_provenance_is_deduplicated(self):
        assert mark_ai_reviewed("[M] [AI]") == "[M] [AI]"

    def test_replacing_the_reviewed_decision_invalidates_ai_review(self):
        assert combine("[M] [AI]", "[S]") == "[S]"
        assert combine("[M] [AI]", "[OK]") == "[M] [OK]"

    def test_combine_no_duplicate(self):
        assert combine("[M]", "[M]") == "[M]"
        assert combine("[M] [OK]", "[OK]") == "[M] [OK]"

    def test_combine_replaces_the_decision_on_the_same_axis(self):
        assert combine("[AI][M] [F]", "[S]") == "[F] [S]"
        assert combine("[M] [AI][OK]", "[F]") == "[M] [F]"

    def test_combine_normalizes_compact_legacy_markers(self):
        assert combine("[AI][E][OK]", "[F]") == "[AI][E] [F]"

    def test_combine_empty(self):
        assert combine("", "[OK]") == "[OK]"


class TestMarkerSemanticQueries:
    def test_is_merge(self):
        assert is_merge("[M]") and is_merge("[AI][M]")
        assert not is_merge("[S]") and not is_merge("")

    def test_is_split(self):
        assert is_split("[S]") and not is_split("[M]")

    def test_is_edit(self):
        assert is_edit("[E]") and not is_edit("[M]")

    def test_is_deleted(self):
        assert is_deleted("[D]") and not is_deleted("[M]")

    def test_is_placeholder(self):
        assert is_placeholder("[P]") and not is_placeholder("[D]")

    def test_is_flagged(self):
        assert is_flagged("[F]") and not is_flagged("[OK]")

    def test_is_approved(self):
        assert is_approved("[OK]") and not is_approved("[M]")

    def test_is_resolved_to_11(self):
        for m in ("[M]", "[S]", "[P]"):
            assert is_resolved_to_11(m)
        for m in ("[E]", "[D]", "[F]", "[OK]"):
            assert not is_resolved_to_11(m)

    def test_has_tag(self):
        assert has_tag("[AI][M]", "[M]") and not has_tag("[M]", "[S]")

    def test_empty_marker(self):
        assert not is_merge("") and not is_approved("")
