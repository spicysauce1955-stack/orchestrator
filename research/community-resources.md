# Community Resources — Coding-Agent Orchestration

*(Tavily research, 2026-06-02.)* Living resources to monitor; these move faster than any static doc.

## Awesome-lists & curated catalogs
- **andyrewlee/awesome-agent-orchestrators** — tools for orchestrating AI *coding* agents (parallel runners, swarms, autonomous loops). https://github.com/andyrewlee/awesome-agent-orchestrators
- **Addy Osmani — "code agent orchestra"** — tiered taxonomy (subagents vs Agent Teams vs orchestrators), names emerging tools. https://addyosmani.com/blog/code-agent-orchestra

## Standards / protocol hubs
- **Agent Client Protocol (ACP)** — spec, RFDs, registry. https://agentclientprotocol.com · https://github.com/agentclientprotocol/agent-client-protocol
- **ACP Registry** (Zed) — agents register once, appear in every ACP client. https://zed.dev/blog/acp-registry
- **AGENTS.md** — cross-harness instruction file. https://agents.md
- **MCP** / **A2A** — https://modelcontextprotocol.io · https://github.com/a2aproject/A2A

## Key OSS repos to watch (closest prior art)
- Microsoft Conductor (declarative YAML) — https://github.com/microsoft/conductor
- Bernstein (deterministic pipeline + test gate, 30+ harnesses) — https://github.com/sipyourdrink-ltd/bernstein
- Composio Agent Orchestrator (event-driven supervisor) — https://github.com/ComposioHQ/agent-orchestrator
- Vibe Kanban (board dispatch, 10+ agents) — https://github.com/BloopAI/vibe-kanban
- Claude Squad (parallel TUI) — https://github.com/smtg-ai/claude-squad
- container-use (Dagger isolation substrate) — https://github.com/dagger/container-use

## Harness docs (primary)
- Claude Code — https://code.claude.com/docs · Codex — https://developers.openai.com/codex · OpenCode — https://opencode.ai/docs

## Engineering blogs / analysts seen this pass
- Augment Code guides (worktrees, supervisor-vs-swarm, pre-merge verification) — augmentcode.com/guides
- Dagger blog (container-use) · Docker blog (Docker Sandboxes) · GitHub blog (reviewing agent PRs)
- Simon Willison (the "lethal trifecta"; sandbox commentary) · Peter J. Thomson (semantic rebase)

## Forums
- **Hacker News** — protocol/safety sentiment bellwether (anti-MCP threads; agent incident discussions).
- **r/ClaudeCode**, **r/LangChain** — practitioner cost/observability audits, framework comparisons.

> Tip: when refreshing, start from awesome-agent-orchestrators + the ACP registry, then verify
> specifics against each project's repo/release notes.
