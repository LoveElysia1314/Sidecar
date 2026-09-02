"""File-list toolbar actions must not depend on QPushButton.clicked arguments."""

from dualign.gui.workspace import WorkspacePanel


class _SignalRecorder:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class _WorkspaceHarness:
    def __init__(self):
        self.chapter_nav_requested = _SignalRecorder()
        self.remove_calls = 0

    def remove_selected(self):
        self.remove_calls += 1


def test_chapter_buttons_emit_unambiguous_directions():
    panel = _WorkspaceHarness()

    WorkspacePanel._on_prev_chapter(panel)
    WorkspacePanel._on_next_chapter(panel)

    assert panel.chapter_nav_requested.values == [-1, 1]


def test_remove_button_uses_the_shared_remove_operation():
    panel = _WorkspaceHarness()

    WorkspacePanel._on_remove_selected(panel)

    assert panel.remove_calls == 1
