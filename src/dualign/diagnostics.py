"""Durable diagnostics for GUI processes without an attached console."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import threading

from dualign.config import get_cache_root

_WRITE_LOCK = threading.Lock()


def write_crash_report(context: str, traceback_text: str) -> str:
    """Append a traceback to the user cache and return the log path.

    GUI integrations commonly launch Dualign through ``QProcess`` without a
    visible console.  Stderr remains useful, but it cannot be the only durable
    destination for a traceback.
    """

    try:
        log_dir = Path(get_cache_root()) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "dualign-crash.log"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        entry = (
            f"\n{'=' * 72}\n"
            f"{timestamp}  pid={os.getpid()}  {context}\n"
            f"{'-' * 72}\n"
            f"{traceback_text.rstrip()}\n"
        )
        with _WRITE_LOCK, path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(entry)
        return str(path)
    except OSError:
        return ""
