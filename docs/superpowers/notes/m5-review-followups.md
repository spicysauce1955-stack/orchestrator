# M5 Review Follow-ups

> From the final holistic review of M5 (2026-06-05). M5 shipped **ready-to-merge** (after two
> review-driven fixes folded in): **169 tests green, ruff clean**. The HITL gate + resume + merge→PR
> + conflict gate are live. A `gate` step calls LangGraph `interrupt()` → the run checkpoints to
> SQLite (`AsyncSqliteSaver`, `thread_id=run_id`) and halts; `orch resume <id> --approve|--reject`
> reloads the checkpoint (in a separate process) and re-enters via `Command(resume=...)`. A unified
> router sends gate approve→forward / reject→END and verdict reject→implement. The `merge` step
> (`merge_strategy: sequential-rebase`) collects upstream agent diffs, applies them onto an
> integration branch off base (`git apply --3way`), and opens a PR (push + `gh`); an apply conflict
> raises a HITL **conflict gate** (`interrupt()` inside the merge node). `orch run full` demonstrates
> `classify → plan → implement → review ⟲ → test → audit → approve(HITL) → merge(PR)`, pausing at the
> gate and resuming to merge. Manual cross-process smoke confirmed (run pauses; resume opens PR).
>
> **Spec §6 invariant verified twice (empirically):** resume re-runs ONLY the interrupted node, never
> an upstream agent step — confirmed for both the `approve` gate and the merge-conflict interrupt
> (agent `attempts`/harness-call counters unchanged across pause+resume). `apply_diffs` is idempotent
> on conflict-retry (force-removes any stale integration worktree/branch first), so no partial state
> survives a retry.

## Resolved an M4 follow-up

- **Non-approve terminal verdict now blocks merge.** `run_merge_step` calls `_terminal_verdict(ctx)`
  (the last-recorded review verdict, correct under the on_reject loop since a re-run overwrites the
  `review` artifact in place) and refuses with `is_error` if it is not `approve`. This is defense in
  depth alongside the human `approve` gate (which gates on the audit summary, a separate decision).

## Must decide / revisit in M6

- **Merge cross-step filesystem isolation (the headline limitation).** Each agent step runs in a
  fresh worktree cut off the base, so steps do NOT see each other's edits; the merge re-applies each
  step's captured diff independently onto one integration branch. Consequence: only **single-editor**
  pipelines (one substantive file-editing step, e.g. `implement`) or pipelines whose diffs are
  byte-identical (collapsed by the `dict.fromkeys` dedup) merge cleanly. Two steps that edit the same
  region differently produce distinct diffs and **legitimately** conflict at apply time (→ HITL
  conflict gate). True multi-step composition (later steps building on earlier work) needs steps to
  branch off the *prior* step's result rather than base — deferred. Document as a known limitation;
  the dedup itself is sound (it only drops byte-identical patches; a real collision is never masked).
- **No distinct terminal status for a rejected/aborted run.** A gate `reject` routes to END and
  `_finalize` reports `RunStatus.COMPLETED` (the run finished, just without merging). There is no
  `ABORTED`/`REJECTED` status to distinguish "ran to completion and merged" from "human rejected" or
  "merge aborted on conflict". Add a terminal status if downstream tooling (`orch status`) needs to
  tell them apart.
- **Cross-process resume of a non-workspace pipeline.** `resume` recovers `pipeline_name` from the
  checkpoint, then looks it up in `workspace.pipelines`. In a fresh process the in-memory
  `_pipeline_cache` is empty, so a run whose pipeline was constructed dynamically (not defined under
  `.orchestrator/pipelines/`) raises `KeyError`, which the CLI reports as "no paused run found"
  (technically misleading — the run exists; its pipeline definition does not). Contract: **resumable
  pipelines must be workspace-defined.** Documented in `scheduler.py`; consider persisting enough to
  reconstruct, or a clearer CLI error, in M6.

## Deferred (carry forward, not bugs)

- **Conflict gate is abort/retry only** (semantic-rebase agent deferred, per spec §3 "Merge
  conflict → HITL gate"). On conflict the run pauses; `resume --reject` aborts (error artifact),
  `resume --approve` retries the apply **once** (assuming the human resolved the base externally). A
  retry that still conflicts now records a clean error artifact rather than crashing (review fix).
  There is no in-loop guided resolution; the human is expected to fix the base out-of-band.
- **`open_pull_request` requires `origin` + `gh`.** With no `origin` remote it returns a
  `local:<branch>` pseudo-ref (MVP: nothing to push to). The real path pushes the branch and shells
  `gh pr create` (faked in tests via `$ORCH_GH_BIN`). No PR templating / labels / reviewers yet.
- **`max_retries` still bounds BOTH** the inner `success_criteria` retry and the outer review-reject
  re-runs (M4 overload, unchanged).
- **Empty-diff merge** now returns a clean non-error "nothing to merge" artifact
  (`output_data.pr_url == None`) instead of a misleading `gh` failure (review fix).
- **Real `--resume <harness_session_id>`** across agent retries still not wired (carried from M2–M4).
- **`output_schema` → `--json-schema`** still threaded-but-not-translated (task/review parse the
  textual result); carried from M2/M3.

## From earlier milestones, still open → M6

- Orchestrator agent (run-owner, message bus, worker Q&A); knowledge provider (core + on-demand
  lexical + auditor-gated write); OpenCode adapter; `orch status` (read checkpoints/spans); safety
  baseline polish. These are the M6 scope per spec §12.

## Checkpoint hygiene (note for M6)

- The SQLite checkpoint db defaults to `<repo>/.orch/checkpoints.sqlite` (override via
  `$ORCH_CHECKPOINT_DB` / `--state-db`). It is never GC'd — every run accumulates. `orch status` /
  a retention policy should be considered when M6 makes runs first-class. `.orch/` should be
  gitignored in real repos (tests use tmp repos).
