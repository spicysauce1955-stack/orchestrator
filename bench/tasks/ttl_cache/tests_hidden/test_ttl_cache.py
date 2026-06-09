"""Held-out grader for TtlCache. NEVER copied into a contestant's repo."""
from __future__ import annotations

import pytest

from ttl_cache import Stats, TtlCache


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_set_get_roundtrip_and_hit_miss_stats():
    c = TtlCache(capacity=2)
    assert c.get("a") is None          # miss
    c.set("a", 1)
    assert c.get("a") == 1             # hit
    assert c.stats.hits == 1
    assert c.stats.misses == 1


def test_len_counts_live_entries():
    c = TtlCache(capacity=3)
    c.set("a", 1)
    c.set("b", 2)
    assert len(c) == 2


def test_overwrite_updates_value_and_does_not_evict():
    c = TtlCache(capacity=1)
    c.set("a", 1)
    c.set("a", 2)                      # overwrite, must not evict
    assert c.get("a") == 2
    assert len(c) == 1
    assert c.stats.capacity_evictions == 0


def test_capacity_eviction_removes_lru_live_entry():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)                      # evicts LRU "a"
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3
    assert c.stats.capacity_evictions == 1


def test_get_refreshes_lru_recency():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1             # "a" now MRU, so "b" is LRU
    c.set("c", 3)                      # evicts "b", not "a"
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.stats.capacity_evictions == 1


def test_set_existing_key_refreshes_recency():
    c = TtlCache(capacity=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 11)                     # "a" now MRU
    c.set("c", 3)                      # evicts LRU "b"
    assert c.get("a") == 11
    assert c.get("b") is None


def test_ttl_lazy_expiry_on_get_counts_miss_and_ttl_eviction():
    clk = FakeClock()
    c = TtlCache(capacity=2, clock=clk)
    c.set("a", 1, ttl=10)
    clk.advance(10)                    # now expired (>= expiry)
    assert c.get("a") is None
    assert c.stats.misses == 1
    assert c.stats.ttl_evictions == 1
    assert c.stats.hits == 0


def test_ttl_none_never_expires():
    clk = FakeClock()
    c = TtlCache(capacity=2, clock=clk)
    c.set("a", 1)                      # no ttl
    clk.advance(1_000_000)
    assert c.get("a") == 1
    assert c.stats.ttl_evictions == 0


def test_len_purges_expired_and_counts_ttl_eviction():
    clk = FakeClock()
    c = TtlCache(capacity=3, clock=clk)
    c.set("a", 1, ttl=5)
    c.set("b", 2)                      # no ttl
    clk.advance(5)
    assert len(c) == 1                 # "a" purged
    assert c.stats.ttl_evictions == 1


def test_set_purges_expired_before_capacity_eviction():
    clk = FakeClock()
    c = TtlCache(capacity=2, clock=clk)
    c.set("a", 1, ttl=5)
    c.set("b", 2)                      # live, no ttl
    clk.advance(5)                     # "a" expired
    c.set("c", 3)                      # expired "a" purged (ttl), room exists, no capacity evict
    assert c.stats.ttl_evictions == 1
    assert c.stats.capacity_evictions == 0
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_capacity_zero_stores_nothing_and_counts_capacity_eviction():
    c = TtlCache(capacity=0)
    c.set("a", 1)
    assert c.get("a") is None
    assert len(c) == 0
    assert c.stats.capacity_evictions == 1


def test_negative_capacity_raises():
    with pytest.raises(ValueError):
        TtlCache(capacity=-1)
