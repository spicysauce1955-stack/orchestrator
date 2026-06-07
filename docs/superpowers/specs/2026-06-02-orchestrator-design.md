# Orchestrator — Design Spec

> **Status:** Approved design (brainstorm complete) · **Date:** 2026-06-02
> **Revised:** 2026-06-07 — added §14 post-MVP enhancements from competitive analysis
> (`research/competitors.md`); folded the durable span store + `status`/`metrics`/`memory` lenses
> into M6d (§9, §12); added milestones M7–M9. MVP boundary (M6) unchanged.
> **Scope of this spec:** full architecture sketch + a detailed, runnable **MVP vertical slice**.
> Grounded in `research/` (snapshot 2026-06-02). Re-verify "current" vendor claims before building.

## 1. Summary

A developer-facing, **declarative** orchestrator that coordinates **coding-agent harnesses**
(Claude Code, Codex, OpenCode, …) as composable, typed pipeline steps. The orchestrated *unit* is a
full coding agent (a harness), never a raw LLM model. The product's differentiation (validated by the
prior-art survey): a **declarative, composable, typed pipeline over a swappable multi-vendor harness
backend**, with first-class isolation, a task DAG, merge, HITL, observability, and safety.

Two execution modes share one core (see §6):
- **Declarative** (default, deterministic) — a compiled DAG.
- **Agentic** (opt-in) — an LLM **orchestrator agent** drives control flow within the same rails.

The MVP builds the **declarative** mode end-to-end and **specs** the agentic mode against a clean seam.

## 2. Key decisions (and why)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Scope** = architecture sketch + one runnable MVP slice | Validate the architecture against something runnable without boiling the ocean. |
| 2 | **Knowledge base** = light context-injection | "Core" = always-injected files; "on-demand" = MCP retrieval over **lexical/file search** (no embeddings yet). Proves the core-vs-indexed split as a config primitive cheaply. |
| 3 | **Harness drive** = adapter interface + native CLI first | Define the swappability seam now; implement Claude Code via `claude -p --output-format stream-json` first; **ACP adapter is the designed-for second impl**. |
| 4 | **Stack** = Python + LangGraph | LangGraph supplies DAG, state, checkpointing, and `interrupt()`-based HITL; richest agent ecosystem. |
| 5 | **MVP pipeline shape** = spine + review loop | `classify → plan → implement → review ⟲ → test → audit → approve → merge`. Exercises every core primitive incl. the cyclic evaluator. |
| 6 | **Authoring** = composable multi-file | Reusable, Pydantic-validated `roles/ skills/ knowledge/ pipelines/` — the "composable" differentiator. |
| 7 | **Orchestrator agent** = first-class, two modes (C) | A supervisor agent owns the run and talks to workers; supported in both declarative (within-rails participant) and agentic (router) modes via one Controller seam. |
| 8 | **MVP build split** | Declarative mode built end-to-end; agentic mode specced. **Two adapters** built: Claude Code + **OpenCode** (covers harness≠model / the `glm` case; previews ACP). |
| 9 | **Checkpointer** = SQLite (MVP) | LangGraph `SqliteSaver`; upgrade to Postgres later. |
| 10 | **Merge conflict** → **HITL gate** (stop & ask) | Semantic-rebase agent deferred. |

## 3. Layered architecture (build vs adopt)

```
ENGINE         declarative pipeline · typed steps · roles/skills/permissions · DAG · scheduler
               · orchestrator agent · merge · HITL · observability          ← BUILD (differentiator)
HARNESS DRIVE  uniform HarnessAdapter (sessions, prompts, tool-calls, permissions) ← ADOPT: ACP later + native CLI now
HARNESSES      Claude Code · Codex · OpenCode · Gemini CLI                   ← ADOPT (swappable)
ISOLATION      git worktrees (default) · containers · microVM sandboxes      ← ADOPT
KNOWLEDGE      core (always-loaded) + on-demand (lexical MCP) · AGENTS.md     ← BUILD thin
```

### Components (one `orch run`)

