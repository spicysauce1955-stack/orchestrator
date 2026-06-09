"""Streaming mean / variance / standard deviation. (TASK STUB)"""
from __future__ import annotations


class RunningStats:
    """See README.md for the full contract."""

    def __init__(self) -> None:
        raise NotImplementedError

    def push(self, x: float) -> None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    @property
    def mean(self) -> float:
        raise NotImplementedError

    @property
    def variance(self) -> float:
        raise NotImplementedError

    @property
    def stddev(self) -> float:
        raise NotImplementedError
