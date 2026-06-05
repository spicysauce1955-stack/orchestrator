# M4 Review Follow-ups

> From the final holistic review of M4 (2026-06-05). M4 shipped **ready-to-merge**:
> 147 tests green, ruff clean. The cyclic `on_reject` review loop runs end-to-end through the compiled
> LangGraph `StateGraph` — a read-only `review` agent produces a verdict (parsed from the harness
> result), a verdict-aware router sends approve→forward / reject→`implement` **bounded by max_retries**
> (termination proven under persistent reject), and a **test-count gate** fails a step that deletes
> tests alongside `success_criteria`. Folds in the M3 follow-ups: per-step attempt counter + `/{attempt}`
> branch suffix (no cycle re-entry collision), verdict router via the `wire_edges(router=)` seam.
> `orch run review-demo` demonstrates `classify → plan → implement → review ⟲ → test`.

## Must decide in M5 (merge sits after `test`; it should act on the loop's outcome)

- **Exhausted / invalid review verdict does NOT halt the run.** When `implement.max_retries` is
  exhausted with a standing `reject` (or the verdict is missing/unparseable), the router fails open and
  proceeds forward to `test`; the reject verdict is only *recorded* in `review.output_data`. Nothing
  currently blocks an eventual merge. **M5 must decide:** should merge refuse on a non-`approve`
  terminal review verdict (block + HITL), or proceed? Recommended: the merge step (M5) inspects the
  last `review` artifact's verdict and gates on it.
- **`Done.is_error` vs `success_criteria` precedence (carried from M3).** A passing `success_criteria`
  clears a harness `Done.is_error=True` (`runtime/executors.py`, success-branch). The `review` judge has
  no `success_criteria` so its harness error is preserved — but any future judge/step that *does* carry
  criteria would mask a harness error. Revisit when M5/M6 adds steps that combine a judge verdict with
  a deterministic criteria.

## Deferred (carry forward, not bugs)

- **`max_retries` overload** (design decision #4). One `Step.max_retries` bounds BOTH the inner
  `success_criteria` retry (within one execution) and the outer review-reject re-runs. Acceptable MVP
  overload; split into distinct fields if the two budgets need to differ.
- **Cross-step filesystem isolation.** Each agent step runs in a fresh worktree off HEAD; `implement`'s
  edits are captured as `diff`/`output` but NOT applied to HEAD, so `review`/`test` see implement's work
  only via the injected `{{implement.output}}` text, not the filesystem. Correct for agent-as-judge MVP;
  **resolved by merge in M5** (applying diffs to HEAD so downstream steps build on prior work). Until
  then, `test` runs against HEAD-without-implement's-changes.
- **`count_tests` is a pytest-style regex heuristic** (`eval/criteria.py`). A polyglot repo or unusual
  test-file naming evades the gate. Documented MVP; generalize (per-language counters / configurable
  collect command) if needed.
- **Real `--resume` across retries** (carried from M2/M3): the retry inner loop re-prompts the same
  worktree without `--resume <harness_session_id>`.

## From earlier milestones, still open

- **`output_schema` → harness structured output** (`--json-schema`): threaded but not translated;
  task/review steps parse the textual result instead (M3/M2 follow-up).
- **MCP wiring / knowledge injection, OpenCode adapter, `orch status`** → M6.
- **Stale docstrings cleaned in M4** (`compile/compiler.py`, `runtime/executors.py`); watch for others
  drifting as milestones land.
