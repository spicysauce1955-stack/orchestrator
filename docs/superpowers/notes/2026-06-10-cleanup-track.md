# Cleanup track (2026-06-10) — pre-M7 deferred follow-ups

Branch `cleanup-track`, TDD, 319 tests green (was 295), ruff clean. Cleared the
three items queued ahead of M7:

1. **Stream abandonment / cancel kills the subprocess (all 3 adapters).** The
   inherited `_stream` pattern orphaned the child + stderr-drain task when the
   consumer abandoned the stream (aclose / task cancellation), and `cancel()`
   never killed a live process. Shared `harness/_proc.py::reap()` (kill + reap +
   retire drain task, safe on every exit path); `try/finally` in each adapter's
   `_stream`; sessions track their live `proc`; `cancel()` reaps it. Locked by
   `tests/integration/test_stream_abandonment.py` (parametrized over the three
   adapters against a hanging fixture child).

2. **Cross-process knowledge MCP spans.** `mcp_server.py` (a harness-spawned
   subprocess) now row-writes `mcp.call` (every tools/call, with `mcp.is_error`)
   and `knowledge.write` (successful writes: `kb.target`, `kb.lesson`) into the
   run's span store. The provider threads `$ORCH_SPAN_DB` + trace context
   (`ORCH_SPAN_TRACE`/`ORCH_SPAN_PARENT`/`ORCH_KB_STEP`) via server env —
   `build_knowledge_mcp` is now called INSIDE the step span and takes `step_id`.
   `orch memory` interleaves knowledge.write entries with bus messages.
   `span_db_path()` moved to `observability/store.py` (CLI + provider share it).

3. **`orch gc`** (`observability/gc.py`): drops whole old runs — span traces by
   root `run` span `run.id`, checkpoint threads by `thread_id == run_id` across
   any thread_id-keyed table (`checkpoints`, `writes`); VACUUMs both. Policies:
   `--keep-runs N` (default 20) and/or `--keep-days D` (drop = fails either).
   Checkpoint threads with no span record (unknowable age) are left untouched.

## Still deferred (unchanged)

- Codex USD cost always 0.0 (needs an external price table).
- Codex-native session resume/fork not wired (MVP stance shared by adapters).
- Real-vs-fake MCP wire-format reconciliation for Claude/OpenCode beyond what
  the benchmark rounds already validated.
