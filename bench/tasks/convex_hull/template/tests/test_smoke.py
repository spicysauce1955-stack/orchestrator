from convex_hull import convex_hull


def _as_set(hull):
    return {tuple(p) for p in hull}


def test_square_corners():
    pts = [(0, 0), (4, 0), (4, 4), (0, 4), (2, 2)]
    assert _as_set(convex_hull(pts)) == {(0, 0), (4, 0), (4, 4), (0, 4)}


def test_triangle():
    pts = [(0, 0), (6, 0), (0, 6)]
    assert _as_set(convex_hull(pts)) == {(0, 0), (6, 0), (0, 6)}


def test_two_points():
    assert _as_set(convex_hull([(1, 1), (3, 3)])) == {(1, 1), (3, 3)}
