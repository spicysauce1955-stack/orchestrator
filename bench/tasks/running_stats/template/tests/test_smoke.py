from running_stats import RunningStats


def test_mean():
    s = RunningStats()
    for x in [1, 2, 3]:
        s.push(x)
    assert s.mean == 2.0
    assert len(s) == 3


def test_empty():
    s = RunningStats()
    assert len(s) == 0
    assert s.mean == 0.0
    assert s.variance == 0.0


def test_variance_basic():
    s = RunningStats()
    for x in [1, 2, 3, 4, 5]:
        s.push(x)
    assert abs(s.variance - 2.0) < 1e-9   # population variance of 1..5
