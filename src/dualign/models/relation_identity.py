"""Stable identities for alignment relations.

Relation IDs identify relations across serialization and editing.  Operation
indices are only the current ordered projection of those relations.
"""

from __future__ import annotations

from collections.abc import Iterable
import re


def relation_id_for_position(position: int) -> str:
    """Return the deterministic compatibility ID for an ordered position."""

    if position < 0:
        raise ValueError("关系位置不能为负数")
    return f"L{position + 1:06d}"


def normalize_relation_ids(
    count: int, relation_ids: Iterable[str] = ()
) -> tuple[str, ...]:
    """Validate IDs or create compatibility IDs for legacy positional data."""

    if count < 0:
        raise ValueError("关系数量不能为负数")
    supplied = tuple(str(value).strip() for value in relation_ids)
    if not supplied:
        return tuple(relation_id_for_position(index) for index in range(count))
    if len(supplied) != count:
        raise ValueError("关系 ID 数量与对齐关系数量不一致")
    if any(not value for value in supplied):
        raise ValueError("关系 ID 不能为空")
    if len(set(supplied)) != len(supplied):
        raise ValueError("关系 ID 必须唯一")
    return supplied


def rebase_relation_ids(
    relation_ids: Iterable[str],
    old_to_new: Iterable[int | None],
    new_count: int,
) -> tuple[str, ...]:
    """Preserve exactly mapped identities and allocate IDs for new relations."""

    old_ids = tuple(str(value).strip() for value in relation_ids)
    mapping = tuple(old_to_new)
    normalize_relation_ids(len(old_ids), old_ids)
    if len(mapping) != len(old_ids):
        raise ValueError("关系映射数量与旧关系数量不一致")
    if new_count < 0:
        raise ValueError("新关系数量不能为负数")

    rebased: list[str | None] = [None] * new_count
    for old_id, new_position in zip(old_ids, mapping):
        if new_position is None:
            continue
        if not 0 <= new_position < new_count:
            raise ValueError("关系映射超出新关系范围")
        if rebased[new_position] is not None:
            raise ValueError("多个旧关系不能映射到同一新关系")
        rebased[new_position] = old_id

    used = set(old_ids)
    serial = max(
        (
            int(match.group(1))
            for value in used
            if (match := re.fullmatch(r"L(\d+)", value))
        ),
        default=0,
    )
    for position, value in enumerate(rebased):
        if value is not None:
            continue
        while True:
            serial += 1
            candidate = f"L{serial:06d}"
            if candidate not in used:
                break
        rebased[position] = candidate
        used.add(candidate)
    return tuple(value for value in rebased if value is not None)
