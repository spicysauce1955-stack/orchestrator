# Post-M6 Follow-up Pass — 2026-06-07

A cleanup pass over the open items in the M1–M6d review-follow-up notes, done
after M6 (the final MVP milestone) completed. TDD throughout; **269 tests green,
ruff clean** (was 257). Many older items were already resolved by later
milestones (verified, not re-done): M1 `mode`-enum→M2, typed-IO ancestor rule &
`{{ }}` syntax & cycle/deep-ref hardening→M3, M2 stderr-drain→M3, MCP wiring→M6b,
M4 exhausted-verdict-blocks-merge→M5, M6c `orch status` board→M6d.

## ① Cheap pure-wins — DONE

- **`.orch/` gitignored.** Checkpoint + span SQLite DBs are per-repo run state,
  never source (M5/M6d).
- **`orch memory` distinguishes not-found from no-messages.** `run_messages`
  returns `[]` for both; the CLI now probes `run_status` and exits 1 with an
  error for an unknown run, else prints "no messages recorded" (exit 0) (M6d).
- **`_trace_for_run` no longer Python-scans.** Replaced with a SQL
  `json_extract(attrs, '$."run.id"')` filter; also now returns *all* matching
  traces (see ②) (M6d).
- **Golden-graph edge ORDER locked.** New `test_golden_graph_edge_order_is_stable`
  asserts the ordered edge list (forward edges before `on_reject` back-edges) the
  M3 verdict router relies on (M1).
- **Test-infra: shared git-repo helpers.** Added `init_git_repo(path, *,
  branch="main")` + `commit_all(path, msg)` to `tests/fixtures/repo.py` (and
  routed `make_repo` through them). Migrated the duplicated local `_repo`/
  `_git_repo` helpers in `test_merge`, `test_relayed_feedback`, `test_hitl_gate`,
  `test_full_pipeline`, `test_mixed_harness` (M6c). **Partial:** other test files
  with a local `_repo` (e.g. `test_capture_diff`, `test_validate`, several
  integration tests) can adopt the helper incrementally — left as-is to bound
  churn (the helper now exists; this was flagged "Non-blocking").

## ② Real seams — DONE

- **Resume-visibility (M6d).** `DeterministicScheduler.resume` now opens a
  `SPAN_RUN` (same `run.id`) around the resumed execution, so steps executed on
  resume are grouped under a resolvable trace instead of scattering as root
  spans. The read models (`run_status`/`run_metrics`/`run_messages`) now resolve
  a run to **all** its traces (original + each resume) via `_traces_for_run` and
  union spans across them (steps deduped by id, latest wins). Proven by
  `test_resumed_steps_are_resolvable_in_status` (audit→gate→after pipeline).
- **`RunStatus.REJECTED` (M5).** A human-rejected HITL gate is now terminal-but-
  distinct from a merged `COMPLETED` run. `_finalize` sets `REJECTED` when any
  `gate_decisions` value is `reject`; `run`/`resume` stamp the terminal status on
  the run span as `run.status`, which `run_status` surfaces verbatim. (Merge-
  conflict *abort* still records an error artifact → reads as `error`, not a new
  status — left as-is.) Updated `test_resume_reject_ends_run` /
  `test_full_pipeline_reject_at_gate_skips_merge`; added
  `test_rejected_run_reports_rejected_in_status`.

## ③ role.model threading — DONE

`Role.model` was unconsumed since M1 (an OpenCode step ran on OpenCode's default
model regardless of the role's `model:`). Threaded it **per-session** (model is
per-step role data) rather than rekeying the registry to `(harness, model)` —
cleaner, no per-step adapter construction, `.single()` back-compat untouched:

- `HarnessAdapter.start_session` gains `model: str | None = None` (protocol +
  both adapters). Claude emits `--model <model>`; OpenCode emits `-m <model>`
  with the `glm`→`zhipu/glm-4.6` alias, a per-session model overriding any
  construction default.
- `run_agent_step` passes `role.model` through `_drive_with_questions` →
  `_drive_harness` → `start_session`. (Scoped to **agent** steps; task steps are
  cheap read-only glue and keep the adapter default.)
- Proven end-to-end: `test_role_model_threads_to_opencode` runs the `opencoder`
  agent step (declares `model: zhipu/glm-4.6`) and asserts `-m zhipu/glm-4.6`
  reached the CLI; plus adapter-level `test_session_model_*` for both harnesses.

## Still deferred (out of this pass — unchanged)

- **Real-vs-fake reconciliation** (M6a NDJSON, M6b MCP wire format, OpenCode
  `deny_read`/`write_scope`) — needs the real `claude`/`opencode` binaries to
  verify against; cannot be done from fakes.
- **Future-milestone scope** — knowledge-write/MCP-call spans (cross-process),
  parallel/best-of-n trace splitting + reducers, span/checkpoint DB GC,
  semantic-rebase merge agent, Codex adapter → M7/M8/M9.
- `Done.is_error` vs `success_criteria` precedence; `max_retries` overload;
  cross-step filesystem composition; real `--resume <session_id>` across retries
  — design deferrals, not bugs.
