# Harder-Task Benchmark Round — Findings (2026-06-09)

Goal: the n=3 suite hit a ceiling (everyone 3/3 on two tasks), so we researched
failure-prone domains and built harder tasks to try to discriminate governed-vs-raw.

## Research (Tavily)

Surveyed where LLM coding agents fail in math/scientific domains. Headline: **SciCode**
(scientist-curated research coding) is brutal — best frontier models solve only ~5–14% of
*main* problems (Claude 3.5 Sonnet 4.6%, o1-preview 7.7%, recent Sonnet-4/Gemini-2.5-Pro
~13.8%); sub-problems ~20–35%. But SciCode needs domain knowledge + numpy/scipy +
multi-file structure — not a fit for our self-contained, stdlib, hidden-pytest format.

The transferable signal was the **failure modes**: LLMs write "syntactically plausible but
numerically fragile" code — catastrophic cancellation, geometric degeneracy, ill-
conditioning, off-by-one. Built three self-contained tasks each targeting one, with hidden
adversarial cases the *naive* approach fails (verified):
- **running_stats** (Welford streaming variance) — naive `sum(x*x)/n - mean**2` → wrong
  variance on large-offset data (0.0 vs 0.667).
- **convex_hull** (integer points, degeneracy) — naive collinear-inclusion over-includes
  edge points. Exact grading via canonicalization.
- **solve_linear** (Gaussian elimination + partial pivoting) — no-pivot elimination
  crashes (ZeroDivisionError) on a zero leading pivot; loses precision on large dynamic
  range. Residual grading + singular detection.

## Result: still no discrimination

| Contestant | running_stats | convex_hull | solve_linear | pass@1 | cost $ | wall s |
|---|---|---|---|---|---|---|
| A orchestrator (governed) | ✅ | ✅ | ✅ | 3/3 | 2.97 | 637 |
| B raw claude | ✅ | ✅ | ✅ | 3/3 | 1.56 | 319 |
| C raw codex | ✅ | ✅ | ✅ | 3/3 | n/a | 382 |

**All three contestants solved all three tasks 3/3** (full hidden suites: 11/12/12).
Frontier agents reliably reach for the robust algorithm (Welford, monotone-chain hull,
partial pivoting) — the naive trap that breaks the hidden tests is exactly the version
they *don't* write. Governance again added ~2× cost and ~2× latency with no pass@1 gain,
and this round its **review loop never fired**: 1 implement step per task, zero rejects —
the implementer was correct first try every time, so there was nothing to catch.

## The meta-finding (now consistent across 3 rounds, 6 tasks)

1. **Bespoke single-file algorithmic tasks don't discriminate frontier coding agents** —
   not even ones built around documented numerical failure modes. These are textbook
   algorithms the models know cold.
2. **Governance (plan→review→merge) never improved pass@1** — across easy and hard tasks
   it only added cost and latency. Its value proposition (a review loop catching defects)
   is real *only when the base agent errs*, which on solvable tasks it doesn't.
3. **Design caveat:** the task READMEs telegraphed the failure modes ("a naive
   `sum(x*x)/n` formula loses precision", "collinear points excluded", "naive elimination
   without row swaps divides by zero"). That likely helped the models avoid the traps; an
   un-hinted phrasing might lower pass rates and is a cheap next experiment.

## Where a discriminating benchmark actually lives

To make governance earn its cost you need tasks where first attempts *fail*:
- **SciCode-style research problems** (domain knowledge + multi-step reasoning; 5–14%
  solve rates) — but those break the self-contained/stdlib format and need numpy/scipy.
- **Long, multi-component tasks** where errors compound across files/steps and a review
  loop has surface area to catch something — closer to the orchestrator's real use case
  than a 30–80 line function.
- **Un-hinted, non-obvious failure modes** (don't name the trap in the spec).

The honest conclusion: on the class of tasks we can cheaply auto-grade, the governed
pipeline is not worth its overhead — and the benchmark's enduring value was the 8 real
adapter bugs the real-binary runs surfaced, not the pass@1 comparison.
