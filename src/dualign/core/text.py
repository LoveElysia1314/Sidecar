"""Small text and relation-label helpers shared by alignment workflows."""

from __future__ import annotations

from collections.abc import Sequence


def op_type_str(source: Sequence[int], target: Sequence[int]) -> str:
    """Return the structural cardinality label for one relation."""

    return f"{len(source)}:{len(target)}"


def smart_join_lines(lines: Sequence[str], separator: str | None = None) -> str:
    """Join logical lines while avoiding spaces after CJK punctuation/text."""

    if not lines:
        return ""
    result = lines[0].rstrip()
    for following in lines[1:]:
        following = following.strip()
        if not following:
            continue
        if separator is not None:
            result += separator + following
            continue
        if not result:
            result = following
            continue
        last = result[-1]
        is_cjk = (
            "\u4e00" <= last <= "\u9fff"
            or "\u3000" <= last <= "\u303f"
            or "\uff00" <= last <= "\uffef"
            or "\u3400" <= last <= "\u4dbf"
        )
        result += following if is_cjk else " " + following
    return result
