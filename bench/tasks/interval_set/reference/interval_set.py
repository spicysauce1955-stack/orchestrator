"""Reference IntervalSet (oracle). NEVER copied into a contestant's repo."""
from __future__ import annotations


class IntervalSet:
    def __init__(self) -> None:
        # sorted, disjoint, non-adjacent list of [start, end) half-open intervals
        self._iv: list[list[int]] = []

    def add(self, start: int, end: int) -> None:
        if start >= end:
            return
        merged = [start, end]
        result: list[list[int]] = []
        for s, e in self._iv:
            if e < merged[0] or s > merged[1]:   # disjoint AND non-adjacent
                result.append([s, e])
            else:                                # overlapping or adjacent -> absorb
                merged[0] = min(merged[0], s)
                merged[1] = max(merged[1], e)
        result.append(merged)
        result.sort()
        self._iv = result

    def remove(self, start: int, end: int) -> None:
        if start >= end:
            return
        result: list[list[int]] = []
        for s, e in self._iv:
            if e <= start or s >= end:           # no overlap
                result.append([s, e])
                continue
            if s < start:                        # left fragment survives
                result.append([s, start])
            if e > end:                          # right fragment survives
                result.append([end, e])
        result.sort()
        self._iv = result

    def contains(self, point: int) -> bool:
        return any(s <= point < e for s, e in self._iv)

    def __len__(self) -> int:
        return len(self._iv)

    @property
    def total(self) -> int:
        return sum(e - s for s, e in self._iv)
