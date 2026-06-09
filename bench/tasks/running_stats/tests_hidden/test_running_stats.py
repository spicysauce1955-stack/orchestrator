"""Held-out grader for RunningStats. NEVER copied into a contestant's repo."""
from __future__ import annotations

import math

from running_stats import RunningStats


def _fill(values):
    s = RunningStats()
    for v in values:
        s.push(v)
    return s


def test_mean_and_len():
    s = _fill([2, 4, 4, 4, 5, 5, 7, 9])
    assert len(s) == 8
    assert math.isclose(s.mean, 5.0, rel_tol=0, abs_tol=1e-9)


def test_population_variance_and_stddev():
    s = _fill([2, 4, 4, 4, 5, 5, 7, 9])      # classic: pop var 4, stddev 2
    assert math.isclose(s.variance, 4.0, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(s.stddev, 2.0, rel_tol=1e-9, abs_tol=1e-9)


def test_empty_stream():
    s = RunningStats()
    assert len(s) == 0
    assert s.mean == 0.0
    assert s.variance == 0.0
    assert s.stddev == 0.0


def test_single_value():
    s = _fill([42.0])
    assert s.mean == 42.0
    assert s.variance == 0.0
    assert s.stddev == 0.0


def test_constant_data_variance_is_zero_not_negative():
    # The naive sum(x*x)/n - mean**2 formula yields a tiny NEGATIVE variance here,
    # which then crashes sqrt(). A stable implementation returns exactly 0.0.
    s = _fill([7.0] * 100)
    assert s.variance >= 0.0
    assert math.isclose(s.variance, 0.0, abs_tol=1e-9)
    assert math.isclose(s.stddev, 0.0, abs_tol=1e-9)   # must not raise


def test_large_offset_small_spread():
    # Values near 1e9 differing only in the last digit. pop var of {1,2,3} = 2/3.
    s = _fill([1e9 + 1, 1e9 + 2, 1e9 + 3])
    assert math.isclose(s.mean, 1e9 + 2, rel_tol=0, abs_tol=1e-3)
    assert math.isclose(s.variance, 2.0 / 3.0, rel_tol=1e-6, abs_tol=1e-6)


def test_huge_offset_constant():
    # Catastrophic cancellation territory: identical huge values -> variance 0.
    s = _fill([1e8] * 5)
    assert s.variance >= 0.0
    assert math.isclose(s.variance, 0.0, abs_tol=1e-6)


def test_known_variance_sequence():
    s = _fill(list(range(100)))               # pop var of 0..99 = (100**2 - 1)/12
    assert math.isclose(s.variance, (100 * 100 - 1) / 12.0, rel_tol=1e-9)


def test_interleaved_push_and_query():
    s = RunningStats()
    s.push(10)
    assert s.mean == 10.0
    assert s.variance == 0.0
    s.push(20)
    assert math.isclose(s.mean, 15.0, abs_tol=1e-9)
    assert math.isclose(s.variance, 25.0, abs_tol=1e-9)   # pop var of {10,20}
    s.push(30)
    assert math.isclose(s.mean, 20.0, abs_tol=1e-9)


def test_offset_sequence_matches_unoffset():
    base = list(range(50))
    offset = [x + 1e7 for x in base]
    assert math.isclose(_fill(base).variance, _fill(offset).variance, rel_tol=1e-6)


def test_stddev_is_sqrt_variance():
    s = _fill([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0])
    assert math.isclose(s.stddev, math.sqrt(s.variance), rel_tol=1e-12, abs_tol=1e-12)
