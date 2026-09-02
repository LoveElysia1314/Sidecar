from dualign.services.score_manager import ScoreManager, ScoreWorker


class _Scorer:
    def score_pairs(self, source, target):
        return [len(a) + len(b) for a, b in zip(source, target)]


def test_worker_request_arguments_are_immutable_per_run():
    worker = ScoreWorker(_Scorer())
    emitted = []
    worker.finished.connect(lambda results, seq: emitted.append((results, seq)))

    worker.run([((7, 0), "a", "bb")], 11)
    worker.run([((2, 0), "ccc", "d")], 12)

    assert emitted == [({(7, 0): 3.0}, 11), ({(2, 0): 4.0}, 12)]


def test_full_invalidation_discards_late_relation_results():
    manager = ScoreManager()
    emitted = []
    manager.score_updated.connect(lambda *args: emitted.append(args))
    manager._pending_req[(99, 0)] = 3
    manager._debounced_pairs.append(((99, 0), "old", "text"))

    manager.invalidate()
    manager._on_worker_finished({(99, 0): 0.75}, 3)

    assert emitted == []
    assert manager._debounced_pairs == []
    assert (99, 0) not in manager._cache


def test_batched_results_accept_only_still_pending_keys():
    manager = ScoreManager()
    emitted = []
    manager.score_updated.connect(lambda *args: emitted.append(args))
    manager._pending_req.update({(1, 0): 5, (2, 0): 5})

    manager._on_worker_finished({(1, 0): 0.1, (2, 0): 0.2, (8, 0): 0.8}, 5)

    assert emitted == [(1, 0, 0.1), (2, 0, 0.2)]
    assert (8, 0) not in manager._cache


def test_debounced_relation_batch_gets_a_sequence_distinct_from_flat_preview():
    manager = ScoreManager()
    captured = []
    manager._request_seq = 7
    manager._flat_requests[7] = 200
    manager._pending_req.update({(1, 0): 5, (2, 0): 6})
    manager._debounced_pairs.extend(
        [((1, 0), "old", "old"), ((1, 0), "new", "new"), ((2, 0), "b", "B")]
    )
    manager._do_score_async = lambda pairs, seq: captured.append((pairs, seq))

    manager._flush_pending()

    assert captured == [([((1, 0), "new", "new"), ((2, 0), "b", "B")], 8)]
    assert manager._pending_req == {(1, 0): 8, (2, 0): 8}
    assert manager._flat_requests == {7: 200}


def test_flat_batches_keep_their_own_batch_identity():
    manager = ScoreManager()
    emitted = []
    manager.flat_batch_ready.connect(
        lambda batch_id, scores: emitted.append((batch_id, scores.tolist()))
    )
    manager._flat_requests.update({7: 101, 8: 102})

    manager._on_worker_finished({-1: 0.4}, 7)
    manager._on_worker_finished({-1: 0.6, -2: 0.7}, 8)

    assert emitted == [(101, [0.4]), (102, [0.6, 0.7])]
