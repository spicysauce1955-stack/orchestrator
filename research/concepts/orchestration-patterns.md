# Orchestration Patterns for Coding Agents

*(Tavily research, 2026-06-02.)* The engineering patterns for running and coordinating multiple
autonomous coding agents on a codebase — the vocabulary for our "configurable pipeline" over
harnesses. Each maps to a config primitive (see "Implications").

## 1. Git worktrees — per-agent isolation (default)
`git worktree add` gives each agent its own checked-out branch/dir sharing one `.git`. Two agents
can't clobber each other at the OS level; conflicts defer to merge time (visible, not silent).
- **Use:** any time >1 agent touches the repo; runs >a few minutes. **Trade-offs:** disk cost (a full
  working tree each — one practitioner: 172 GB across 371 worktrees); does **not** isolate shared
  external state (DBs, Docker daemon, ports, caches) or credentials.
- Native in Claude Code (`--worktree`, `/batch`), Cursor 3 (`/worktree`, up to 8), Windsurf. Tooling: Claude Squad, ccswarm, dmux, uzi, CodeRabbit git-worktree-runner.

## 2. Containers / sandboxes — per-agent execution isolation
Stronger than worktrees: separate filesystem/network/process (Docker/devcontainer → gVisor → Firecracker microVM). Needed for unattended ("YOLO") runs and untrusted code. **Dagger container-use** (MCP) = container + worktree per agent. See [`safety-sandboxing.md`](safety-sandboxing.md).

## 3. Parallel fan-out + best-of-N
Dispatch the same task to N agents (each isolated), then **select the best** via an evaluator.
- **Evaluators (strong→weak):** test suite as oracle (first all-green wins) > CI/lint/type gate > **agent-as-judge** (replays + runs the code, evaluates trajectory) > LLM-as-judge (⚠️ weak on correctness — Cohen's κ ~0.21, ~50% FP for GPT-4 on code; use for style not correctness) > human pick.
- **Use:** high quality variance + automatable oracle + time matters (pay N× cost). Cursor 3 `/best-of-n`, Dagger container-use, Hermes `/batch`.

## 4. Conflict resolution / merging N agents' diffs
N branches from one base must converge to `main`. **~27.67% of agentic PRs hit merge conflicts**
(AgenticFlict, N=107k; Codex 32%, Claude Code 27%, Copilot 15%). Worse: **semantic conflicts** (compiles + passes tests but logically broken) that git can't detect.
- **Strategies:** file-ownership partition (assign non-overlapping file scopes; flag "collision hotspots" like configs/registries to one owner); **sequential merge + rebase chain**; three-way/intent-aware resolution; **semantic-rebase sub-agent** (re-implement intent on new `main`); GitLab 19.0 autonomous MR conflict resolution.

## 5. Supervisor / orchestrator over agents
Central planner: goal decomposition → task routing → **dependency ordering (DAG)** → state tracking → aggregation. *"The orchestrator is the most critical component — if it mis-decomposes or mis-routes, the pipeline fails regardless of worker quality."*
- **Agent-sized task** = fits one context window, no unresolved deps at start, deterministic success criterion, bounded non-overlapping file scope.
- Topologies: hub-and-spoke (traceable), hierarchical sub-agents (teams of teams), adaptive planning (risk: goal drift). Examples: Claude Code Agent Teams (shared task list + peer messaging), LangGraph supervisor, AdaptOrch (dynamic topology selection, +12–23% over static).

## 6. Evaluator / review loops (iterate-until-green)
Submit output to a deterministic or LLM evaluator before accepting; on fail, feed details back and retry to a budget.
- **Inner loop** (per-agent): test/lint hooks fire after each edit (Claude Code hooks, CircleCI Chunk). **Outer loop** (CI): integration/E2E/security only CI can run.
- ⚠️ Failure modes: flaky tests → infinite loops; **"patch the test to go green"** (agent deletes the failing assertion); infeasible-task loops. Mitigate with test-count gates + max-retries + agent-as-judge.

## 7. Human-in-the-loop checkpoints
Architectural, non-bypassable pause points: **plan/spec gate** (approve plan before code), **diff review before merge**, **risky-action gate** (migrations/deploys/deletes), **architectural-change gate** (>5 files / diff not describable in one sentence). LangGraph `interrupt()`, Claude `require_plan_approval`, GitHub draft PRs + protected branches. ⚠️ resuming after a non-deterministic step may replay it.

## 8. Observability & state for long multi-agent runs
Answer who-did-what / cost / status / why-it-failed: LLM-call spans, tool-call spans, reasoning traces, **handoff spans across agents**, per-task cost rollups, online eval scores. OTel GenAI conventions; Langfuse/Phoenix/Braintrust/Datadog. Coordination state = shared task board (Hermes `/batch` markdown table; Claude Agent Teams shared list) — a *derived view* of span data, not the source of truth.

## Implications for our declarative orchestrator
Each pattern → a config primitive:
1. **`isolation:`** per task — `worktree | container | sandbox` (not global; mixed within a run).
2. **Task DAG:** `depends_on:` + `file_scope:` per task; scheduler topo-sorts; overlapping scopes → plan-time warning (primary conflict-avoidance).
3. **`success_criteria:`** per task (shell exit 0/≠0) run in the agent's worktree post-completion; `max_retries` → deterministic iterate-until-green (replaces ad-hoc "loop until green").
4. **`merge_strategy:`** `sequential-rebase | parallel-merge-owner-priority | human-gate` — merging is first-class (~27% conflict rate).
5. **`require_approval:`** per task — composable interrupt; pause→persist→notify→resume (LangGraph `interrupt()` semantics over our queue).
6. **`strategy: best-of-n, n:`** as a first-class topology; default evaluator = test-suite oracle; LLM-as-judge opt-in only.
7. **Observability is the orchestrator's job**, not each agent's — emit OTel spans for assignment/start/tool-calls/completion/merge/eval/cost; derive the status board from spans.

Sources: see [`../sources.md`](../sources.md) → "Patterns".