- **CLI** (`orch run|status|metrics|memory|resume|compile`) — entry point; streams progress; resumes
  interrupted runs; `status`/`metrics`/`memory` are lenses over the span store (§9). (`orch init` /
  `orch new --template` scaffolder is post-MVP, §4.2/§14.)
- **Config loader + validator** — reads `.orchestrator/`, validates against Pydantic schemas, resolves role/skill/knowledge references by name.
- **Compiler** — pipeline → LangGraph `StateGraph`; topo-sort; typed-I/O reference checks; `file_scope` overlap warnings.
- **Controller** (the mode seam, §6) — `DeterministicScheduler` | `AgenticSupervisor`.
- **Step executors** — `TaskStep` (cheap LLM glue) · `AgentStep` (full harness run in a worktree).
- **Run context / state** — typed `RunContext` threaded through the graph; per-step artifacts (output + diff + branch + cost); budget rollup. Persisted by LangGraph checkpointer (SQLite).
- **Orchestrator agent + message bus** (§7) — supervisor agent; all messages emitted as spans.
- **HarnessAdapter layer** (§5) — interface + `ClaudeCodeCLIAdapter` + `OpenCodeCLIAdapter`; ACP/Codex later.
- **Isolation manager** — git worktree per agent step; credential exclusion; cleanup.
- **Knowledge provider** (§8) — core injection + on-demand lexical MCP search + access-gated write.
- **Evaluator** — `success_criteria` (shell) · agent-as-judge verdict · test-count gate · `max_retries`.
- **HITL gate** — LangGraph `interrupt()` → checkpoint → notify → `orch resume`.
- **Merge manager** — `sequential-rebase` → PR; conflict → HITL gate.
- **Observability + Safety** — OTel spans; cost caps; capability resolution + translation; deny-list; never-push-main.

## 4. Config model (authoring surface)

All files under `.orchestrator/`, every file Pydantic-validated.

```
.orchestrator/
├─ roles/        implementer.yaml · reviewer.yaml · planner.yaml · auditor.yaml
├─ skills/       test-runner.yaml · code-review.yaml      # reusable capability bundles
├─ knowledge/    core.yaml (always) · index.yaml (on-demand)
├─ pipelines/    feature.yaml
└─ config.yaml   # defaults: isolation, budgets, observability sink, safety, mode
```

### Role — "which harness + how it behaves"
```yaml
# roles/implementer.yaml
harness: claude-code          # claude-code | codex | opencode  (the orchestrated unit)
model: opus                   # OPTIONAL — omit for harness default; glm → opencode + zhipu/glm-4.6
permissions: edit             # read-only | edit | full   → a PRESET over the 7 access dimensions
access:                       # OPTIONAL per-dimension overrides (see §4.1)
  filesystem: { write: ["src/**","tests/**"], read_only: [".git",".claude"] }
  network:    { egress: ["pypi.org","github.com"] }
  shell:      { deny: ["rm -rf","git push --force","DROP TABLE"] }   # merged with global deny-list
  git:        { push_to_main: false, open_pr: true }
  knowledge:  { read: [repo-conventions, lessons], write: [] }       # read-only by default
skills: [test-runner]         # contributes its own tool grants
knowledge: [repo-conventions] # which sources this role gets (core is always on)
mcp: [repo-index]             # MCP servers injected; expose mcp__repo-index__* tools
budget: { max_usd: 5, timeout_s: 1800 }
```

### Skill — reusable capability bundle (instructions + tool grants + optional MCP/knowledge)
```yaml
# skills/test-runner.yaml
instructions: "Run `pytest -q` after each change; never delete or weaken tests."
tools: [Bash(pytest), Read, Edit]      # skills CAN grant tools (clamped by the role's profile)
```

### Knowledge — core (always) + on-demand (retrieval)
```yaml
# knowledge/core.yaml — always injected into every session's working dir
inject: [AGENTS.md, docs/architecture.md]
# knowledge/index.yaml — on-demand, exposed as an MCP tool
sources: [docs/**, src/**]
backend: lexical                       # MVP: file/lexical search (no embeddings)
```

