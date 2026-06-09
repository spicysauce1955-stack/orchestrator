"""A set of half-open integer intervals [start, end) with merging. (TASK STUB)"""
from __future__ import annotations


class IntervalSet:
    """See README.md for the full contract."""

    def __init__(self) -> None:
        raise NotImplementedError

    def add(self, start: int, end: int) -> None:
        raise NotImplementedError

    def remove(self, start: int, end: int) -> None:
        raise NotImplementedError

    def contains(self, point: int) -> bool:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    @property
    def total(self) -> int:
        raise NotImplementedError
