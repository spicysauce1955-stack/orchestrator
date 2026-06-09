"""Reference convex_hull (oracle). NEVER copied into a contestant's repo.

Andrew's monotone chain. Excludes collinear points; returns CCW order starting
at the lexicographically smallest vertex.
"""
from __future__ import annotations


def _cross(o, a, b) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pts = sorted({(int(x), int(y)) for x, y in points})
    if len(pts) <= 2:
        return pts

    lower: list[tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]
