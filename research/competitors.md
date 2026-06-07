# Competitor Deep-Dives

*(Tavily research, 2026-06-07.)* Focused head-to-head analyses of named competitors against **our**
design (declarative, composable, typed pipeline over swappable multi-vendor coding-agent harnesses).
Where [`existing-orchestrators.md`](existing-orchestrators.md) is a broad one-line-each survey, this
file goes deep on specific tools a stakeholder asks us to position against.

> Naming caution: **"hivemind" is overloaded.** At least four unrelated projects use it — an EU
> research consortium (`hivemind-project.eu`), a Manifund "verifiable orchestration for regulated
> industries" engine, an arXiv "Society of HiveMind" paper (`arxiv.org/abs/2503.05473`), and the
> ones below. Disambiguate before citing.

---

## 1. activeloopai/hivemind — *cross-agent memory layer* (complementary, not a rival)

`github.com/activeloopai/hivemind` · Apache-2.0 · "One brain for all your agents."

**What it is:** a *horizontal memory layer*, not an orchestrator. It sits beside whatever coding
agent you already use (Claude Code, Codex, Cursor, OpenClaw, pi) and makes each smarter from shared
history. Loop: **Capture → Codify → Propagate → Compound.** Every interaction (prompt/tool-call/
response) is captured as a structured trace in **Deeplake**; a background worker mines traces for
repeated patterns and auto-codifies them into `SKILL.md` files; codified skills propagate into every
connected agent's context at inference. Natural-language search over traces. Per-agent integration
via marketplace plugin / hooks / skills / native extension + an `AGENTS.md` block. Tenant isolation,
encryption, `HIVEMIND_CAPTURE=false` opt-out.

**It does NOT** run, schedule, isolate, or coordinate agents. No pipeline, no DAG, no execution
control.

**Overlap with us:** only our **M6b knowledge provider** sits in the same conceptual space
(propagating learned lessons across runs). The design divergence is the interesting part:

| | activeloopai/hivemind | our M6b knowledge provider |
|---|---|---|
| Capture | **Automatic** — background worker mines traces | **Deliberate** — only the `auditor` role writes |
| Gate | None (frictionless) | **Auditor-gated**, per-source grants, server-side deny re-check |
| Store | Deeplake (vector) | Lexical search, no embeddings (MVP) |
| Bet | Frictionless accumulation | Governed, attributable knowledge |

**Verdict: complementary.** Validates the multi-vendor coding-agent market but isn't a pipeline at
all. Possible *integration* story (consume a hivemind-style memory as a knowledge source), not a
competitor.

---

## 2. Claude-Flow "Hive Mind" — *queen-led swarm orchestrator* (direct rival, different axis)

`github.com/ruvnet/claude-flow` (by Reuven Cohen / `ruvnet`) · landed mid-2025 · being rewritten as
**Ruflo** (Rust/WASM) early 2026.

**What it is:** a **queen-led hierarchical swarm orchestrator** layered on Claude Code via MCP +
hooks. A "queen" (strategic / tactical / adaptive) decomposes an objective and delegates to
specialized workers (architect / coder / tester / researcher / security) that coordinate through a
shared **SQLite blackboard** (`.swarm/memory.db`: `shared_state`, `events`, `consensus_state`,
`workflow_state`, `performance_metrics`) and reach decisions via **consensus voting**
(`majority | weighted | byzantine`). Auto-scales to dozens of agents; 87 MCP tools; SPARC phase
modes (`npx claude-flow sparc run`). Two modes: `swarm` (quick) and `hive-mind` (persistent).
Marketing claims ~84.8% SWE-bench solve, 2.8–4.4× speed.

`npx claude-flow hive-mind spawn "Build microservices" --queen-type strategic --max-workers 12 --consensus byzantine`

### Head-to-head

