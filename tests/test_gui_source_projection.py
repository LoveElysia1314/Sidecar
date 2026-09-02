import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dualign.gui.base_table import marker_cl, source_cl, text_color_for_side
from dualign.gui.preview_table import AiSuggestionItem, SuggestionPreviewTable
from dualign.gui.review import ReviewController
from dualign.gui.window import COLUMN_HEADERS as WINDOW_HEADERS
from dualign.gui.window_table import COLUMN_HEADERS as RENDER_HEADERS
from dualign.models.action import RepairAction
from dualign.services.repair import RepairState


def test_alignment_tables_share_the_effective_source_column():
    assert WINDOW_HEADERS == RENDER_HEADERS
    assert WINDOW_HEADERS == [
        "关系",
        "初始类型",
        "初始评分",
        "来源",
        "当前状态",
        "当前评分",
        "文档 A",
        "文档 B",
    ]


def test_suggestion_preview_renders_operation_and_source_separately():
    app = QApplication.instance() or QApplication([])
    action = RepairAction.make_edit("L000001", source="ai", new_tgt_lines=["revised"])
    widget = SuggestionPreviewTable()
    widget.set_items(
        [
            AiSuggestionItem(
                0,
                action,
                src_line="原文",
                tgt_line="revised",
                init_type="1:1",
                cur_type="1:1",
                effective_source="ai",
            )
        ]
    )

    assert widget.table.columnCount() == 8
    assert widget.table.item(0, 3).text() == "ai"
    assert widget.table.item(0, 4).text() == "[E]"
    assert widget.table.item(0, 6).text() == "原文"
    assert widget.table.item(0, 7).text() == "revised"

    widget.close()
    app.processEvents()


def test_bundle_preview_does_not_span_over_later_short_side_text():
    app = QApplication.instance() or QApplication([])
    action = RepairAction.make_merge(("L000364", "L000365"), source="ai", sub_count=2)
    widget = SuggestionPreviewTable()
    widget.set_items(
        [
            AiSuggestionItem(
                363,
                action,
                sub=0,
                src_line="专长",
                tgt_line="",
                init_type="关系 363\n1:0",
                n_src=2,
                n_tgt=1,
            ),
            AiSuggestionItem(
                363,
                action,
                sub=1,
                src_line="无特别专长。",
                tgt_line="Special skills: None in particular.",
                init_type="关系 364\n1:1",
                n_src=2,
                n_tgt=1,
            ),
        ]
    )

    assert widget.table.rowSpan(0, 7) == 1
    assert widget.table.item(1, 7).text() == "Special skills: None in particular."

    widget.close()
    app.processEvents()


def test_flag_preview_preserves_the_existing_effective_source():
    state = RepairState.from_ops([((0,), (0,), 0.9)], ["原文"], ["target"])
    state = state.apply(RepairAction.make_ok("L000001", source="user"))
    flag = RepairAction.make_flag("L000001", "recheck", source="ai")

    rows = ReviewController._compute_action_preview(flag, state.snapshot, state)

    assert rows is not None
    assert rows[0][8] == "user"


def test_source_colors_are_categorical_and_approval_green_is_separate():
    source_colors = {
        source_cl(value).name() for value in ("none", "auto", "ai", "user")
    }

    assert len(source_colors) == 4
    assert marker_cl("[OK]", "user").name() == "#4caf50"
    assert marker_cl("[OK]", "ai").name() == "#81c784"
    assert source_cl("user").name() != marker_cl("[OK]", "user").name()


def test_user_ok_colors_both_text_sides_when_stacked_with_an_operation():
    marker = "[E] [OK]"

    src = text_color_for_side(True, True, False, False, False, marker, set(), "user")
    tgt = text_color_for_side(False, True, False, False, False, marker, set(), "user")

    assert src.name() == "#4caf50"
    assert tgt.name() == "#4caf50"
