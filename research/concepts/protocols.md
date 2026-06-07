# Protocols for Driving & Coordinating Coding Agents

*(Tavily research, 2026-06-02.)* Which standards an orchestrator should speak to drive coding-agent
harnesses uniformly. **Headline recommendation: build the orchestrator as an ACP (Zed's Agent
Client Protocol) client** for harness-driving, use **MCP** for shared tools, **AGENTS.md** for
context, and **A2A** only for remote-agent delegation.

> ⚠️ **Two different "ACP"s.** **Zed's Agent Client Protocol** (editor↔agent, *active*, what we
> want) vs **IBM's Agent Communication Protocol** (agent↔agent, **deprecated** — merged into A2A
> Aug 2025). In this library, "ACP" = Zed's Agent Client Protocol.

```
   ACP   = orchestrator ↔ coding-agent harness   (drive: sessions, prompts, tool calls, permissions)
   MCP   = agent ↔ tools/data                    (shared capabilities)
   A2A   = orchestrator ↔ remote autonomous agent (cross-org task delegation)
 AGENTS.md = static project context for any agent (Markdown, no wire protocol)
```

## ACP — Agent Client Protocol (Zed) ⭐ primary

- **What:** JSON-RPC 2.0 protocol that decouples editors/clients from coding agents — "LSP for AI
  agents." Lifecycle: `initialize` (capability negotiation) → `session/new` (working dir + **MCP
  servers** to bootstrap) → `session/load` (resume) → `session/set_mode` (plan vs build) →
  prompt turn → `session/update` stream (message/thought chunks, **tool calls** with
  `pending→in_progress→completed/failed`, plan steps) → `session/request_permission`
  (`allow_once|allow_always|reject_once|reject_always`) → `session/cancel`. Optional capability-gated
  `fs/*` (mediated file I/O) and `terminal/*` (create/output/wait/kill).
- **Transport:** stdio (stable — client spawns agent as subprocess, newline-delimited JSON-RPC).
  Streamable HTTP / WebSocket for remote agents are **draft** (roadmap).
- **Governance:** Zed Industries (Aug 2025) + Google (Gemini CLI co-launch) + JetBrains (Oct 2025).
  Apache-2.0; SDKs in Rust (official), Kotlin/Java/Python/TS. **ACP Registry** launched Jan 28 2026.
- **Adopters — agents:** Gemini CLI (native `--acp`), **Claude Code** (via `claude-agent-acp`),
  **Codex** (via `codex-acp`), **OpenCode** (native `opencode acp`), Copilot CLI, Cursor, Kimi CLI,
  Qwen Code, OpenHands, Pi… **Clients:** Zed (reference), JetBrains, Neovim, Emacs, VS Code (ext),
  Toad (18+ agents).
- **Fit:** purpose-built for exactly our problem. The **orchestrator becomes the ACP client**: one
  protocol drives every major harness, with standardized session lifecycle, streaming tool-call
  visibility, permission mediation, terminal output, and MCP bootstrapping. Registry = new agents
  become driveable with no code change. Precedents: the ACP Rust SDK's "Conductor"/patchwork-rs
  orchestrator-over-ACP patterns.
- **Limitation/risk:** remote transport still draft → cloud-hosted agents need local stdio spawning
  for now. Adapter coverage/maturity varies per harness (verify Claude/Codex adapters per release).

## MCP — Model Context Protocol (shared tools)
- JSON-RPC client-server for tools/resources/prompts; **~97M downloads**, LF/AAIF governance (donated
  Dec 2025), universally supported by every major coding agent. 2025-11-25 spec adds async tasks,
  OAuth 2.1, elicitation, server-side loops. ~2,000 registry servers.
- **Role here:** *shared tool layer, not the driving layer.* Run MCP servers (repo index, CI, test
  runners, shared memory, observability sinks); inject into every agent via ACP `session/new`'s
  `mcpServers`. Complementary to ACP (MCP = what the agent can call; ACP = how we drive it).
- ⚠️ Security: tool-poisoning succeeds ~84% with auto-approval; sandbox MCP tool execution.

## A2A — Agent2Agent (remote delegation)
- HTTP + SSE + JSON-RPC; **Agent Cards** (capability manifests at well-known URLs); task lifecycle;
  OAuth/OIDC. Google (Apr 2025) → Linux Foundation (Jun 2025); **IBM's ACP merged into A2A** (Aug
  2025); 150+ orgs by Apr 2026.
- **Role here:** only if delegating to **remote, independently-hosted** agents (cloud Codex, a
  Devin-type service). *Not* for driving local CLI harnesses — A2A assumes pre-deployed HTTP services
  with Agent Cards and doesn't model interactive permission/tool-call streams. ACP > A2A for harness-driving.

## AGENTS.md (static context)
- Plain-Markdown project instructions (build/test commands, conventions, constraints); "closest file
  wins" in monorepos. OpenAI-pioneered (mid-2025) → AAIF/LF (Dec 2025). Read by **20+ agents** (Codex,
  Claude Code [CLAUDE.md primary], Gemini CLI, Copilot, Cursor, Windsurf, Devin, Aider, Zed, OpenCode…).
- **Role here:** cheapest cross-agent context delivery — orchestrator writes/injects an AGENTS.md into
  each session's working dir; works regardless of driving protocol.

## Harness-native SDKs (fallback only)
- **Claude Agent SDK** (Py/TS, full runtime, JSONL sessions) — deep Claude control, vendor-locked.
- **Codex SDK** (TS app-server; Python over JSON-RPC) — Codex-only; Responses API since Feb 2026.
- **OpenCode** — `opencode serve` REST/OpenAPI + `@opencode-ai/sdk`; or native ACP.
- Use these for capabilities ACP doesn't yet expose; not as the uniform layer.

## Recommendation for our orchestrator
1. **Be an ACP client** — the single highest-leverage decision; uniform driving across all harnesses.
2. **Run MCP servers** for shared tools; inject via ACP `session/new`.
3. **Write AGENTS.md** per run for static context.
4. **A2A** only for remote-agent delegation tiers.
5. **Native SDKs/headless CLI** as per-harness fallbacks (see [`../harnesses.md`](../harnesses.md)).
- **Avoid:** building around IBM ACP (dead), or making any single vendor SDK the primary interface.

Sources: see [`../sources.md`](../sources.md) → "Protocols".
