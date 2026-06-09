# Task: implement `convex_hull`

Implement the function `convex_hull(points)` in `convex_hull.py`. Given a list of 2-D
points with integer coordinates (as `(x, y)` tuples), return the vertices of their
**convex hull** — the smallest convex polygon containing all the points.

Rules (these are what make it tricky):

- **Only true corners.** A point that lies *on* a hull edge but is not a corner (i.e. it
  is collinear with two other hull points) is **not** a hull vertex and must be excluded.
- **Duplicates** in the input are ignored.
- **Order.** Return the vertices in **counter-clockwise** order. (The grader accepts your
  hull starting at any vertex and in either winding, as long as the cyclic sequence of
  vertices is the correct hull.)
- **Degenerate inputs:**
  - No points → return `[]`.
  - One unique point → return `[that point]`.
  - All points collinear (two or more unique points) → return the **two extreme
    endpoints** of the segment.

Coordinates are exact integers, so the hull is exact — no floating point is needed.

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite covering degenerate cases (collinear points on edges,
duplicates, all-collinear inputs, fewer than three points, unsorted/negative
coordinates), so implement the full contract, not just the smoke tests.
