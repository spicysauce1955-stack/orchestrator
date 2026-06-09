import pytest

from solve_linear import solve


def _residual(A, x, b):
    return max(abs(sum(A[i][j] * x[j] for j in range(len(x))) - b[i]) for i in range(len(A)))


def test_diagonal():
    x = solve([[2, 0], [0, 4]], [6, 8])
    assert _residual([[2, 0], [0, 4]], x, [6, 8]) < 1e-9


def test_basic_2x2():
    A, b = [[1, 1], [1, -1]], [3, 1]
    assert _residual(A, solve(A, b), b) < 1e-9


def test_singular_raises():
    with pytest.raises(ValueError):
        solve([[1, 2], [2, 4]], [1, 2])
