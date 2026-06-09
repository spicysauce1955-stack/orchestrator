"""Token-bucket rate limiter with an injected clock. (TASK STUB)"""
from __future__ import annotations

import time
from typing import Callable


class TokenBucket:
    """See README.md for the full contract."""

    def __init__(
        self, capacity: float, refill_rate: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        raise NotImplementedError

    def allow(self, cost: float = 1.0) -> bool:
        raise NotImplementedError

    @property
    def tokens(self) -> float:
        raise NotImplementedError
