from types import SimpleNamespace

from dualign.gui.review import _next_suggestion_ordinal


def _items(*ordinals):
    return [SimpleNamespace(ordinal=ordinal) for ordinal in ordinals]


def test_suggestion_navigation_uses_visible_ai_rows_not_anomaly_filter():
    items = _items(305, 305, 404)

    assert _next_suggestion_ordinal(items, 305, 1) == 404
    assert _next_suggestion_ordinal(items, 404, 1) == 305
    assert _next_suggestion_ordinal(items, 305, -1) == 404


def test_suggestion_navigation_starts_at_directional_edge():
    items = _items(305, 404)

    assert _next_suggestion_ordinal(items, None, 1) == 305
    assert _next_suggestion_ordinal(items, None, -1) == 404
    assert _next_suggestion_ordinal([], None, 1) is None
