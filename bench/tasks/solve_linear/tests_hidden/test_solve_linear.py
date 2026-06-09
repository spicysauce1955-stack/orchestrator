"""Held-out grader for solve_linear. NEVER copied into a contestant's repo."""
from __future__ import annotations

import pytest

from solve_linear import solve


def _matvec(A, x):
    return [sum(A[i][j] * x[j] for j in range(len(x))) for i in range(len(A))]


def _residual(A, x, b):
    return max(abs(v - b[i]) for i, v in enumerate(_matvec(A, x)))


def _check(A, x_true, *, res_tol=1e-7, sol_tol=1e-6):
    """b := A @ x_true; solve(A,b) must reproduce x_true and have small residual."""
    b = _matvec(A, x_true)
    x = solve(A, b)
    assert len(x) == len(x_true)
    assert _residual(A, x, b) <= res_tol
    assert all(abs(a - t) <= sol_tol for a, t in zip(x, x_true))


def test_one_by_one():
    _check([[5.0]], [2.0])


def test_diagonal():
    _check([[2, 0, 0], [0, 4, 0], [0, 0, 8]], [1.0, -2.0, 0.5])


def test_requires_pivoting_zero_leading_pivot_2x2():
    # A[0][0] == 0: elimination without a row swap divides by zero.
    _check([[0, 1], [1, 0]], [3.0, 2.0])


def test_requires_pivoting_3x3():
    _check([[0, 2, 1], [1, 0, 1], [2, 1, 0]], [1.0, 2.0, 3.0])


def test_large_dynamic_range_needs_pivoting():
    # Tiny leading pivot: no-pivot elimination loses all precision (growth ~1e10).
    _check([[1e-10, 1.0], [1.0, 1.0]], [1.0, -1.0], res_tol=1e-6, sol_tol=1e-4)


def test_ill_conditioned_hilbert_3x3():
    H = [[1.0, 1 / 2, 1 / 3], [1 / 2, 1 / 3, 1 / 4], [1 / 3, 1 / 4, 1 / 5]]
    _check(H, [1.0, 1.0, 1.0], res_tol=1e-9, sol_tol=1e-4)


def test_negative_entries():
    _check([[-3, 1, 2], [1, -4, 1], [2, 1, -5]], [-1.0, 2.0, 0.0])


def test_larger_5x5():
    A = [
        [4, 1, 0, 2, 1],
        [1, 5, 2, 0, 1],
        [0, 2, 6, 1, 0],
        [2, 0, 1, 7, 2],
        [1, 1, 0, 2, 5],
    ]
    _check(A, [2.0, -1.0, 3.0, 0.5, -2.0])


def test_permuted_identity_needs_full_pivoting():
    # A row-permuted identity: every leading pivot is zero until swapped.
    A = [[0, 0, 1], [0, 1, 0], [1, 0, 0]]
    _check(A, [7.0, -3.0, 5.0])


def test_singular_dependent_rows_raises():
    with pytest.raises(ValueError):
        solve([[1, 2], [2, 4]], [1.0, 2.0])


def test_singular_inconsistent_raises():
    with pytest.raises(ValueError):
        solve([[1, 2], [2, 4]], [1.0, 5.0])


def test_singular_3x3_rank_deficient_raises():
    # row3 = row1 + row2 -> rank 2, singular.
    with pytest.raises(ValueError):
        solve([[1, 1, 1], [0, 1, 2], [1, 2, 3]], [1.0, 2.0, 3.0])
