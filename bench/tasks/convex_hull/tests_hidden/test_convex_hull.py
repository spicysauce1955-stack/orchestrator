"""Held-out grader for convex_hull. NEVER copied into a contestant's repo."""
from __future__ import annotations

from convex_hull import convex_hull


def _vset(hull):
    return {tuple(p) for p in hull}


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _is_ccw_convex(poly):
    """True if poly is a strictly-convex polygon wound counter-clockwise."""
    n = len(poly)
    if n < 3:
        return True
    for i in range(n):
        if _cross(poly[i], poly[(i + 1) % n], poly[(i + 2) % n]) <= 0:
            return False   # right turn or collinear -> not strictly CCW-convex
    return True


def test_square_with_interior_and_edge_point():
    # (2,2) interior, (2,0) collinear on the bottom edge -> both excluded.
    pts = [(0, 0), (4, 0), (4, 4), (0, 4), (2, 2), (2, 0)]
    assert _vset(convex_hull(pts)) == {(0, 0), (4, 0), (4, 4), (0, 4)}


def test_collinear_points_on_edge_excluded():
    # Three collinear points along the bottom; only the two ends are corners.
    pts = [(0, 0), (2, 0), (4, 0), (4, 3), (0, 3)]
    assert _vset(convex_hull(pts)) == {(0, 0), (4, 0), (4, 3), (0, 3)}


def test_duplicates_ignored():
    pts = [(0, 0), (0, 0), (4, 0), (4, 4), (0, 4), (4, 4), (0, 0)]
    assert _vset(convex_hull(pts)) == {(0, 0), (4, 0), (4, 4), (0, 4)}


def test_all_collinear_returns_endpoints():
    pts = [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert _vset(convex_hull(pts)) == {(0, 0), (3, 3)}


def test_all_collinear_unsorted_horizontal():
    pts = [(5, 2), (1, 2), (3, 2), (2, 2)]
    assert _vset(convex_hull(pts)) == {(1, 2), (5, 2)}


def test_single_point():
    assert _vset(convex_hull([(7, 9)])) == {(7, 9)}


def test_empty():
    assert convex_hull([]) == []


def test_two_unique_points_with_duplicate():
    assert _vset(convex_hull([(2, 2), (2, 2), (5, 5)])) == {(2, 2), (5, 5)}


def test_triangle_with_many_interior_points():
    pts = [(0, 0), (10, 0), (0, 10)]
    pts += [(2, 2), (3, 1), (1, 3), (4, 4), (1, 1)]   # all interior
    assert _vset(convex_hull(pts)) == {(0, 0), (10, 0), (0, 10)}


def test_negative_and_unsorted_coordinates():
    pts = [(3, -1), (-2, 2), (1, 4), (-2, -3), (0, 0), (1, 1)]
    hull = convex_hull(pts)
    assert _vset(hull) == {(-2, -3), (3, -1), (1, 4), (-2, 2)}
    assert _is_ccw_convex(hull)


def test_returns_ccw_convex_polygon():
    pts = [(0, 0), (4, 0), (4, 4), (0, 4), (2, 5), (5, 2)]
    hull = convex_hull(pts)
    assert _vset(hull) == {(0, 0), (4, 0), (5, 2), (4, 4), (2, 5), (0, 4)}
    assert _is_ccw_convex(hull)


def test_square_corners_only_with_dense_border():
    # Points densely along all four edges; only the 4 corners are vertices.
    pts = []
    for i in range(5):
        pts += [(i, 0), (i, 4), (0, i), (4, i)]
    assert _vset(convex_hull(pts)) == {(0, 0), (4, 0), (4, 4), (0, 4)}