### Pipeline / step — the DAG (MVP shape B)
```yaml
# pipelines/feature.yaml
mode: declarative                       # declarative | agentic
inputs: { task: string }
steps:
  - id: classify
    type: task
    prompt: "Classify <task> as: bugfix | feature | refactor"
    output_schema: { kind: enum[bugfix,feature,refactor] }
  - id: plan
    role: planner
    needs: [classify]
  - id: implement
    role: implementer
    needs: [plan]
    file_scope: ["src/**"]
    isolation: worktree                 # worktree (default) | container | sandbox
    success_criteria: "pytest -q"
    max_retries: 2
  - id: review                          # agent-as-judge (read-only role)
    role: reviewer
    needs: [implement]
    on_reject: implement                # the one cyclic edge, bounded by implement.max_retries
  - id: test
    role: implementer
    needs: [review]
    success_criteria: "pytest -q && ruff check"
  - id: audit
    role: auditor                       # the only role with knowledge write access
    needs: [test]
  - id: approve
    type: gate
    needs: [audit]
    require_approval: true
  - id: merge
    type: task
    needs: [approve]
    merge_strategy: sequential-rebase    # never push main; opens PR
```

**Typed I/O / artifacts.** Each step declares an `output_schema`; outputs become typed artifacts
in the run context, referenceable as `<step.output>`. `agent` steps always capture the diff/branch
via `git diff` in the worktree (harness JSON omits diffs). The compiler validates referenced
artifacts exist and types align.

**Composites (specced, lowered to the same node/edge graph):** `sequence`, `parallel`, `router`
(classify→branch), `best-of-n` (fan-out). MVP runs a flat list + one `on_reject` cycle. **`best-of-n`
selection** (post-MVP, §14): the N candidates are not picked first-wins — a read-only **judge** (the
existing `reviewer`/agent-as-judge role) scores them and selects the winner. This is our governed
analog of swarm "consensus voting": one accountable judge with a verdict artifact, not an opaque vote.

### 4.1 Access / capability model (7 dimensions)

`permissions: read-only|edit|full` is a **preset** that expands into seven dimensions, each
overridable per role/step:

1. **Filesystem** — read scope · write scope (`file_scope`) · credential paths excluded (`~/.ssh`, `~/.aws`, `~/.kube`, `~/.config/gh`, `.env*`) · harness config (`.git/`, `.claude/`) read-only.
2. **Tools** — allow / deny tool list.
3. **Shell / commands** — deny-list hard-blocks (`rm -rf /`, `git push --force`, `git reset --hard`, `curl|bash`, `DROP TABLE`, `npm publish`).
4. **Network egress** — default-deny + domain allowlist + blocked metadata IPs (`169.254.169.254`, `metadata.google.internal`).
5. **Git / VCS** — never push to `main`; PR-only.
6. **Secrets** — short-lived scoped tokens injected at runtime, never baked into images.
7. **Knowledge** — per source `read | write | none`. **Core is always read, never writable.** Write is *never* in a preset — always an explicit per-source grant (e.g. only `auditor` gets `write: [lessons]`).

**Resolution:** effective set = `(role grants ∪ skill grants ∪ mcp grants) ∩ permission profile`;
**deny always wins**; least-privilege. Computed once per step, then **translated** to harness-native
controls:
- **Claude Code** — `--allowedTools`/`--disallowedTools` · `--permission-mode` · sandbox `denyRead`.
- **Codex** — `--sandbox workspace-write` · `approval_policy` · OS Landlock/seccomp.
- **OpenCode** — `permission` map · **no OS sandbox → orchestrator supplies worktree/container isolation**.

A role speaks in abstract capabilities, so it is portable across harnesses.

### 4.2 Recipe / template library (post-MVP, §14)

Declarative configs have a blank-page problem. A curated, versioned **template library** of vetted
pipelines (e.g. `review-heavy`, `bugfix-fast`, `mixed-harness`) — promoted from today's `examples/` to
first-class, named recipes — plus an `orch init` / `orch new --template <name>` scaffolder that seeds a
working `.orchestrator/` in one command. Adoption lever, not a new engine capability.

