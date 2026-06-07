# The Landscape: Coding-Agent Orchestration

*(Tavily research, 2026-06-02.)* Map of the space for a declarative orchestrator over coding-agent
harnesses, and where we adopt vs. build.

```
┌──────────────────────────────────────────────────────────────────────┐
│  OUR ENGINE         Declarative pipeline · typed steps · roles · DAG   │  ← BUILD (the differentiator)
│                     scheduler · merge · HITL · observability           │
├──────────────────────────────────────────────────────────────────────┤
│  HARNESS DRIVE      Uniform interface to coding agents                 │  ← ADOPT: ACP (Zed) client
│                     (sessions, prompts, tool-calls, permissions)       │     + native CLI fallback
├──────────────────────────────────────────────────────────────────────┤
│  HARNESSES          Claude Code · Codex · OpenCode · Gemini CLI · …    │  ← ADOPT (swappable backends)
├──────────────────────────────────────────────────────────────────────┤
│  ISOLATION          git worktrees · containers · microVM sandboxes     │  ← ADOPT (worktree native; gVisor/Firecracker)
├──────────────────────────────────────────────────────────────────────┤
│  SHARED CONTEXT     MCP (tools) · AGENTS.md (instructions)             │  ← ADOPT / speak
└──────────────────────────────────────────────────────────────────────┘
   Cross-cutting: A2A for remote-agent delegation · OTel observability · safety/guardrails
```

## Build vs. adopt

| Layer | Stance | Why |
|---|---|---|
| **Harness drive** | **Adopt — be an ACP client** | ACP uniformly drives Claude Code/Codex/Gemini/OpenCode; Registry future-proofs. Native `-p`/`exec`/`run` as fallback. Don't hand-roll per-harness adapters. → [`concepts/protocols.md`](concepts/protocols.md) |
| **Harnesses** | **Adopt — swappable** | Treat each as a backend behind the ACP/adapter seam; multi-vendor = which harness a role uses. → [`harnesses.md`](harnesses.md) |
| **Isolation** | **Adopt** | Worktrees (native, default) for local; containers/microVM (gVisor/Firecracker) for unattended/untrusted. Orchestrator owns it — harness sandboxing is uneven. → [`concepts/safety-sandboxing.md`](concepts/safety-sandboxing.md) |
| **Shared context** | **Speak MCP + AGENTS.md** | MCP servers inject shared tools per session; AGENTS.md delivers project context cross-harness. |
| **Pipeline engine** | **Build (core)** | The whitespace: declarative, composable, typed pipeline over swappable harnesses. Likely on LangGraph as execution substrate (adopt-and-extend). |
| **Durability** | **Adopt when needed** | Temporal/Conductor-OSS for long-running runs; not day one. |
| **Observability/safety** | **Build thin + adopt** | OTel spans + cost budgets + guardrail hooks are first-class (where agents die in production). |

## The whitespace (validated by the survey)

Crowded: **"run N agents in parallel"** (Claude Squad ~7.6k★, Vibe Kanban ~26.6k★, Emdash ~4.6k★,
uzi). Sparse: **declarative pipelines** (MS Conductor — 2 harnesses, no typed I/O; Bernstein — 30+
harnesses but *fixed* pipeline). **Nobody** offers: declarative + composable + **typed inter-step
I/O** + **swappable multi-vendor harness backend** + cross-harness **task DAG** + first-class
**merge/observability**. That intersection is our product. → [`existing-orchestrators.md`](existing-orchestrators.md)

## How prior design decisions hold up (post-pivot)

- **Dev-facing, declarative-first YAML, explicit typed I/O + run context, composable steps, compile-to-LangGraph** — all still hold.
- **"Multi-vendor" reinterpreted:** the seam is the **harness** (via ACP), not an LLM gateway. A **Role** = "which harness + profile." Model selection lives inside each harness.
- **The headline leaf step is `agent`** (drive a harness via ACP) alongside `task` (plain LLM glue step), plus composites (`sequence`/`parallel`/`router`/`agentic`/`pipeline`).

## Config primitives the research demands (preview for design)
`isolation:` (worktree/container/sandbox) · task **DAG** (`depends_on` + `file_scope`) ·
`success_criteria:` (+`max_retries`) · `merge_strategy:` · `require_approval:` (HITL) ·
`strategy: best-of-n` · per-task **token budget + timeout** · OTel observability built in.

## Open question to resume in the design
Pure-harness orchestrator vs **hybrid** (harness `agent` steps + cheap `task` glue steps). Lean:
**hybrid** — a cheap LLM step for routing/triage/diff-summary between full harness runs, with a
pure-coding-agent pipeline as the subset. Everything else (ACP, isolation, DAG, merge, safety) is
now well-grounded.

Sources: see [`sources.md`](sources.md).
