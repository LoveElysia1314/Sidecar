"""Small dependency-free helpers shared by Dualign front ends."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def content_hash(lines: list) -> str:
    """Hash an already segmented line sequence."""

    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def instruction_hash(instruction: str) -> str:
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()[:16]


def normalize_document_text(text: str) -> str:
    """Normalize transport details without changing document content."""

    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def document_sha256_from_text(text: str) -> str:
    return hashlib.sha256(normalize_document_text(text).encode("utf-8")).hexdigest()


def file_bytes_sha256(path: str | os.PathLike[str]) -> str:
    """Hash a file exactly as stored, or return empty for a missing path."""

    source = Path(path)
    if not source.is_file():
        return ""
    return hashlib.sha256(source.read_bytes()).hexdigest()


def file_identity_changed(
    path: str | os.PathLike[str],
    *,
    expected_exists: bool | None,
    expected_sha256: str = "",
) -> bool:
    """Compare a file with the existence and byte identity previously observed."""

    source = Path(path)
    exists = source.is_file()
    if expected_exists is not None and exists != expected_exists:
        return True
    return bool(expected_sha256 and file_bytes_sha256(source) != expected_sha256)


@dataclass
class FilePair:
    """One neutral two-document entry for the GUI."""

    entry_id: str
    label: str
    document_a_path: str
    document_b_path: str
    report_path: str = ""
    document_a_id: str = ""
    document_b_id: str = ""
    language_a: str = ""
    language_b: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def load_text_lines(path: str) -> list[str]:
    """Load non-empty content lines, matching content-line segmentation."""

    try:
        with open(path, "r", encoding="utf-8-sig") as stream:
            return [line.strip() for line in stream if line.strip()]
    except (FileNotFoundError, OSError):
        return []


def format_markdown_output(lines: list[str]) -> str:
    """Serialize logical reader rows with unambiguous blank separators."""

    return "\n\n".join(lines) + ("\n" if lines else "")