## 5. Harness adapter (the swappability seam)

```python
class HarnessAdapter(Protocol):
    async def start_session(self, *, cwd: Path, capabilities: ResolvedCaps,
                            mcp_servers: list[McpServer]) -> SessionId: ...
    async def prompt(self, session: SessionId, text: str, *,
                     output_schema: dict | None) -> AsyncIterator[Event]: ...
    async def resume(self, session: SessionId) -> SessionId: ...
    async def cancel(self, session: SessionId) -> None: ...
```

**Normalized event model** (every adapter emits this; deliberately shaped like ACP `session/update`):
```
SessionStarted(session_id) · MessageChunk(text) · ToolCall(name, status:pending|in_progress|completed|failed)
· FileEdit(path, kind) · Cost(usd, tokens) · Done(result, is_error)
```

**ClaudeCodeCLIAdapter (MVP).** Spawns
`claude -p "<prompt>" --output-format stream-json --add-dir <worktree> --json-schema <schema>
--allowedTools <…> --disallowedTools <…> --permission-mode acceptEdits --mcp-config <generated.json>`,
parses NDJSON (`system/init`→`SessionStarted`, deltas→`MessageChunk`, tool events→`ToolCall`, final
object→`Done`+`Cost`), resumes via `--resume <id>`.

**OpenCodeCLIAdapter (MVP, 2nd).** `opencode run --format json --model <provider/model> --dir <worktree>`;
parses its NDJSON (`step_start`/`text`/`tool_use`/`tool_result`/`step_finish` with `.cost`).
Demonstrates harness≠model (75+ providers; `glm`) and previews the native-ACP path.

**Adapter owns** (because harnesses don't give them cleanly): **diff capture** (`git diff` in worktree)
and **capability translation** (`ResolvedCaps` → harness flags).

**Why this pays off:** the future `ACPAdapter` implements the same interface against `session/new` +
`session/update` + `session/request_permission` — near-literal mapping. New harnesses = "implement the
Protocol."

## 6. Execution model & the two-mode seam

**Compile.** Pipeline → LangGraph `StateGraph`: step→node, `needs`→edge, `on_reject`→conditional
(cyclic) edge. Compile-time validation: topo-sort (reject undeclared cycles), typed-I/O references,
`file_scope` overlap warnings. Composites lowered to the same graph.

**Run state.** One typed `RunContext` threaded through the graph (artifacts + cost + status); LangGraph
**SqliteSaver** checkpoints after every node → enables **both** resume and HITL.

**AgentStep lifecycle:** (1) resolve capabilities → harness flags · (2) create worktree (creds
excluded, config read-only) · (3) inject knowledge (core files + wire MCP search/write per access) ·
(4) drive harness, stream NDJSON → OTel spans, enforce budget/timeout · (5) capture diff via `git
diff` · (6) run `success_criteria`; on fail with retries left, re-prompt with failure output (inner
loop, `max_retries`) · (7) emit typed artifact.

**Review loop.** `review` writes a `verdict`; conditional edge: `approve`→`test`, `reject`→`implement`
(`attempt++`, bounded by `max_retries`). A **test-count gate** runs alongside `success_criteria` so an
agent cannot "go green" by deleting assertions.

**HITL gate.** `approve` node calls LangGraph `interrupt()` → checkpoint → CLI prints diff + audit
summary + run id → `orch resume <id> --approve|--reject` re-enters from the checkpoint. Gates sit only
at **deterministic boundaries** (after `audit`, before `merge`) so resume never replays an agent.

**Merge.** On approval, `sequential-rebase` onto base → **open a PR** (never push `main`). Rebase
conflict → raise a **HITL conflict gate** (semantic-rebase agent deferred).

**Failure & cleanup.** Budget-exceeded / timeout / non-zero terminal `success_criteria` fails the step
→ run halts with state checkpointed (resumable/inspectable). Worktrees auto-cleaned on success,
retained on failure (configurable); ephemeral containers always destroyed.

### The Controller seam (mode C)

`mode:` selects one of two `Controller` implementations over the **same shared core** (config,
capability resolution, adapters, isolation, knowledge, evaluators, step executors, merge,
observability):

- **`DeterministicScheduler`** (declarative, default) — static compiled LangGraph; fixed edges. The
  orchestrator agent participates *within the rails* (answers questions, delegated routing) but does
  not choose structure. **Built in MVP.**
- **`AgenticSupervisor`** (agentic, opt-in) — the orchestrator agent IS the router: chooses the next
  role/step, may spawn agents; the YAML is its toolbox + constraints. **Specced, not built in MVP.**

**Rails bind in both modes:** HITL gates · safety deny-list · per-step budget/timeout ·
never-push-main. Agentic mode gains *structural* freedom, not *safety* freedom.

## 7. Orchestrator agent & messaging

A first-class LLM agent (its own Role + budget) that **owns the run** (holds goal + compiled pipeline)
and is the entity the user converses with. Communicates over a **message bus where every message is an
OTel span** (hub-and-spoke = traceable; coordination board is a derived view):

- **orch → worker** — answer a stuck worker's question, inject guidance, follow-up prompt (session
  resume / ACP).
