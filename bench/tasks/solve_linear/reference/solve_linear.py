"""Reference solve_linear (oracle). NEVER copied into a contestant's repo.

Gaussian elimination with partial pivoting; raises ValueError when singular.
"""
from __future__ import annotations

_EPS = 1e-12


def solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(A)
    if n == 0:
        return []
    # augmented matrix (float copy)
    m = [[float(A[i][j]) for j in range(n)] + [float(b[i])] for i in range(n)]

    for col in range(n):
        # partial pivot: largest magnitude entry in this column, on/below the diagonal
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < _EPS:
            raise ValueError("matrix is singular (no unique solution)")
        m[col], m[pivot] = m[pivot], m[col]
        inv = m[col][col]
        for r in range(col + 1, n):
            factor = m[r][col] / inv
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]

    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / m[i][i]
    return x
