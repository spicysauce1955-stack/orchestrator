"""Held-out grader for TokenBucket. NEVER copied into a contestant's repo."""
from __future__ import annotations

import pytest

from token_bucket import TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_starts_full():
    c = FakeClock()
    b = TokenBucket(capacity=10, refill_rate=1, clock=c)
    assert b.tokens == 10


def test_allow_consumes_tokens():
    c = FakeClock()
    b = TokenBucket(capacity=5, refill_rate=0, clock=c)
    assert b.allow(2) is True
    assert b.tokens == 3


def test_deny_does_not_consume():
    c = FakeClock()
    b = TokenBucket(capacity=5, refill_rate=0, clock=c)
    assert b.allow(3) is True          # 2 left
    assert b.allow(3) is False         # not enough; no consumption
    assert b.tokens == 2


def test_refill_over_time():
    c = FakeClock()
    b = TokenBucket(capacity=10, refill_rate=2, clock=c)  # 2 tokens/sec
    assert b.allow(10) is True         # empty
    assert b.tokens == 0
    c.advance(3)                       # +6 tokens
    assert b.tokens == 6


def test_refill_capped_at_capacity():
    c = FakeClock()
    b = TokenBucket(capacity=4, refill_rate=5, clock=c)
    b.allow(4)                         # empty
    c.advance(100)                     # would be 500 tokens, capped at 4
    assert b.tokens == 4


def test_cost_larger_than_capacity_never_allows():
    c = FakeClock()
    b = TokenBucket(capacity=3, refill_rate=1, clock=c)
    c.advance(1000)                    # full (capped at 3)
    assert b.allow(4) is False


def test_partial_refill_allows_after_wait():
    c = FakeClock()
    b = TokenBucket(capacity=10, refill_rate=1, clock=c)
    assert b.allow(10) is True         # empty
    assert b.allow(1) is False         # nothing yet
    c.advance(1)                       # +1 token
    assert b.allow(1) is True


def test_fractional_cost_and_tokens():
    c = FakeClock()
    b = TokenBucket(capacity=1.0, refill_rate=0.5, clock=c)
    assert b.allow(0.5) is True
    assert b.tokens == pytest.approx(0.5)
    c.advance(1)                       # +0.5
    assert b.tokens == pytest.approx(1.0)


def test_zero_refill_rate_never_refills():
    c = FakeClock()
    b = TokenBucket(capacity=2, refill_rate=0, clock=c)
    b.allow(2)
    c.advance(1000)
    assert b.tokens == 0


def test_invalid_capacity_raises():
    with pytest.raises(ValueError):
        TokenBucket(capacity=0, refill_rate=1)


def test_invalid_refill_rate_raises():
    with pytest.raises(ValueError):
        TokenBucket(capacity=1, refill_rate=-1)