- **worker → orch** — clarifying question, permission request, verdict, "stuck" report. *A worker's
  question can be answered by the orchestrator instead of always halting to a human.*
- **worker ↔ worker** — **mediated through the orchestrator** in the MVP; direct peer messaging
  (A2A / Agent-Teams) is a later increment.

**MVP scope of the agent:** run-owner doing the shared coordination only — classify, relay the review
verdict to the implementer on loop-back, and answer worker questions. (Full structural autonomy is the
`AgenticSupervisor`, specced.)

## 8. Knowledge base

Light/context-injection (decision #2):
- **Core** (`knowledge/core.yaml`) — files written into each session's working dir (AGENTS.md + pinned
  docs). Always read, never writable.
- **On-demand** (`knowledge/index.yaml`) — exposed as MCP tools: `mcp__knowledge__search` (granted to
  any role with `read`) over **lexical/file search** (no embeddings in MVP).
- **Gated write** — `mcp__knowledge__write` granted **only** to roles with `write` on that source
  (e.g. `auditor`). The resolver refuses to hand it to others even if a skill tries to grant it
  (deny-wins). MVP "write" = provider appends/updates an entry in `.orchestrator/knowledge/lessons.md`,
  captured in the audit log.

**Closed loop:** `audit` writes durable lessons → next run's `plan`/`implement` read them as
core/on-demand context.

### 8.1 Knowledge mining (post-MVP, §14)

