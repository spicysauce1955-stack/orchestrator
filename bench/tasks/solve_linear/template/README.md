# Task: implement `solve`

Implement `solve(A, b)` in `solve_linear.py`. Given a square `n × n` matrix `A` (a list
of `n` rows, each a list of `n` numbers) and a length-`n` right-hand side vector `b`,
return the solution vector `x` (length `n`) of the linear system **`A x = b`**.

Requirements:

- **Numerically sound.** Use a method that works for *any* solvable system, not only the
  easy ones. In particular it must handle systems where a leading diagonal entry is zero
  (so naive elimination without row swaps would divide by zero) and stay accurate on
  mildly ill-conditioned matrices. The hidden tests include both.
- **Singular systems.** If `A` is singular (no unique solution — including inconsistent
  systems), raise `ValueError`.
- You may assume real-valued inputs. `n` is at least 1. Standard library only (no numpy).

The returned `x` is graded by residual: `A x` must equal `b` within a small tolerance.

## Done when

`uv run --with pytest pytest -q` passes the smoke tests in `tests/`. Your grade is based
on a larger hidden test suite (systems requiring pivoting, ill-conditioned systems,
singular/inconsistent systems, and larger random systems), so implement the full
contract robustly, not just the smoke tests.
