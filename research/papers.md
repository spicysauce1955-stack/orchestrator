# Academic Papers & Benchmarks

*(Tavily research, 2026-06-02.)* Peer-reviewed / preprint work relevant to orchestrating coding
agents. Verify arXiv IDs before external citation (audited in [`source-index.md`](source-index.md)).

## Most relevant to coding-agent orchestration
- **AgenticFlict** (arXiv 2604.03551) — large study of **merge conflicts in agentic PRs** (N≈107k):
  overall **27.67%** conflict rate; per-agent (Codex 32%, Claude Code 27%, Cursor 20%, Copilot 15%).
  Direct evidence that **merge handling must be first-class**. https://arxiv.org/html/2604.03551v1
- **AdaptOrch: Task-Adaptive Orchestration** (arXiv 2602.16873) — dynamic topology selection
  (parallel/sequential/hierarchical/hybrid) from task dependency graphs; +12–23% over static. Cites
  Claude Code Agent Teams / OpenCode architectures. https://arxiv.org/html/2602.16873
- **Agent-as-a-Judge** (arXiv 2508.02994) — process-level evaluation: a judge agent replays the
  environment and evaluates the full trajectory, not just the final diff. Stronger than static
  LLM-as-judge for agentic/code tasks (which has weak correctness agreement). https://arxiv.org/html/2508.02994v1

## Orchestration architecture & multi-agent
- **The Orchestration of Multi-Agent Systems: Architectures, Protocols, Enterprise Adoption**
  (arXiv 2601.13671) — three-tier taxonomy (agent layer / control plane / communication); MCP + A2A.
  https://arxiv.org/html/2601.13671v1
- **Manager agent / dynamic task graph** (arXiv 2510.02557) — orchestrator-worker MAS with a
  runtime-built task DAG. https://arxiv.org/html/2510.02557v1

## On evaluation caveats (for our eval-loop design)
- LLM-as-judge for code has **weak correctness agreement** (Cohen's κ ~0.21; ~50% FP for GPT-4 on
  code) — use deterministic oracles (tests/CI) for correctness, LLM/agent judges for style/process.

## Reading order for our team
1. **AgenticFlict** — why `merge_strategy` and `file_scope` are first-class.
2. **AdaptOrch** — topology selection (informs `best-of-n` / DAG primitives).
3. **Agent-as-a-Judge** — how to evaluate agent outputs (the eval-loop step).
4. Orchestration survey — control-plane separation (planning/execution/state/quality).
