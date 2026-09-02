"""Persistent scores keyed by stable relation identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class RelationScoreCache:
    """Scores for current relation subrows, independent of ordered positions."""

    values: dict[tuple[str, int], float] = field(default_factory=dict)

    def clear(self) -> None:
        self.values.clear()

    def get(self, relation_id: str, sub: int) -> float | None:
        return self.values.get((relation_id, sub))

    def set(self, relation_id: str, sub: int, score: float) -> None:
        if not relation_id:
            raise ValueError("评分必须绑定关系 ID")
        if sub < 0:
            raise ValueError("评分子行不能为负数")
        self.values[(relation_id, sub)] = float(score)

    def discard(self, relation_id: str, sub: int | None = None) -> None:
        if sub is not None:
            self.values.pop((relation_id, sub), None)
            return
        for key in tuple(self.values):
            if key[0] == relation_id:
                self.values.pop(key, None)

    def retain(
        self,
        relation_ids: set[str],
        *,
        excluding: set[str] | frozenset[str] = frozenset(),
    ) -> RelationScoreCache:
        return RelationScoreCache(
            {
                key: score
                for key, score in self.values.items()
                if key[0] in relation_ids and key[0] not in excluding
            }
        )

    def to_dict(self) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for (relation_id, sub), score in sorted(self.values.items()):
            result.setdefault(relation_id, {})[str(sub)] = score
        return result

    @classmethod
    def from_dict(
        cls,
        raw: object,
        relation_ids: tuple[str, ...] = (),
    ) -> RelationScoreCache:
        """Read current nested data or legacy ``snap_sub`` flat keys."""

        cache = cls()
        if not isinstance(raw, Mapping):
            return cache
        for raw_key, raw_value in raw.items():
            key = str(raw_key)
            if isinstance(raw_value, Mapping):
                for raw_sub, raw_score in raw_value.items():
                    try:
                        cache.set(key, int(raw_sub), float(raw_score))
                    except (TypeError, ValueError):
                        continue
                continue

            ordinal, separator, raw_sub = key.partition("_")
            if not separator:
                continue
            try:
                relation_id = relation_ids[int(ordinal)]
                cache.set(relation_id, int(raw_sub), float(raw_value))
            except (IndexError, TypeError, ValueError):
                continue
        return cache
