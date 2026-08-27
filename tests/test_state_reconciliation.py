from dualign.services.state_reconciliation import (
    map_relations,
    reconcile_relation_state,
    relation_fingerprints,
)


def _action(relation_id, kind="flag"):
    return {
        "kind": kind,
        "source": "user",
        "data": {"note": relation_id},
        "timestamp": "2026-01-01T00:00:00",
        "relation_ids": [relation_id],
    }


def test_fingerprint_ignores_position_and_score():
    old_lines_a = ["甲"]
    old_lines_b = ["A"]
    new_lines_a = ["前言", "甲"]
    new_lines_b = ["Preface", "A"]

    old = relation_fingerprints([((0,), (0,), 0.999999)], old_lines_a, old_lines_b)
    new = relation_fingerprints([((1,), (1,), 0.125)], new_lines_a, new_lines_b)

    assert old == new


def test_one_punctuation_change_invalidates_only_its_relation():
    old_a = ["甲。", "乙。", "丙。"]
    new_a = ["甲。", "乙！", "丙。"]
    lines_b = ["A.", "B.", "C."]
    operations = [((index,), (index,), 0.9) for index in range(3)]

    mapping = map_relations(
        operations,
        operations,
        relation_fingerprints(operations, old_a, lines_b),
        relation_fingerprints(operations, new_a, lines_b),
    )

    assert mapping == (0, None, 2)


def test_duplicate_content_is_ambiguous_unless_documents_are_identical():
    lines_a = ["分隔", "分隔"]
    lines_b = ["*", "*"]
    operations = [((0,), (0,), 1.0), ((1,), (1,), 1.0)]
    fingerprints = relation_fingerprints(operations, lines_a, lines_b)

    assert map_relations(operations, operations, fingerprints, fingerprints) == (
        None,
        None,
    )
    assert map_relations(
        operations,
        operations,
        fingerprints,
        fingerprints,
        positional_identity=True,
    ) == (0, 1)


def test_reconciliation_moves_all_relation_owned_state_together():
    old_a = ["甲。", "乙。", "丙。"]
    new_a = ["甲。", "乙！", "丙。"]
    lines_b = ["A.", "B.", "C."]
    operations = [((index,), (index,), 0.9) for index in range(3)]
    ids = ("R-a", "R-b", "R-c")
    proposals = {
        relation_id: [
            {
                "action": _action(relation_id, "ok"),
                "status": "pending",
                "summary": relation_id,
            }
        ]
        for relation_id in ids
    }
    scores = {relation_id: {"0": index / 10} for index, relation_id in enumerate(ids)}

    result = reconcile_relation_state(
        source_operations=operations,
        source_relation_ids=ids,
        source_fingerprints=relation_fingerprints(operations, old_a, lines_b),
        target_operations=operations,
        target_fingerprints=relation_fingerprints(operations, new_a, lines_b),
        repair_log=[_action(relation_id) for relation_id in ids],
        ai_proposals=proposals,
        scores=scores,
        cause="test",
    )

    assert result.relation_map == (0, None, 2)
    assert result.relation_ids[0] == "R-a"
    assert result.relation_ids[2] == "R-c"
    assert result.relation_ids[1] not in ids
    assert [item["relation_ids"] for item in result.repair_log] == [
        ["R-a"],
        ["R-c"],
    ]
    assert set(result.ai_proposals) == {"R-a", "R-c"}
    assert set(result.scores) == {"R-a", "R-c"}
    assert result.audit["preserved_relations"] == 2
    assert result.audit["invalidated_relations"] == 1
