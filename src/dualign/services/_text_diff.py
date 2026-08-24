"""Small text-diff primitive shared by review and solidification flows."""

from __future__ import annotations

import difflib


def _format_range(start: int, stop: int) -> str:
    beginning = start + 1
    length = stop - start
    if length == 1:
        return str(beginning)
    if not length:
        beginning -= 1
    return f"{beginning},{length}"


def unified_text_diff(
    before: str,
    after: str,
    before_name: str,
    after_name: str,
) -> str:
    """Return a line-level unified diff without difflib's autojunk heuristic.

    Repeated lines are common in long literary documents.  Treating them as
    junk can turn a local edit into an apparent block replacement.
    """

    if before == after:
        return ""
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    output = [f"--- {before_name}\n", f"+++ {after_name}\n"]
    for group in matcher.get_grouped_opcodes(3):
        first, last = group[0], group[-1]
        output.append(
            f"@@ -{_format_range(first[1], last[2])} "
            f"+{_format_range(first[3], last[4])} @@\n"
        )
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                output.extend(" " + line for line in before_lines[i1:i2])
            elif tag in {"replace", "delete"}:
                output.extend("-" + line for line in before_lines[i1:i2])
            if tag in {"replace", "insert"}:
                output.extend("+" + line for line in after_lines[j1:j2])
    return "".join(output)
