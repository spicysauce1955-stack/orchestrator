# M6c Orchestrator Agent — Follow-ups

> M6c shipped **ready-to-merge**: **240 tests green, ruff clean**. It adds the
> orchestrator agent + span-emitting message bus (spec §7 MVP). The agent is NOT
> a router — the `DeterministicScheduler` remains the executor and calls into the
> agent at its seams. Three coordination actions are implemented: (1) **classify**
> — every non-merge task step is routed through `agent.run_task`, which delegates
> to `run_task_step` and emits a `classify`-kind `message` span marking the
> orchestrator's awareness of that step. (2) **verdict relay** — on reject,
> `_router` calls `agent.relay_verdict`, which sets `ctx.relayed_feedback` and
> emits a `verdict`-kind span; the feedback is injected (one-shot `pop`) into the
> implementer's next prompt. (3) **worker Q&A** — a step opts in with
> `max_questions` + a `question` field in `output_schema`; the orchestrator
> answers via a fresh LLM call (its own read-only Role) and the SAME worktree is
> re-prompted, bounded by `max_questions`. Every coordination action emits exactly
> one OTel `message` span (via `SPAN_MESSAGE` in `observability/spans.py`) and
> appends to the in-memory `MessageBus.log` (the coordination board). The
> orchestrator uses its own read-only Role (default constructed when the workspace
> defines no `orchestrator` role entry). Reserved `orchestrator` role + `qa-demo`
> pipeline example ship with the milestone. Built and tested entirely against the
> **existing fake harnesses** (zero API cost); manual `orch run qa-demo` smoke
> completed with the orchestrator answering the worker.

## Headline note: coordination layer, not a router

The orchestrator agent is the within-rails declarative participant described in
spec §6. It observes and acts at the seams the scheduler exposes; it does NOT
choose which agents run, in what order, or how many worktrees to spawn — that
structure comes from the pipeline spec itself. The specced `AgenticSupervisor`
(dynamic routing, free-form planning) is a distinct, unbuilt concept. The user
does not yet converse with the agent; all interactions are scheduler-mediated.

## MVP fidelity notes

- **`MessageBus.log` is in-memory / process-local.** The durable coordination
  record is the `message` spans written to the OTel store. The coordination board
  (`orch status` rendering of these spans) is M6d scope.
- **Worker question detection is output-schema-based, not event-based.** A step
  signals a question by setting the `question` field in its harness result
  `output_data`; there is no mid-stream `Question` event. `max_questions`
  defaults to 0 (opt-in). After exhausting `max_questions` the step proceeds with
  the last result as-is — if it still carries a `question` field, that surfaces in
  `output_data`, not as an error.
- **Orchestrator `answer` is a fresh one-shot LLM call.** The agent holds no
  conversation memory across answers; each call is independent. Relayed feedback
  is injected once per loop-back via a one-shot `pop` from `ctx.relayed_feedback`;
  the `on_reject` cycle regenerates it each time.
- **All non-merge task steps route through `agent.run_task` as `classify`-kind
  coordination.** MVP treats the canonical task step as a classify action. A
  second task-step type (e.g. a sub-delegation kind) would warrant a distinct
  `kind` value; none exists yet.
- **Worker↔worker communication is mediated-only.** Workers share context only
  through the orchestrator (via relay or Q&A); there is no direct A2A channel.
- **Test-harness coupling note:** in fake-harness tests the orchestrator's
  `answer` prompt is worded to avoid the fake harness's routing keywords
  (`classify` / `review` / `question`) so that it routes to `default`; real
  harnesses do not use keyword routing and are unaffected. This is documented in
  `fake_harness.py`.

## Deferred / out of M6c scope (not bugs)

- **`orch status` does not yet render the coordination board.** `MessageBus.log`
  and the `message` spans are the data source; rendering them in `orch status` is
  M6d scope.
- **Test-infra debt: `_repo` git-init helper is duplicated.** The `_repo`
  git-init helper is now copy-pasted across several `tests/integration/` files. A
  shared `conftest.py` fixture would consolidate this alongside the existing
  `_rpc_helpers.py`. Non-blocking.
- **`role.model` still not threaded to adapters.** Carried project-wide gap from
  M1/M6a — unchanged by M6c. The `Role.model` field has been unconsumed since M1;
  `HarnessRegistry` is keyed by `Harness`, not `(harness, model)`.
- **Real-vs-fake MCP reconciliation (from M6b) still pending.** The MCP wire
  format for both the Claude and OpenCode adapters has not been verified against
  the real binaries. Deferred since M6b; see M6b follow-ups for full detail.

## Remaining M6 scope (after M6c)

- **`orch status`**: render checkpoints and spans including `message`-kind spans
  (the coordination board) and knowledge-write spans — the `MessageBus.log` and
  message spans are its data source. This is M6d.
- **Safety baseline polish** (M6d).

After those, M6 (the final MVP milestone) is complete.
