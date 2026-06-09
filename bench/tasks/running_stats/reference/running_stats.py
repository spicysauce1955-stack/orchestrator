"""Reference RunningStats (oracle). NEVER copied into a contestant's repo.

Welford's online algorithm — numerically stable population variance.
"""
from __future__ import annotations

import math


class RunningStats:
    def __init__(self) -> None:
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0   # sum of squared deviations from the running mean

    def push(self, x: float) -> None:
        x = float(x)
        self._n += 1
        delta = x - self._mean
        self._mean += delta / self._n
        delta2 = x - self._mean
        self._m2 += delta * delta2

    def __len__(self) -> int:
        return self._n

    @property
    def mean(self) -> float:
        return self._mean if self._n else 0.0

    @property
    def variance(self) -> float:
        # population variance; never negative
        return self._m2 / self._n if self._n else 0.0

    @property
    def stddev(self) -> float:
        return math.sqrt(self.variance)
