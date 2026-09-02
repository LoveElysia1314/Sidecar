"""Shared runtime limit for the atomic alignment solver."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

ATOMIC_ALIGNMENT_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class _Deadline:
    started_at: float
    expires_at: float
    limit_seconds: float


class AtomicAlignmentTimeout(RuntimeError):
    """Raised cooperatively when atomic alignment exceeds its fixed limit."""

    def __init__(self, phase: str, elapsed_seconds: float, limit_seconds: float):
        super().__init__(f"原子对齐超过 {limit_seconds:.0f} 秒")
        self.phase = phase
        self.elapsed_seconds = elapsed_seconds
        self.limit_seconds = limit_seconds


_CURRENT_DEADLINE: ContextVar[_Deadline | None] = ContextVar(
    "dualign_atomic_deadline", default=None
)


@contextmanager
def atomic_alignment_deadline() -> Iterator[_Deadline]:
    """Apply the fixed product limit to one atomic alignment run."""

    started_at = time.monotonic()
    limit_seconds = float(ATOMIC_ALIGNMENT_TIMEOUT_SECONDS)
    deadline = _Deadline(
        started_at=started_at,
        expires_at=started_at + limit_seconds,
        limit_seconds=limit_seconds,
    )
    token = _CURRENT_DEADLINE.set(deadline)
    try:
        yield deadline
    finally:
        _CURRENT_DEADLINE.reset(token)


def check_atomic_alignment_deadline(phase: str) -> None:
    """Stop the active run after its deadline; do nothing outside a run."""

    deadline = _CURRENT_DEADLINE.get()
    if deadline is None:
        return
    now = time.monotonic()
    if now >= deadline.expires_at:
        raise AtomicAlignmentTimeout(
            phase=phase,
            elapsed_seconds=now - deadline.started_at,
            limit_seconds=deadline.limit_seconds,
        )
