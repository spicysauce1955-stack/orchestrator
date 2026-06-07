# M6d follow-ups — durable span store + status/metrics/memory

Deferred items and known limitations from M6d (the durable, queryable SQLite span
store and the `orch status|metrics|memory` lenses).

- **knowledge-write / MCP-call spans not emitted.** Cross-process: the write
  happens in the `mcp_server.py` subprocess spawned by the harness, not the
  orchestrator. `run_messages` already surfaces `knowledge.write` spans *if*
  present (forward-compatible) — adding emission needs no query change. Likely
  approach: have `mcp_server.py` export to the same span DB (`$ORCH_SPAN_DB`)
  with the run's trace context passed via env.
- **Queries assume one trace_id per run.** Holds for linear MVP pipelines
  (locked by `test_all_spans_of_a_run_share_one_trace`). Parallel / best-of-n
  branches (M9) may split traces; revisit then (stamp `run.id` on every span, or
  query by attribute instead of trace_id).
- **`_trace_for_run` is a full table scan filtered in Python.** Fine at MVP
  scale. Optimize later with `json_extract(attrs, '$."run.id"')` (SQLite 3.38+)
  and/or an index; also makes the "duplicate run.id" case explicit (currently the
  first match silently wins).
- **`orch memory` cannot distinguish "run not found" from "run found, no
  messages".** `run_messages` returns `[]` for both (documented inline). A probe
  via `run_status` would disambiguate if needed.
- **Span DB never GC'd** (same as the checkpoint DB, M5 follow-up). No retention
  policy; the `.orch/spans.sqlite` file grows unbounded.
- **`orch metrics` surfaces step-level durations only.** Run-level wall-clock and
  budget-vs-actual are not surfaced yet.
- **`orch resume` exports under a fresh trace with no `run` span.** `resume()`
  (scheduler) does not open a `SPAN_RUN`, so a resume-only execution writes step
  spans under a new trace_id that `_trace_for_run` can't resolve by `run.id` — the
  resumed steps won't show in `status`/`metrics`/`memory` for that run (the
  original run's spans remain queryable). Pre-existing seam, newly relevant now
  that resume exports to the store. Fix: open a `SPAN_RUN` (with `run.id`) around
  the resumed execution, or carry the original trace.
