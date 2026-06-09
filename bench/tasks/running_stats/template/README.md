# Task: implement `RunningStats`

Implement the `RunningStats` class in `running_stats.py` (the file already has the
signatures). It accumulates a stream of numbers one at a time and reports summary
statistics that can be queried **at any point** between pushes:

- **`push(x)`.** Add one observation `x` to the stream.
- **`len(stats)`.** The number of observations pushed so far.
- **`mean`** (property). The arithmetic mean of all observations, or `0.0` if none.
- **`variance`** (property). The **population** variance — the mean of the squared
  deviations from the mean, i.e. `sum((x_i - mean)**2) / n`. Return `0.0` if there are
  fewer than 1 observation. The variance must never be negative.
- **`stddev`** (property). The population standard deviation (`sqrt(variance)`).

The statistics must remain **numerically accurate** even for large streams and for data
with a large offset and a small spread (e.g. values near 1e9 that differ only in their
last few digits) — a naive `sum(x*x)/n - mean**2` formula loses all precision and can
even produce a negative variance. Querying after every push must be cheap.

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite covering numerical-stability edge cases (constant data,
large offsets, single/empty streams, interleaved push/query), so implement the full
contract robustly, not just the smoke tests.
