from dualign.services.cancellation import CancellationError, CancellationToken


def test_cancellation_invokes_cleanup_once_and_wakes_waiters():
    token = CancellationToken()
    calls = []
    token.register(lambda: calls.append("closed"))

    assert token.cancel()
    assert not token.cancel()
    assert calls == ["closed"]
    assert token.wait(0)

    try:
        token.raise_if_cancelled()
    except CancellationError:
        pass
    else:
        raise AssertionError("cancelled token did not raise")
