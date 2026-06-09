"""Held-out grader for IntervalSet. NEVER copied into a contestant's repo."""
from __future__ import annotations

from interval_set import IntervalSet


def test_single_add():
    s = IntervalSet()
    s.add(2, 5)
    assert len(s) == 1
    assert s.total == 3
    assert s.contains(2) and s.contains(4)
    assert not s.contains(5)           # half-open
    assert not s.contains(1)


def test_disjoint_adds_stay_separate():
    s = IntervalSet()
    s.add(1, 3)
    s.add(5, 7)
    assert len(s) == 2
    assert s.total == 4
    assert not s.contains(3) and not s.contains(4)


def test_overlapping_adds_merge():
    s = IntervalSet()
    s.add(1, 4)
    s.add(3, 8)
    assert len(s) == 1
    assert s.total == 7


def test_adjacent_adds_merge():
    s = IntervalSet()
    s.add(1, 3)
    s.add(3, 5)                        # adjacent -> single [1,5)
    assert len(s) == 1
    assert s.total == 4


def test_add_engulfing_interval():
    s = IntervalSet()
    s.add(3, 5)
    s.add(1, 10)                       # swallows the first
    assert len(s) == 1
    assert s.total == 9


def test_add_bridging_two_intervals():
    s = IntervalSet()
    s.add(1, 3)
    s.add(6, 9)
    s.add(2, 7)                        # bridges both -> [1,9)
    assert len(s) == 1
    assert s.total == 8


def test_empty_add_is_noop():
    s = IntervalSet()
    s.add(5, 5)
    s.add(7, 3)
    assert len(s) == 0
    assert s.total == 0


def test_remove_middle_splits():
    s = IntervalSet()
    s.add(0, 10)
    s.remove(3, 6)                     # -> [0,3) and [6,10)
    assert len(s) == 2
    assert s.total == 7
    assert s.contains(2) and not s.contains(4) and s.contains(7)


def test_remove_trims_edges():
    s = IntervalSet()
    s.add(0, 10)
    s.remove(0, 3)
    assert s.contains(3) and not s.contains(2)
    s.remove(8, 20)                    # over-wide removal trims to [3,8)
    assert s.total == 5
    assert not s.contains(8)


def test_remove_spanning_multiple():
    s = IntervalSet()
    s.add(0, 2)
    s.add(4, 6)
    s.add(8, 10)
    s.remove(1, 9)                     # leaves [0,1) and [9,10)
    assert len(s) == 2
    assert s.total == 2
    assert s.contains(0) and s.contains(9)
    assert not s.contains(5)


def test_remove_nonexistent_is_noop():
    s = IntervalSet()
    s.add(1, 3)
    s.remove(5, 9)
    s.remove(2, 2)                     # empty range no-op
    assert len(s) == 1
    assert s.total == 2