| Dimension | Claude-Flow Hive Mind | orchestrator (this project) |
|---|---|---|
| Coordination model | Emergent, **queen-led swarm** + consensus voting | **Declarative typed DAG** (`DeterministicScheduler` default; agentic supervisor specced) |
| Author's mental model | "Spawn N agents, let them self-organize" | "I author the pipeline; it executes predictably" |
| Reproducibility | Low — emergent by design | High — compiled graph IR, golden-graph test, typed I/O |
| Vendor coupling | **Claude Code only** (native MCP + hooks) | **Multi-harness** — CC + OpenCode built, Codex/ACP specced (harness ≠ model) |
| Scaling philosophy | Scale-out: "unlimited agents," auto-scale, clusters | Scale-correct: bounded retries, `success_criteria`, verdict-gated review loop |
| Memory/state | Heavy central SQLite blackboard + consensus + telemetry; AgentDB semantic queries | LangGraph SQLite **checkpointer** (resumable) + light lexical KB (auditor-gated) |
| Safety / isolation | Relies on Claude Code's own permissions | Owns it: worktree isolation, **7-dim capability model** (deny-wins), shell deny-list |
| HITL | Not a first-class gate | `interrupt()` gates + cross-process resume + merge conflict gate |
| Integration / merge | Agents write directly; coordination via blackboard | Diff capture → 3-way apply onto integration branch → **PR** |
| Coordination comms | Blackboard + consensus votes | Orchestrator agent + span-emitting message bus (hub-and-spoke) |
| Observability | `performance_metrics` table, status/metrics CLI | OTel spans throughout (message + knowledge-write + MCP-call spans) |
| Maturity / adoption | Large adoption, v2.7, → Ruflo rewrite | Pre-release MVP, 240 tests, single integration branch |

### Core philosophical split

- **Claude-Flow bets on emergence** — *more agents + a queen + consensus = intelligence greater than
  the sum of parts.* Give it an objective, trust the swarm to self-organize. Fast when it works;
  hard to reproduce, audit, or constrain when it doesn't.
- **We bet on composition** — *a typed, declarative pipeline you can read, validate, version, and
  replay.* The DAG is the contract. Trades the swarm's emergent ceiling for determinism,
  auditability, and safety rails.

Maps onto the chains-vs-graphs / supervisor-vs-pipeline tension in
[`concepts/orchestration-patterns.md`](concepts/orchestration-patterns.md). Notably our
*specced-not-built* `AgenticSupervisor` mode **is** essentially the queen-led model — so we treat
theirs as one of two modes, with the deterministic pipeline as default. Stronger than "either/or."

### Threat assessment

**Where they out-position us today:** adoption, scale-out story, ecosystem (87 MCP tools), benchmark
marketing, maturity. "Throw 30 agents at it overnight" is their pitch, not ours.

**Where our whitespace survives — sharper against them than against activeloopai:**

1. **Multi-harness vs. Claude-only.** Our single biggest differentiator. Claude-Flow is structurally
   wedded to Claude Code; "swappable harnesses, harness ≠ model" can't be easily retrofitted. Our
   OpenCode adapter + `mixed-harness` example is the concrete proof.
2. **Determinism & typed composition.** Nobody in the swarm camp offers a compiled, validated,
   replayable DAG with typed I/O and `file_scope`. Exactly the gap Claude-Flow does *not* fill — it's
   the opposite design.
3. **Safety/isolation as an owned concern.** Claude-Flow leans on Claude Code's permissions; our
   7-dim deny-wins capability model + worktree isolation + HITL gates target the "prod-DB deletion /
   `rm -rf /`" incidents in [`concepts/safety-sandboxing.md`](concepts/safety-sandboxing.md).
   Decisive for regulated/cautious buyers.

**One genuine caution:** their SQLite blackboard + consensus is a *more developed coordination
substrate* than our M6c message bus (in-memory log + spans). If we ever push into emergent
coordination (our agentic mode), they're years ahead — so keep that mode framed as "optional second
mode," not the headline.

**Net:** a real rival, but on a *different design axis*. We win on portability (multi-harness),
determinism, and safety; they win on scale, emergence, and adoption. The competitive line is
**"governed, portable, declarative pipeline" vs. "Claude-native emergent swarm."**

---

Sources: gathered via Tavily 2026-06-07 — `github.com/activeloopai/hivemind`,
`github.com/ruvnet/claude-flow` (+ `gist.github.com/ruvnet/9b066e77…` Claude Flow playbook,
`mcp.directory/skills/hive-mind-advanced`, `dev.to/stevengonsalvez` Claude-Flow→Ruflo writeup).
