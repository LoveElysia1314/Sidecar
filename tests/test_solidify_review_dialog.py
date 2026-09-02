import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from dualign.gui.dialogs import SolidifyReviewDialog
from dualign.models.action import RepairAction
from dualign.models.alignment_pair import (
    AlignmentLink,
    AlignmentPair,
    DocumentReference,
)
from dualign.models.pair_editing import PairEditingState
from dualign.services.solidify import SolidifyPolicy, build_solidification_plan


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _plan():
    pair = AlignmentPair(
        id="pair",
        document_a=DocumentReference("a", "a.md"),
        document_b=DocumentReference("b", "b.md"),
        links=(AlignmentLink("L000001", (1,), (1,)),),
    )
    baseline = PairEditingState.from_alignment_pair(pair, "甲\n", "A\n")
    action = RepairAction.make_edit(
        "L000001",
        source="user",
        new_src_lines=["甲校订"],
        new_tgt_lines=["A edited"],
    )
    return build_solidification_plan(
        baseline,
        [action],
        SolidifyPolicy(frozenset({"edit_a", "edit_b"})),
    )


def test_solidify_review_uses_relation_table_and_collapsible_stacked_diffs():
    _app()
    dialog = SolidifyReviewDialog(_plan())

    table = dialog._change_table
    assert table.rowCount() == 1
    assert table.columnCount() == 4
    assert [table.horizontalHeaderItem(column).text() for column in range(4)] == [
        "关系",
        "操作",
        "文档 A 变化",
        "文档 B 变化",
    ]
    assert table.item(0, 0).text() == "L000001"
    assert "校订 [E]" in table.item(0, 1).text()
    assert table.item(0, 2).text() == "− 甲\n+ 甲校订"
    assert table.item(0, 3).text() == "− A\n+ A edited"
    assert dialog.findChildren(QTabWidget) == []

    assert dialog._diff_details.isChecked() is False
    assert dialog._diff_container.isHidden() is True
    assert dialog._diff_splitter.orientation() == Qt.Orientation.Vertical
    assert len(dialog._diff_editors) == 2

    dialog._diff_details.setChecked(True)
    assert dialog._diff_container.isHidden() is False
    assert "文档 A（当前）" in dialog._diff_editors[0].toPlainText()
    assert "文档 B（当前）" in dialog._diff_editors[1].toPlainText()

    dialog.deleteLater()
