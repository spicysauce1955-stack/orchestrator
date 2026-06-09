from interval_set import IntervalSet


def test_add_and_contains():
    s = IntervalSet()
    s.add(1, 5)
    assert s.contains(1) is True
    assert s.contains(5) is False   # half-open: end exclusive


def test_total_and_len():
    s = IntervalSet()
    s.add(0, 3)
    assert len(s) == 1
    assert s.total == 3


def test_overlapping_add_merges():
    s = IntervalSet()
    s.add(1, 4)
    s.add(3, 6)
    assert len(s) == 1
    assert s.total == 5
