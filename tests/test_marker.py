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
)


class TestMarkerConstruct:
    def test_basic_kind(self):
        assert from_kind("merge") == "[M]"
        assert from_kind("split") == "[S]"
        assert from_kind("edit") == "[E]"
        assert from_kind("delete") == "[D]"
        assert from_kind("flag") == "[F]"
        assert from_kind("ok") == "[OK]"
        assert from_kind("placeholder_src") == "[P]"

    def test_with_ai_source(self):
        # AI 来源：操作标记加 [AI] 前缀
        assert from_kind("merge", source="ai") == "[AI][M]"
        assert from_kind("edit", source="ai") == "[AI][E]"
        assert from_kind("delete", source="ai") == "[AI][D]"
        assert from_kind("flag", source="ai") == "[AI][F]"
        # AI ok → [AI][OK]（与其他操作一致，不再有裸 [AI] 特例）
        assert from_kind("ok", source="ai") == "[AI][OK]"

    def test_ok_human_source(self):
        # 人类 ok → [OK]
        assert from_kind("ok", source="") == "[OK]"
        assert from_kind("ok", source="user") == "[OK]"

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

    def test_combine_no_duplicate(self):
        assert combine("[M]", "[M]") == "[M]"
        assert combine("[M] [OK]", "[OK]") == "[M] [OK]"

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
        for m in ("[M]", "[S]", "[P]", "[OK]"):
            assert is_resolved_to_11(m)
        for m in ("[E]", "[D]", "[F]"):
            assert not is_resolved_to_11(m)

    def test_has_tag(self):
        assert has_tag("[AI][M]", "[M]") and not has_tag("[M]", "[S]")

    def test_empty_marker(self):
        assert not is_merge("") and not is_approved("")
