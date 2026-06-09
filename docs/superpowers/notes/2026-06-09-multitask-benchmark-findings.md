# Multi-Task Benchmark + Harness Hardening — Findings (2026-06-09)

Follow-up to the n=1 benchmark (`2026-06-09-benchmark-findings.md`). Three
deliverables: (1) make codex a valid contestant, (2) de-risk the OpenCode adapter
against the real binary, (3) run a multi-task suite to settle the governance question.

## Multi-task scorecard (n=3)

| Contestant | interval_set | token_bucket | ttl_cache | pass@1 | cost $ | wall s |
|---|---|---|---|---|---|---|
| **A** orchestrator (governed, real claude) | ✅ | ✅ | ❌ | **2/3** | 2.87 | 524 |
| **B** raw `claude code` | ✅ | ✅ | ✅ | **3/3** | 1.15 | 226 |
| **C** raw `codex` | ✅ | ✅ | ✅ | **3/3** | n/a (470k tok) | 189 |

Hidden-test detail: interval_set 11/11 all; token_bucket 11/11 all; ttl_cache A 11/12
(missed `test_negative_capacity_raises`), B 12/12, C 12/12.

## Verdict: governance still did not win

Across three tasks the governed pipeline (A) **scored lower** (2/3 vs 3/3) while costing
**~2.5× more** ($2.87 vs $1.15) and running **~2.5× slower** (524s vs ~200s). Its only
loss is the same ttl_cache edge as n=1: the review loop *approved* an implementation
missing the negative-capacity guard. The measurable effect of plan→implement→review→merge
here was added cost and latency, not higher pass@1.

**Caveat — ceiling effect.** Two of three tasks were solved 3/3 by *everyone*, so they
didn't discriminate; only ttl_cache (with a hidden, README-unspecified edge) separated the
field. Frontier coding agents clear bespoke ~80-line data-structure tasks easily. To
actually measure governance value you need harder, more failure-prone tasks where a
review/retry loop can catch defects raw single-shot agents miss — and a per-task n>1 to
average out variance. This 3-task run is still directional, not conclusive; but the cost
and latency overhead of governance is now consistent and clear.

## Codex made a valid contestant (was env-blocked at n=1)

codex's `-s workspace-write` sandbox uses bubblewrap, which can't initialize here
(`bwrap: loopback: Failed RTM_NEWADDR`). Fix: invoke codex with
`--dangerously-bypass-approvals-and-sandbox` (its help: "Intended solely for running in
environments that are externally sandboxed" — each contestant already runs in an isolated
throwaway git repo). codex then solves all three tasks 3/3, fastest of the field (189s).
Fairness caveat recorded: bypass also grants codex shell/network its sandboxed peers lack.

## OpenCode adapter real-vs-fake de-risk (the same bug class as Claude)

Drove the **real** `opencode` (1.15.13, glm-5.1 via ollama) through the orchestrator. The
adapter had its own real-vs-fake gap, hidden by the fakes: real opencode nests the whole
payload under `.part` (`part.text`, `part.tool`, `part.state.input.filePath`,
`part.tokens.total`), but `parse_opencode_line` read top-level keys — so text, tool names,
edited paths, and token counts were all silently dropped. Reconciled the parser to the
real shape (validated against captured NDJSON), updated the fake fixtures + unit tests to
match, and added concurrent stderr draining (the same silent-failure fix as the Claude
adapter). Result: the orchestrator now drives opencode end-to-end — implement edited the
file (91-line diff, 113k tokens parsed), merge landed, graded 10/12. This closes the
OpenCode half of the M6a/M6b real-vs-fake reconciliation gap.

## Cumulative harness bugs found by running real binaries

The benchmark's real value remains the bugs it surfaced — none visible to the zero-cost
fakes:

1. Claude adapter missing `--verbose` (exit 1 every step).
2. Claude adapter discarded stderr (silent failures).
3. Task repo had no `.gitignore` → `.venv` polluted the merge diff.
4. Verdict JSON not extracted from prose → review loop dead.
5. Reviewer couldn't see code (no `{{step.diff}}`).
6. codex bwrap sandbox unusable in this env.
7. OpenCode parser read top-level keys, not `.part` (text/tool/path/tokens dropped).
8. OpenCode adapter discarded stderr (same as #2).

Both real harness adapters (Claude, OpenCode) are now exercised against their real
binaries; codex (raw) is a valid contestant.

## Follow-ups

- **Harder tasks + per-task repetition** are the only way to actually settle the
  governance question; this suite hits a ceiling at n=3 easy tasks.
- codex cost (not just tokens) and orchestrator turn-count could be folded into the
  auto-scorecard (currently A cost is sourced manually from the span store, C is tokens).
- The OpenCode adapter's `build_permission_config` vs real opencode's permission schema
  is still only spot-checked; deny-scope translation remains best-effort.
