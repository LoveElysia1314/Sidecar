from dataclasses import dataclass

from dualign.gui.base_table import TYPE_CL_10_01, TYPE_CL_NON11, type_cl
from dualign.services.table_projection import project_table_cells


@dataclass
class Row:
    ordinal: int
    sub: int
    init_type: str
    n_src: int
    n_tgt: int
    marker: str = ""
    display_group_id: object = None


def test_projection_separates_initial_segments_from_current_bundle():
    rows = [
        Row(0, 0, "snap 0\n1:1", 2, 1, "[M]"),
        Row(0, 1, "snap 1\n1:0", 2, 1, "[M]"),
    ]

    projection = project_table_cells(rows, col_offset=1, relation_col=0)

    assert (0, 1) not in projection.spans
    assert (0, 2) not in projection.spans
    assert projection.spans[(0, 3)] == (2, 1)
    assert projection.spans[(0, 4)] == (2, 1)
    assert projection.spans[(0, 6)] == (2, 1)
    assert projection.covered_rows(3) == frozenset({1})
    assert projection.divider_cells == frozenset({(0, 5)})


def test_projection_preserves_independent_current_edit_rows():
    rows = [
        Row(0, 0, "snap 0\n1:1\n---\nsnap 1\n2:1", 2, 2, "[E]"),
        Row(0, 1, "", 2, 2, "[E]"),
    ]

    projection = project_table_cells(rows, col_offset=1, relation_col=0)

    assert projection.spans[(0, 0)] == (2, 1)
    assert projection.spans[(0, 1)] == (2, 1)
    assert projection.spans[(0, 2)] == (2, 1)
    assert (0, 3) not in projection.spans
    assert (0, 4) not in projection.spans
    assert not projection.divider_cells


def test_identical_initial_labels_do_not_fuse_explicit_segments():
    rows = [
        Row(0, 0, "snap 0\n1:1", 2, 2, "[M]"),
        Row(0, 1, "snap 0\n1:1", 2, 2, "[M]"),
    ]

    projection = project_table_cells(rows, col_offset=1, relation_col=0)

    assert (0, 1) not in projection.spans
    assert (0, 2) not in projection.spans


def test_two_suggestions_for_same_snap_remain_separate_display_groups():
    rows = [
        Row(3, 0, "2:1", 2, 1, "[M]", (3, "proposal-a")),
        Row(3, 1, "", 2, 1, "[M]", (3, "proposal-a")),
        Row(3, 0, "1:1", 1, 1, "[E]", (3, "proposal-b")),
    ]

    projection = project_table_cells(rows, col_offset=1, relation_col=0)

    assert projection.spans[(0, 0)] == (2, 1)
    assert (0, 0) not in projection.covered_cells
    assert (2, 0) not in projection.covered_cells


def test_relation_color_reads_semantics_from_bundled_display_label():
    assert type_cl("snap 0\n1:1\n---\nsnap 1\n2:1").name() == TYPE_CL_NON11.name()
    assert type_cl("snap 0\n1:1\n---\nsnap 1\n1:0").name() == TYPE_CL_10_01.name()
