"""Reference TokenBucket (oracle). NEVER copied into a contestant's repo."""
from __future__ import annotations

import time
from typing import Callable


class TokenBucket:
    def __init__(
        self, capacity: float, refill_rate: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        self._capacity = float(capacity)
        self._rate = float(refill_rate)
        self._clock = clock
        self._tokens = float(capacity)   # starts full
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last
        self._last = now
        if elapsed > 0 and self._rate > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if cost <= self._tokens:
            self._tokens -= cost
            return True
        return False

    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens
