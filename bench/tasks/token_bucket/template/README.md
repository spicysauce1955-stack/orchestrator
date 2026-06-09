# Task: implement `TokenBucket`

Implement the `TokenBucket` class in `token_bucket.py` (the file already has the
signatures). It is a token-bucket rate limiter:

- **Construction.** `TokenBucket(capacity, refill_rate, *, clock=time.monotonic)`. The
  bucket **starts full** (`capacity` tokens). `capacity` must be `> 0` and `refill_rate`
  (tokens per second) must be `>= 0`; otherwise raise `ValueError`.
- **Refill.** Tokens refill continuously at `refill_rate` tokens/second, measured with
  the injected `clock`, and are **capped at `capacity`** (they never exceed it). Refill is
  lazy: compute elapsed time against `clock()` whenever the bucket is queried or used.
- **`allow(cost=1.0)`.** Refill to now, then: if at least `cost` tokens are available,
  consume `cost` and return `True`; otherwise consume nothing and return `False`. A `cost`
  larger than `capacity` can therefore never succeed.
- **`tokens`** (property). Refill to now and return the current token count (a float,
  never above `capacity`).

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite covering all the rules above (refill capping, partial
refills, no-consume-on-deny, fractional costs, validation), so implement the full
contract, not just the smoke tests.
