"""Bounded in-memory cache: per-key TTL + LRU eviction + stats. (TASK STUB)"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Hashable


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    ttl_evictions: int = 0       # entries removed because they expired
    capacity_evictions: int = 0  # live entries removed to make room for a new key


class TtlCache:
    """See README.md for the full contract."""

    def __init__(self, capacity: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        raise NotImplementedError

    def set(self, key: Hashable, value: Any, *, ttl: float | None = None) -> None:
        raise NotImplementedError

    def get(self, key: Hashable) -> Any | None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    @property
    def stats(self) -> Stats:
        raise NotImplementedError