Today knowledge is written *only* on explicit auditor action — nothing is captured from what agents
actually did. Borrowing the *capture → codify → propagate* idea (but **not** the ungated auto-write)
from cross-agent memory tools: an **offline miner** scans the durable span store (§9) after runs for
repeated patterns (recurring failures, fixes, decisions), and emits **candidate lessons**. Candidates
are not written directly — the **`auditor` role vets them** (its `audit` step gains a "review mined
candidates" duty) and approves through the existing auditor-gated `mcp__knowledge__write` path
(deny-wins, §4.1/§8). The differentiator stands: capture is automatic, but every write stays
**governed and attributable**. Depends on the queryable span store (M6d).

## 9. Observability, safety & testing

**Observability** (the orchestrator's job): OTel GenAI spans for `run`, `step`, `harness session`,
`tool-call`, `file-edit`, `eval`, `merge`, each **message-bus message**, `knowledge-write`, `MCP-call`,
`HITL gate`; cost/tokens roll up per step → run vs budget. MVP sink: OTLP to file/SQLite; Langfuse
optional exporter.

**Durable, queryable span store (M6d).** The SQLite sink is a **structured span table** (one row per
span with `run_id`, `kind`, `parent`, timing, cost, attrs) — the *single record of truth*. `orch status`
queries it rather than re-parsing raw output. (This is the "structured & queryable" borrow from
swarm-style coordination blackboards — but spans stay the only durable record; we do not add a parallel
store.) Three CLI lenses over the same table:
- `orch status <run>` — run/step state (which step, pass/attempt, terminal verdict, PAUSED/resume hint).
- `orch metrics <run>` — cost/tokens/timings rolled up per step and per run vs budget.
- `orch memory <run>` — the message-bus log + knowledge writes for the run.

This store is also the data source the post-MVP knowledge miner (§8.1) scans.

**Safety baseline.** *Built in MVP:* worktree isolation (default) · credential-path exclusion ·
harness config read-only · command deny-list hard-blocks · never-push-main → PR-only · writer≠reviewer
(role permissions) · test-count gate · per-step budget + timeout · gated knowledge writes · metadata-IP
egress block. *Documented, deferred:* container/microVM sandbox (gVisor/Firecracker) + full default-deny
egress enforcement · bot-account identity + org rulesets.

**Testing (TDD — tests precede implementation):**
- **Unit** — schema validation; capability resolution (deny-wins, knowledge-write gating); compiler
  (topo, typed-I/O, `file_scope` warnings).
- **Adapter contract tests** — against a **fake harness** stub binary emitting canned NDJSON (zero API
  cost); both adapters satisfy the same contract.
- **Integration** — full pipeline run against the fake harness + a throwaway git repo: worktree
  creation, `success_criteria`, review loop (reject→implement→approve), HITL `interrupt`→`resume`,
  merge→PR (+ conflict→HITL).
- **Golden-graph test** — pipeline compiles to an expected node/edge set (locks determinism).

## 10. MVP scope boundary

**Built & runnable:** composable `.orchestrator/` config + schemas · compiler → LangGraph
(`DeterministicScheduler`) · `task` + `agent` executors · pipeline shape B · 7-dimension capability
model + resolution + translation · `HarnessAdapter` + ClaudeCode + OpenCode adapters · worktree
isolation · knowledge provider (core + on-demand lexical + auditor-gated write) · evaluator
(success_criteria, agent-as-judge verdict, test-count gate, max_retries) · HITL gate
(interrupt/resume) · merge (sequential-rebase→PR, conflict→HITL) · orchestrator agent as run-owner +
span-emitting message bus · OTel spans + cost + `orch status` · SQLite checkpointer · CLI
(`orch run|status|resume|compile`) · safety baseline above.

**Specced, not built:** `AgenticSupervisor` mode · best-of-N fan-out + parallel reviewers (with
**judge-based selection**, §4/§14) · ACP adapter · Codex adapter · container/microVM sandbox + full
egress · embeddings/vector knowledge · semantic-rebase conflict agent · direct worker↔worker (A2A) peer
messaging · durable execution (Temporal/Conductor) · A2A remote-agent delegation · **knowledge mining**
(§8.1) · **recipe/template library + `orch init`** (§4.2). The last three are the post-MVP milestones
M7–M9 (§12); see §14 for provenance.

## 11. Repository layout

```
orchestrator/
  cli.py
  config/        schemas.py · loader.py
  compile/       compiler.py · validate.py
  runtime/       controller.py · scheduler.py · state.py · executors.py
  agents/        orchestrator_agent.py · message_bus.py
  harness/       adapter.py · events.py · claude_code.py · opencode.py
  isolation/     worktree.py
  knowledge/     provider.py · lexical.py
  eval/          criteria.py · verdict.py
  merge/         merge.py
  safety/        capabilities.py · denylist.py
  observability/ spans.py · status.py
tests/           unit/ · integration/ · fixtures/fake_harness/
```

## 12. Milestones (each independently runnable)

- **M1** — config + schemas + compiler: `orch compile` validates a pipeline (no execution).
- **M2** — adapter interface + ClaudeCode adapter + worktree: a single `plan` agent step runs end-to-end with spans.
- **M3** — full DAG executor + task step: `classify → plan → implement` with `success_criteria`/retry.
- **M4** — review loop + agent-as-judge + test-count gate.
- **M5** — HITL gate + resume + merge→PR + conflict gate.
- **M6** (final MVP milestone, built as sub-milestones) — **M6a** OpenCode adapter + harness registry ·
  **M6b** knowledge provider (core + on-demand lexical + auditor-gated write) · **M6c** orchestrator
  agent (run-owner, message bus, worker Q&A) · **M6d** observability/status + safety baseline polish —
  now scoped to build the **durable, queryable span store** and the **`orch status`/`metrics`/`memory`**
  lenses over it (§9).

**Post-MVP milestones** (from competitive analysis, §14; planned one at a time when next, per project
rhythm — not planned in advance):
- **M7** — knowledge mining (§8.1): offline miner over the span store → candidate lessons → `auditor`
  vets → existing gated write. Depends on M6d's span store.
- **M8** — adoption: recipe/template library + `orch init` / `orch new --template` scaffolder (§4.2).
- **M9** — `best-of-n` fan-out with judge-based selection (§4): N candidates scored/selected by the
  read-only agent-as-judge role.

## 13. Open questions / risks

- **LangGraph impedance** — confirm the typed-pipeline + worktree + cyclic `on_reject` map cleanly onto
  LangGraph `StateGraph`/checkpointer during M1–M2; if friction is high, the `DeterministicScheduler`
  can fall back to a custom topo executor without changing the config model or Controller seam.
- **HITL resume replay** — keep gates strictly at deterministic boundaries; verify resume never
  re-invokes a harness.
- **OpenCode has no OS sandbox** — the orchestrator must supply isolation; container isolation is
  deferred, so MVP OpenCode runs are trusted/local only.
- **Merge-conflict rate (~27%)** — MVP stops to HITL; revisit semantic-rebase agent early as the first
  post-MVP increment if conflicts dominate.
- **Agent-as-judge cost** — reviewer runs a full harness; cap with budget + prefer deterministic
  `success_criteria` where an oracle exists.

## 14. Post-MVP enhancements (competitive analysis, 2026-06-07)

Sourced from a head-to-head against **Claude-Flow "Hive Mind"** (queen-led emergent swarm, Claude-only)
and **activeloopai/hivemind** (cross-agent memory layer) — see [`research/competitors.md`](../../../research/competitors.md).
The guiding principle: **borrow tactics that strengthen our bets (declarative, deterministic,
multi-harness, governed); resist anything that erodes them** (auto-scaling, ungated auto-writes,
emergent swarm as default, Claude-only coupling). Five enhancements:

| # | Enhancement | Borrowed from | Lands in | Spec |
|---|-------------|---------------|----------|------|
| 1 | **Mined-candidate knowledge capture** — offline miner → `auditor` vets → gated write | hivemind *capture→codify→propagate* (minus the ungated write) | **M7** | §8.1 |
| 2 | **Durable, queryable span store** — structured SQLite span table as single record of truth | Claude-Flow's SQLite coordination blackboard (minus the parallel store) | **M6d** | §9 |
| 3 | **`status`/`metrics`/`memory` CLI lenses** over the span store | Claude-Flow's `hive-mind status`/`metrics`/`memory` triad | **M6d** | §3, §9 |
| 4 | **Recipe/template library + `orch init`** scaffolder | Claude-Flow's SPARC named-workflow templates | **M8** | §4.2 |
| 5 | **`best-of-n` judge-based selection** — agent-as-judge scores/selects candidates | Claude-Flow's consensus voting (one accountable judge instead) | **M9** | §4, §10 |

**Why these and not more:** #2/#3 only shape the not-yet-built M6d, so they fold into the MVP close
without expanding scope. #1 turns our biggest gap (no automatic capture) into a *governed* feature that
out-positions hivemind on auditability. #4 is the cheapest adoption lever (declarative configs have a
blank-page problem). #5 gives the already-specced `best-of-n` a principled selection strategy. Deliberately
**not** adopted: dynamic worker auto-scaling, ungated mining, emergent-swarm-as-default — those belong (if
ever) inside the opt-in `AgenticSupervisor` mode (§6), never the deterministic default.
```
