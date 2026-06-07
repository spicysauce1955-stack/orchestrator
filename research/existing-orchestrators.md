# Prior Art — Coding-Agent Orchestrators

*(Tavily research, 2026-06-02.)* Survey of tools that orchestrate/parallelize/coordinate multiple
AI coding agents, to map prior art and find our differentiation. **Headline: the field is crowded
with "run N agents in parallel" tools, but the "declarative, composable pipeline over multi-vendor
harnesses with typed I/O" space is open.** That whitespace is our concept.

> Verification note: "TeamHero" and a product literally named "Async" could **not** be verified
> (no repo/site/credible source) — dropped. "Gastown"/"Antigravity" mentioned by a credible blog
> but no public repo found. Star counts approximate, early June 2026.

## By orchestration style

### Declarative / pipeline engines (closest to us)
- **Microsoft Conductor** (MIT, ~300★) — YAML multi-agent workflows; deterministic routing (zero tokens), parallel blocks, `for_each`, conditionals, HITL gates, web dashboard. **But:** only GitHub Copilot SDK + Anthropic SDK; thin schema; no typed inter-step I/O; no harness-plugin abstraction. *Closest existing tool.* `github.com/microsoft/conductor`
- **Bernstein** (Apache-2.0, ~178★) — Goal→Planner→Task Graph→parallel agents→**Janitor** (test gate)→merge; deterministic Python scheduler; HMAC-chained audit log; **30+ harnesses** (Claude Code, Codex, Gemini, Amp, Aider, OpenCode…); git worktrees. **But:** pipeline is *fixed*, not user-composable; no typed step I/O. *Most architecturally rigorous OSS.*
- **Antfarm** (Ryan Carson, MIT) — YAML workflows (Planner→Implementer→Verifier→Tester→Reviewer), SQLite+cron+git, stateless "Ralph Loop" sessions. **But:** OpenClaw-only, not multi-harness.
- **Conductor OSS** (Netflix→Orkes, Apache-2.0, ~15k★) — durable, versioned JSON/YAML workflow engine, replayable, battle-tested. **But:** general-purpose, not coding-agent/worktree-aware. Prior art for "declarative pipeline at scale," not for harnesses.

