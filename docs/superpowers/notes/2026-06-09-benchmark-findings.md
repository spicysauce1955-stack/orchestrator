# Governed-vs-Raw Coding-Agent Benchmark — Findings (2026-06-09)

Spec: `docs/superpowers/specs/2026-06-08-agent-benchmark-design.md` ·
Plan: `docs/superpowers/plans/2026-06-08-agent-benchmark.md`

One identical, hidden-test-graded task (`TtlCache`) run through three contestants and
graded against a 12-test held-out suite the agents never see. Run on 2026-06-09.

## Scorecard

| Contestant | pass@1 | hidden | cost $ | wall s | turns | integrity | notes |
|---|---|---|---|---|---|---|---|
| **A** orchestrator (governed, real `claude`) | ❌ | 11/12 | 0.72 | 140 | 3 sessions | ok | missed `negative_capacity` guard |
| **B** raw `claude code` | ✅ | 12/12 | 0.45 | 106 | 10 | ok | cleanest impl + defensive guard |
| **C** raw `codex` | ⚠️ invalid | 0/12 | — | 71 | 6 | ok | **sandbox could not start** (env) |

Total real spend on the graded 3-way run ≈ **$1.17** (A $0.72 + B $0.45 + C ~$0). Plus
~$2 across the staged de-risk runs that found the bugs below.

## Headline verdict

**On this single task, the governed pipeline did NOT beat raw `claude code`.** Contestant
B (raw) scored a clean 12/12 while being cheaper ($0.45 vs $0.72) and faster (106s vs
140s). Contestant A's plan→implement→review→merge governance added a planning step and a
review session (≈60% more cost, +34s) yet produced a *worse* result: its review loop
*approved* an implementation that omitted the `capacity < 0 → ValueError` guard, which
raw `claude` added defensively. Governance cost more and caught less here.

This is n=1 and **not** a leaderboard — it is a directional result with real caveats
(below). The more valuable outcome of the exercise is what the de-risk uncovered: five
real orchestrator bugs that every prior milestone's zero-cost fakes had masked.

## The real payoff: 5 real-vs-fake bugs found & fixed

Contestant A had **never made a real harness run** (M1–M6 used fakes). Staging the run as
"de-risk A alone first" surfaced — at near-zero cost — a chain of defects, each hidden by
the fakes and each fixed (TDD, full suite green):

1. **Adapter omitted `--verbose`.** `claude -p --output-format stream-json` *requires*
   `--verbose`; without it the binary exits 1 immediately. Every step failed at $0. The
   fake never enforced it. → `claude_code.py` adds `--verbose`.
2. **stderr discarded (`DEVNULL`).** The exit-1 failure was silent ("harness exited 1",
   no cause). The deferred M2 follow-up. → drain stderr concurrently, surface its tail on
   non-zero exit.
3. **`.venv` polluted the captured diff.** The implementer's `success_criteria` `uv run`
   created `.venv/` (binary files); `_capture_diff`'s `git add -A -N` swept them in, and
   `git apply --3way` at merge choked → conflict → run paused. → task template gains a
   `.gitignore`.
4. **Verdict parsing too strict.** `parse_output` did `json.loads` on the *whole* result
   text, so a real reviewer wrapping `{"verdict":...}` in prose/```json fences never
   parsed → review loop silently degraded to "always proceed". → extract the last flat
   JSON object from prose/markdown.
5. **Reviewer couldn't see the code.** Per-step worktree isolation means a downstream
   review step starts from a fresh checkout of *base* and sees only the implementer's
   prose, not its edits — so it reviewed an unimplemented stub and rejected good work.
   → expose `{{step.diff}}` in the template engine; feed `{{implement.diff}}` to the
   reviewer. With this, A's review loop finally functioned (approved a real 89-line impl,
   merged, graded 11/12).

After all five fixes, A runs the full governed pipeline end-to-end against the real
`claude` binary: plan → implement → review(approve) → merge → graded.

## Per-contestant detail

- **A (orchestrator, 11/12).** plan $0.16 → implement $0.31 (89-line OrderedDict impl,
  no retry) → review $0.25 (approve, diff-aware) → merge $0 (landed on
  `orch/<run>/merge`, no origin so `local:` branch). Clean, well-factored code with a
  `_purge_if_expired` helper. Single defect: no negative-capacity guard. Readability 4/5,
  maintainability 4/5 (the `set` overwrite branch is slightly dense).
- **B (raw `claude`, 12/12).** Single session, 10 turns, $0.45. The strongest
  implementation: clear "why" comments, `_purge_expired` separation, and a defensive
  `if capacity < 0: raise ValueError`. Readability 5/5, maintainability 5/5. Integrity:
  clean (an earlier heuristic false-positive on the README's own phrase "hidden test
  suite" was corrected — B never referenced the held-out path).
- **C (codex, invalid).** codex's `workspace-write` sandbox uses bubblewrap, which failed
  to initialize in this environment: `bwrap: loopback: Failed RTM_NEWADDR: Operation not
  permitted`. Every fs op (read/ls/`apply_patch`) failed before execution, so codex wrote
  nothing — it even narrated the correct impl it *would* have applied. **Not a capability
  result**; the contestant could not run here.

## Caveats (don't over-read this)

- **n = 1.** One task is directional, not significant. A different task could invert it.
- **The failing test probes unspecified behavior.** The README specifies `capacity=0` but
  says nothing about *negative* capacity; `test_negative_capacity_raises` grades a hidden
  rule. B's defensiveness won; A's literal-to-spec reading lost. Applied equally, but
  it's a hidden-spec gotcha, not a pure correctness gap.
- **Turns aren't apples-to-apples.** A's "3" = orchestrator harness sessions
  (plan/implement/review); B's "10" = `claude`'s internal `num_turns`. Different units.
- **C is environment-blocked**, not measured.

## Follow-ups surfaced

- The five fixes above close the M6a/M6b "real-vs-fake reconciliation" gap for the
  **Claude** adapter specifically. The **OpenCode** adapter's real-vs-fake reconciliation
  remains unverified (no real `opencode` run yet).
- Review-as-judge only works because we now feed it `{{implement.diff}}`. A more general
  fix would let a review step's worktree *materialize* upstream diffs, so the reviewer can
  run the code, not just read it.
- codex needs a non-bwrap sandbox mode (or a host that permits bwrap loopback) to be a
  valid contestant in this environment.
- Governance value is unproven (even negative) at n=1; a multi-task suite is the only way
  to tell whether plan→review→merge earns its cost. That's a deliberately out-of-scope
  larger experiment (spec §9).
