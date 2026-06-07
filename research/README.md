# Research & Reference Library

Landscape research for **orchestrator** — a developer-facing, declarative orchestrator that
coordinates **coding-agent harnesses** (Claude Code, OpenAI Codex, OpenCode) as composable
pipeline steps. The orchestrated *unit* is a full coding agent, not a raw LLM model.

> Snapshot date: **2026-06-02**. Sources gathered via the **Tavily MCP** through parallel research
> agents, then quality-audited. Re-verify versions/"current" claims before relying on them; vendor
> benchmarks and star counts are flagged. See [`source-index.md`](source-index.md).

> **Scope note:** This library was re-scoped on 2026-06-02 from a general LLM-vendor-orchestration
> survey to **coding-agent-harness orchestration**. Out-of-scope docs (LLM gateways, RAG/knowledge
> base, low-code builders, general agent frameworks) were removed.

## How this is organized

| File | What's in it |
|------|--------------|
| [`landscape.md`](landscape.md) | Big-picture map + build-vs-adopt stance + the whitespace we target |
| [`harnesses.md`](harnesses.md) | **How to invoke** Claude Code / Codex / OpenCode headlessly (CLI flags, JSON, sessions, SDKs) |
| [`existing-orchestrators.md`](existing-orchestrators.md) | **Prior-art survey** of coding-agent orchestrators + gaps/whitespace |
| [`competitors.md`](competitors.md) | **Head-to-head deep-dives** vs. named competitors (activeloopai/hivemind, Claude-Flow Hive Mind) |
| [`concepts/protocols.md`](concepts/protocols.md) | **ACP** (drive agents) + MCP + A2A + AGENTS.md — the interop stack |
| [`concepts/orchestration-patterns.md`](concepts/orchestration-patterns.md) | Worktrees, containers, best-of-N, conflict-merge, supervisor, eval loops, HITL, observability |
| [`concepts/safety-sandboxing.md`](concepts/safety-sandboxing.md) | Permission models, sandboxing, secrets, guardrails, incidents, baseline checklist |
| [`community-resources.md`](community-resources.md) | Awesome-lists, key repos, blogs to monitor |
| [`papers.md`](papers.md) | Academic surveys & benchmarks (orchestration, conflicts, agent-as-judge) |
| [`sources.md`](sources.md) | Master link list, grouped by topic |
| [`source-index.md`](source-index.md) | Quality audit — reachability + credibility tiers |

## The one-paragraph takeaway

There are two decisive findings. **(1) Don't build a bespoke harness adapter — speak ACP.** Zed's
**Agent Client Protocol** is purpose-built to drive coding agents uniformly (sessions, streaming
tool-calls, permission mediation, terminal, MCP bootstrap); Claude Code, Codex, Gemini CLI, and
OpenCode are all reachable through it (native or adapter), and the ACP Registry means new agents
become driveable for free. Build the orchestrator as an **ACP client**, with native headless CLIs
(`claude -p`, `codex exec`, `opencode run`) as fallback. **(2) Our concept is genuine whitespace.**
The survey found a crowded field of "run N agents in parallel" tools (Claude Squad, Vibe Kanban,
Emdash, uzi) and a couple of declarative engines (MS Conductor, Bernstein), but **none** combine a
*declarative, composable, typed pipeline* with a *swappable multi-vendor harness backend*. Plus:
isolation (worktrees/containers), a task DAG (`depends_on`+`file_scope`), `success_criteria`,
`merge_strategy`, and HITL gates are all proven patterns that map directly to config primitives —
and safety (sandboxing, the ~27% merge-conflict rate, real incidents) must be first-class.

## Next step

Resume the **design brainstorm** (paused at: pure-harness vs hybrid scope) — now grounded in: speak
**ACP**, own **isolation**, model the pipeline as a **typed task DAG over swappable harnesses**, and
treat **merge + safety + observability** as first-class. See [`landscape.md`](landscape.md).
