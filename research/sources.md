# Master Source List (Tavily research, 2026-06-02)

Gathered via the Tavily MCP through parallel research agents, grouped by topic. Primary sources
(official docs, repos, specs, press) preferred; comparison blogs and vendor benchmarks are
directional. See [`source-index.md`](source-index.md) for the reachability/credibility audit.

## Harness invocation (Claude Code / Codex / OpenCode)
- Claude Code headless — https://code.claude.com/docs/en/headless
- Claude Agent SDK — https://code.claude.com/docs/en/agent-sdk/overview · sessions: https://code.claude.com/docs/en/agent-sdk/sessions · TS: https://code.claude.com/docs/en/agent-sdk/typescript
- Claude Code settings/permissions — https://code.claude.com/docs/en/settings · https://code.claude.com/docs/en/permission-modes
- Claude Code auto mode — https://www.anthropic.com/engineering/claude-code-auto-mode
- Codex non-interactive — https://developers.openai.com/codex/noninteractive · CLI ref: https://developers.openai.com/codex/cli/reference · SDK: https://developers.openai.com/codex/sdk
- Codex sandboxing/approvals — https://developers.openai.com/codex/concepts/sandboxing · https://developers.openai.com/codex/agent-approvals-security
- OpenCode — CLI: https://opencode.ai/docs/cli · server: https://opencode.ai/docs/server · sdk: https://opencode.ai/docs/sdk · config: https://opencode.ai/docs/config · agents: https://opencode.ai/docs/agents
- Claude Agent SDK TS changelog — https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md

## Existing orchestrators
- MS Conductor — https://github.com/microsoft/conductor · https://opensource.microsoft.com/blog/2026/05/14/conductor-deterministic-orchestration-for-multi-agent-ai-workflows
- Bernstein — https://github.com/sipyourdrink-ltd/bernstein
- Claude Squad — https://github.com/smtg-ai/claude-squad
- Vibe Kanban — https://github.com/BloopAI/vibe-kanban · https://vibekanban.com
- uzi — https://github.com/devflowinc/uzi
- Emdash — https://github.com/generalaction/emdash · https://emdash.sh
- Parallel Code — https://github.com/johannesjo/parallel-code
- dmux — https://github.com/standardagents/dmux
- container-use (Dagger) — https://github.com/dagger/container-use · https://dagger.io/blog/agent-container-use
- Sculptor (Imbue) — https://github.com/imbue-ai/sculptor
- Composio Agent Orchestrator — https://github.com/ComposioHQ/agent-orchestrator
- ccswarm — https://github.com/nwiizo/ccswarm
- Antfarm — https://github.com/snarktank/antfarm
- Claw Orchestrator — https://github.com/Enderfga/claw-orchestrator
- Crystal (archived) — https://github.com/stravu/crystal · Nimbalyst — https://nimbalyst.com
- Conductor OSS (Netflix/Orkes) — https://github.com/conductor-oss/conductor
- Claude Code Agent Teams — https://code.claude.com/docs/en/agent-teams
- VS Code multi-agent — https://code.visualstudio.com/blogs/2026/02/05/multi-agent-development
- awesome-agent-orchestrators — https://github.com/andyrewlee/awesome-agent-orchestrators
- Addy Osmani, code agent orchestra — https://addyosmani.com/blog/code-agent-orchestra

## Protocols (ACP / MCP / A2A / AGENTS.md)
- ACP (Zed Agent Client Protocol) — https://agentclientprotocol.com · https://github.com/agentclientprotocol/agent-client-protocol
- ACP registry — https://zed.dev/blog/acp-registry · https://zed.dev/acp
- JetBrains + Zed ACP — https://blog.jetbrains.com/ai/2025/10/jetbrains-zed-open-interoperability-for-ai-coding-agents-in-your-ide
- ACP intro — https://blog.marcnuri.com/agent-client-protocol-acp-introduction
- MCP 2026 — https://workos.com/blog/everything-your-team-needs-to-know-about-mcp-in-2026 · https://www.anthropic.com/engineering/code-execution-with-mcp
- A2A — https://github.com/a2aproject/A2A · https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability · https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year
- IBM ACP → A2A merge — https://lfaidata.foundation/communityblog/2025/08/29/acp-joins-forces-with-a2a-under-the-linux-foundations-lf-ai-data
- AGENTS.md — https://agents.md · https://www.morphllm.com/agents-md-guide

## Patterns (isolation, best-of-N, conflicts, supervisor, eval, HITL, observability)
- Git worktrees for agents — https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution · https://nx.dev/blog/git-worktrees-ai-agents · https://addyosmani.com/blog/code-agent-orchestra
- Docker/sandbox isolation — https://www.docker.com/blog/docker-sandboxes-run-claude-code-and-other-coding-agents-unsupervised-but-safely · https://dagger.io/blog/agent-container-use · https://shanedeconinck.be/posts/docker-sandbox-coding-agents
- Best-of-N / fan-out — https://www.digitalapplied.com/blog/multi-agent-coding-parallel-development
- Merge conflicts (AgenticFlict) — https://arxiv.org/html/2604.03551v1 · semantic rebase: https://www.peterjthomson.com/2026/01/semantic-rebase · https://www.augmentcode.com/guides/how-to-run-a-multi-agent-coding-workspace
- Supervisor / task graph — https://www.augmentcode.com/guides/swarm-vs-supervisor · https://www.mindstudio.ai/blog/claude-code-agent-teams-shared-task-list
- Eval/review loops — https://circleci.com/blog/test-hooks-ai-development · agent-as-judge: https://arxiv.org/html/2508.02994v1
- HITL — https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them · https://towardsdatascience.com/building-human-in-the-loop-agentic-workflows
- Observability — https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse · https://www.braintrust.dev/articles/agent-observability-complete-guide-2026

## Safety & sandboxing
- Claude permission modes — https://code.claude.com/docs/en/permission-modes · auto mode: https://www.anthropic.com/engineering/claude-code-auto-mode
- Codex sandbox — https://developers.openai.com/codex/concepts/sandboxing · https://openai.com/index/building-codex-windows-sandbox
- OS sandbox patterns — https://www.digitalapplied.com/blog/ai-agent-sandboxing-isolation-patterns-2026 · https://dev.to/uenyioha/os-level-sandboxing-kernel-isolation-for-ai-agents-3fdg
- Sandbox bypass CVE — https://www.penligent.ai/hackinglabs/claude-code-sandbox-bypass
- Secrets — https://patrickmccanna.net/a-better-way-to-limit-claude-code-and-other-coding-agents-access-to-secrets · https://github.com/anthropics/claude-code/issues/2142
- Hooks guardrails — https://github.com/yurukusa/claude-code-hooks
- Incident roundups — https://sysid.github.io/your-agent-has-root

## Papers
- AgenticFlict (merge conflicts) — https://arxiv.org/html/2604.03551v1
- AdaptOrch (task-adaptive orchestration) — https://arxiv.org/html/2602.16873
- Agent-as-a-Judge — https://arxiv.org/html/2508.02994v1
- Orchestration architectures survey — https://arxiv.org/html/2601.13671v1
- Manager agent / dynamic task graph — https://arxiv.org/html/2510.02557v1
