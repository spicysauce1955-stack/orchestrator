# M3 Review Follow-ups

> From the final holistic review of M3 (2026-06-04). M3 shipped **ready-to-merge**:
> 128 tests green, ruff clean, a multi-step pipeline (`classify task → plan agent → implement agent`)
> runs end-to-end through a real compiled LangGraph `StateGraph` with cross-step `{{...}}` dataflow and
> a bounded `success_criteria`/retry inner loop. **Open question #13 is RESOLVED for linear DAG
> execution** (cyclic `on_reject` execution is M4). One IMPORTANT retry bug (empty-feedback sentinel)
> and one UX gap (`--only` on a dependent step dumped a traceback) were **fixed before merge**.

## Must address in M4 (the cyclic on_reject path reuses M3 machinery)

- **Worktree branch-name collision on the reject cycle** (`runtime/executors.py` `run_agent_step`,
  `isolation/worktree.py` `create_worktree`). The branch is `orch/{run_id}/{step.id}` with no
  attempt/pass suffix, and `git worktree add -b <branch>` FAILS if the branch already exists. Safe in
  M3 (each step runs once; the `finally` deletes the branch). But M4's `on_reject` cycle re-enters
  `implement` — the second pass will collide unless the prior pass's cleanup ran. Add a pass/attempt
  suffix when wiring the cycle (e.g. `orch/{run_id}/{step.id}/{pass}`). This interacts with
  retain-on-failure (deferred) too.
- **Verdict router vs. forward-edge ordering invariant** (`compile/compiler.py` `wire_edges`,
  `compile/ir.py` `build_ir`). The M3 forward-only router picks `targets[0]`, relying on `build_ir`
  emitting forward (`needs`) edges BEFORE `on_reject` back-edges (now documented with comments). When
  M4 passes a verdict-aware `router` (the `router=` kwarg already exists), it receives the mixed
  targets list and must reliably tell forward successors from the reject back-edge. Prefer tagging
  edge kind in the IR (`Edge.conditional` already exists; consider an explicit `kind`/`is_reject`)
  over relying on list position.
- **`Done.is_error` vs `success_criteria` precedence** (`runtime/executors.py` retry loop). M3
  semantics: the `success_criteria` shell gate is final — a passing criteria clears a harness
  `Done.is_error=True`. Defensible for M3 (the gate is the observable signal), but when M4 builds the
  review/agent-as-judge step, a harness that errored mid-run yet left tests green would be reported
  `is_error=False` and proceed to review. Revisit the precedence when the judge executor lands.

## Deferred (carry forward, not bugs)

- **Parallel-branch reducers** (`runtime/state.py` `GraphState`). The single shared mutable
  `RunContext` under key `"ctx"` is sound ONLY for linear pipelines (verified: object identity
  preserved across nodes; diamond fan-out raises `InvalidUpdateError`, i.e. fails loud). Parallel /
  best-of-n fan-out needs per-key reducers. Already noted in the state docstring.
- **CLI unreachable-step comment** (`cli.py` full-run loop `if art is None: continue`). The guard is
  forward-looking — in M4, conditional branches skip steps, so it becomes live. Update the
  `# not reached on this path` comment when M4 lands.
- **Real `--resume` across retries.** The retry inner loop re-prompts the same worktree (state
  persists, which is what matters); it does not pass `--resume <harness_session_id>`. Wire real
  session resume when the harness session lifecycle needs it.

## From M2, still open

- **`output_schema` → harness structured output.** Threaded into `adapter.prompt(...)` but not yet
  translated to `--json-schema`; task-step parsing currently reads the textual result. Wire when
  richer typed I/O is needed.
- **MCP wiring / knowledge injection** (M6); **OpenCode adapter** (M6); **`orch status`** (M6).
