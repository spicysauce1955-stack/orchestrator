# Task: implement `TtlCache`

Implement the `TtlCache` class in `ttl_cache.py` (the file has the signatures and a
`Stats` dataclass already). It is a bounded in-memory cache combining three behaviours:

- **Capacity + LRU.** `TtlCache(capacity)` holds at most `capacity` entries. When a new
  key is inserted and the cache is full, evict the **least-recently-used** entry. Both
  `get` (on a hit) and `set` count as "using" a key. Overwriting an existing key updates
  its value and recency but must **not** evict anything.
- **Per-key TTL.** `set(key, value, ttl=...)` expires the entry `ttl` seconds from now,
  measured with the injected `clock` (default `time.monotonic`). `ttl=None` never expires.
  Expiry is lazy: an expired entry is dropped the next time it is touched (`get`, `set`,
  or `len`). A `get` on an expired key returns `None` and is a miss.
- **Stats.** The `stats` property exposes counters: `hits`, `misses`,
  `ttl_evictions` (entries dropped due to expiry), and `capacity_evictions` (live
  entries evicted to make room). `capacity=0` is legal — nothing is stored and every new
  insert is a capacity eviction.

`get` returns the value, or `None` if the key is absent or expired. `len(cache)` returns
the number of live (non-expired) entries.

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite covering all the rules above, so implement the full
contract, not just the smoke tests.
