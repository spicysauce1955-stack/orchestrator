# Task: implement `IntervalSet`

Implement the `IntervalSet` class in `interval_set.py` (the file already has the
signatures). It maintains a set of **half-open integer intervals** `[start, end)` (start
inclusive, end exclusive), always kept as a minimal collection of **disjoint,
non-adjacent** intervals:

- **`add(start, end)`.** Add the interval `[start, end)`, merging it with any existing
  intervals it **overlaps or is adjacent to** (e.g. `[1, 3)` and `[3, 5)` merge into
  `[1, 5)`). An empty or invalid interval (`start >= end`) is a no-op.
- **`remove(start, end)`.** Remove the range `[start, end)` from the set, trimming or
  **splitting** existing intervals as needed (removing the middle of an interval leaves
  two). `start >= end` is a no-op.
- **`contains(point)`.** Return `True` if `point` lies in some interval — i.e. some
  `[s, e)` with `s <= point < e`.
- **`len(set)`.** The number of disjoint intervals currently stored.
- **`total`** (property). The total covered length, `sum(end - start)` over the stored
  intervals.

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite covering all the rules above (adjacency merging, removal
splitting, half-open boundaries, `len`/`total`, no-op edge cases), so implement the full
contract, not just the smoke tests.
