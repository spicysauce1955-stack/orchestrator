"""Reference TtlCache (oracle). NEVER copied into a contestant's repo."""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Hashable


@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    ttl_evictions: int = 0
    capacity_evictions: int = 0


class TtlCache:
    def __init__(self, capacity: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if capacity < 0:
            raise ValueError("capacity must be >= 0")
        self._capacity = capacity
        self._clock = clock
        # key -> (value, expiry_or_None); ordered oldest→newest (LRU at the front)
        self._data: OrderedDict[Hashable, tuple[Any, float | None]] = OrderedDict()
        self._stats = Stats()

    def _is_expired(self, expiry: float | None) -> bool:
        return expiry is not None and self._clock() >= expiry

    def _purge_all_expired(self) -> None:
        for k in [k for k, (_, exp) in self._data.items() if self._is_expired(exp)]:
            del self._data[k]
            self._stats.ttl_evictions += 1

    def get(self, key: Hashable) -> Any | None:
        if key in self._data:
            value, expiry = self._data[key]
            if self._is_expired(expiry):
                del self._data[key]
                self._stats.ttl_evictions += 1
                self._stats.misses += 1
                return None
            self._data.move_to_end(key)
            self._stats.hits += 1
            return value
        self._stats.misses += 1
        return None

    def set(self, key: Hashable, value: Any, *, ttl: float | None = None) -> None:
        expiry = None if ttl is None else self._clock() + ttl
        if key in self._data:                      # overwrite: refresh, never evict
            self._data[key] = (value, expiry)
            self._data.move_to_end(key)
            return
        if self._capacity == 0:
            self._stats.capacity_evictions += 1
            return
        self._purge_all_expired()
        if len(self._data) >= self._capacity:
            oldest = next(iter(self._data))
            del self._data[oldest]
            self._stats.capacity_evictions += 1
        self._data[key] = (value, expiry)
        self._data.move_to_end(key)

    def __len__(self) -> int:
        self._purge_all_expired()
        return len(self._data)

    @property
    def stats(self) -> Stats:
        return self._stats
