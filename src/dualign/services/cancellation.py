"""Cooperative cancellation shared by long-running Dualign services."""

from __future__ import annotations

import threading
from collections.abc import Callable


class CancellationError(RuntimeError):
    """Raised when a caller explicitly cancels an operation."""


class CancellationToken:
    """Thread-safe cancellation signal with resource cleanup callbacks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: set[Callable[[], None]] = set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> bool:
        """Cancel once and invoke every currently registered cleanup callback."""
        with self._lock:
            if self._event.is_set():
                return False
            self._event.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
        return True

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register cleanup and return an idempotent unregister function."""
        with self._lock:
            if self._event.is_set():
                invoke_now = True
            else:
                self._callbacks.add(callback)
                invoke_now = False
        if invoke_now:
            callback()

        def unregister() -> None:
            with self._lock:
                self._callbacks.discard(callback)

        return unregister

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancellationError("操作已由用户取消")

    def wait(self, timeout: float) -> bool:
        """Wait for cancellation; return ``True`` when cancellation wins."""
        return self._event.wait(timeout)