### Supervisor / agent-as-orchestrator
- **Composio Agent Orchestrator** (MIT) — the orchestrator is itself an AI agent: decomposes features, spawns agents (Claude Code/Codex/Aider/OpenCode), event-driven reactions (CI fail→inject→fix→push), PR-comment routing, escalation. Most sophisticated coordination logic in OSS. Worktrees+tmux/Docker. *Imperative rules, not a composable DAG.*
- **ccswarm** (MIT, Rust, ~139★) — role-based swarm (frontend/backend/devops/QA), channel-based coordination, worktrees. Claude Code primary.
- **Claw Orchestrator** (MIT) — wrap Claude Code/Codex/Gemini/Cursor/OpenCode as persistent sessions; "council" + Planner/Coder/Reviewer; web UI.
- **Claude Code Agent Teams** (Anthropic, first-party, experimental `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) — lead + teammates, shared task list, direct peer messaging. Claude-only.

### Parallel runners / session managers (HITL) — the crowded middle
- **Vibe Kanban** (Apache-2.0, Rust, ~26.6k★) — kanban board → agent workspaces (worktrees); 10+ agents; experimental MCP "orchestrator agent." Highest stars; community-maintained after BloopAI sunset.
- **Claude Squad** (AGPL-3.0, ~7.6k★) — TUI managing many sessions (Claude Code/Codex/Aider/Gemini/OpenCode/Amp), each in a worktree+tmux. Pure HITL, no coordination.
- **Emdash** (Apache-2.0, YC W26, ~4.6k★) — Electron "ADE"; **~22 agents** (broadest harness support); worktrees + per-task `$EMDASH_PORT`; issue intake (Linear/Jira/GitHub/Asana). HITL only.
- **uzi** (MIT, ~579★) — fan-out same prompt to N agents (`--agents=claude:3,codex:2`), worktrees+tmux, `uzi checkpoint` to rebase a winner. "Spray and pray," no pipeline.
- **Conductor (Melty Labs)** (closed, free) — macOS app, Claude Code+Codex in worktrees, diff-first review. (≠ Microsoft Conductor.)
- **dmux** (MIT), **Parallel Code** (MIT, ~673★), **Crystal→Nimbalyst** (Stravu), **worktrunk** (~5k★) — worktree-based parallel desktop/TUI runners.

### Container-isolated substrates (not orchestrators)
- **container-use** (Dagger, Apache-2.0, ~3.6k★) — MCP server giving each agent a **Docker container + worktree**; merge with `container-use merge`. Isolation layer others can build on. "Two forms of isolation in one system."
- **Sculptor (Imbue)** (OSS) — desktop app, each workspace in a Docker container, "Pairing Mode" syncs to local IDE; Claude Code + Codex.

### Cloud / async & IDE-native
- **Terragon** (commercial SaaS) — cloud Claude Code in parallel, cross-device, auto-PR. Claude-only.
- **VS Code Multi-Agent** (1.109, Feb 2026) — Claude + Codex + Copilot in one "Agent Sessions" view (local/worktree/cloud).
- **Sortie / Lalph** — issue-tracker-ticket → autonomous agent session → PR.

## Comparison (representative)

| Tool | Style | Harnesses | Isolation | Pipeline/DAG | License | ★ |
|---|---|---|---|---|---|---|
| MS Conductor | Declarative YAML | Copilot, Claude | session | parallel+cond | MIT | ~300 |
| Bernstein | Fixed pipeline + gate | 30+ | worktrees | fixed | Apache-2.0 | ~178 |
| Composio AO | Supervisor agent | Claude/Codex/Aider/OpenCode | worktrees+tmux/Docker | event rules | MIT | — |
| Vibe Kanban | Kanban dispatch | 10+ | worktrees | lanes | Apache-2.0 | ~26.6k |
| Claude Squad | Parallel TUI | 6 | worktrees+tmux | none | AGPL-3.0 | ~7.6k |
| Emdash | Parallel desktop | ~22 | worktrees+ports | none | Apache-2.0 | ~4.6k |
| uzi | Fan-out CLI | any CLI | worktrees | none | MIT | ~579 |
| container-use | Isolation substrate | any MCP | Docker+worktree | none | Apache-2.0 | ~3.6k |

## Gaps / whitespace (our differentiation)

The survey is consistent: **no tool combines all of these**, and each is a candidate differentiator.

1. **Declarative, composable pipeline over multi-vendor harnesses.** MS Conductor (2 harnesses, no typed I/O) and Bernstein (fixed pipeline) are closest; neither lets users compose reusable, typed steps over a *swappable* harness backend.
2. **Harness-agnostic abstraction.** Tools enumerate harnesses with bespoke integrations (Emdash's 22 via install scripts); none expose a clean **harness adapter interface** a new agent can implement. → **ACP is the standard that solves this** ([`concepts/protocols.md`](concepts/protocols.md)); building the engine as an ACP client is the leverage point.
3. **Composable steps vs. "run N in parallel."** Almost everything is (a) same prompt → N agents or (b) N independent tasks. Few model a **dependency DAG with typed outputs flowing between steps**.
4. **Pipeline observability/auditability.** Only Bernstein has a production-grade audit log; most are tmux-scrollback. No distributed tracing / typed per-step artifacts / replay.
5. **Cross-harness task dependency graph** ("Makefile for coding agents") — user-declared, plan-time-validated, topologically executed across arbitrary harnesses.
6. **Container isolation + composable pipeline + multi-harness in one tool** — container-use and Sculptor isolate but aren't pipeline engines; the combination doesn't exist.

**Closest-to-us ranking:** MS Conductor > Bernstein > Antfarm > Composio AO. Everything else is a parallel runner.

> **Not surveyed here:** **Claude-Flow "Hive Mind"** (ruvnet) — a queen-led emergent *swarm*
> orchestrator (Claude-only) — gets a full head-to-head in [`competitors.md`](competitors.md), as
> does **activeloopai/hivemind** (a complementary cross-agent memory layer, not an orchestrator).

Sources: see [`sources.md`](sources.md) → "Existing orchestrators".
