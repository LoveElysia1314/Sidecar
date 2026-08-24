"""Dualign GUI public API, loaded lazily by component.

Importing a lightweight component such as ``dualign.gui.dialogs`` must not
initialize the main window and its complete service dependency graph. Besides
reducing startup coupling, lazy exports prevent a long-running host process
from mixing an already-cached service module with newly edited GUI modules.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "DualignWindow": ("dualign.gui.window", "DualignWindow"),
    "BlockEditDialog": ("dualign.gui.dialogs", "BlockEditDialog"),
    "ReviewController": ("dualign.gui.review", "ReviewController"),
    "FilterPanel": ("dualign.gui.filter", "FilterPanel"),
    "RelationIndicator": ("dualign.gui.panels", "RelationIndicator"),
    "DockPanelHelper": ("dualign.gui.panels", "DockPanelHelper"),
    "LogPanel": ("dualign.gui.log_panel", "LogPanel"),
    "HighlightDelegate": ("dualign.gui.base_table", "HighlightDelegate"),
    "score_to_color": ("dualign.gui.base_table", "score_to_color"),
    "type_cl": ("dualign.gui.base_table", "type_cl"),
    "marker_cl": ("dualign.gui.base_table", "marker_cl"),
    "anomaly_cl": ("dualign.gui.base_table", "anomaly_cl"),
    "priority_anomaly_type": (
        "dualign.gui.base_table",
        "priority_anomaly_type",
    ),
    "TYPE_CL_11": ("dualign.gui.base_table", "TYPE_CL_11"),
    "TYPE_CL_10_01": ("dualign.gui.base_table", "TYPE_CL_10_01"),
    "TYPE_CL_NON11": ("dualign.gui.base_table", "TYPE_CL_NON11"),
    "TEXT_CL_NORMAL": ("dualign.gui.base_table", "TEXT_CL_NORMAL"),
    "TEXT_CL_DELETED": ("dualign.gui.base_table", "TEXT_CL_DELETED"),
    "TEXT_CL_CONTEXT": ("dualign.gui.base_table", "TEXT_CL_CONTEXT"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
