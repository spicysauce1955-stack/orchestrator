# Source Index & Quality Audit

*(Re-audited 2026-06-02 after the coding-agent re-scope.)* All URLs machine-checked for
reachability; all cited arXiv papers authenticated against arXiv (API + HTML).

## Verification method
1. Extracted all unique URLs from `research/`.
2. `curl` each (follow redirects, browser UA, 18s timeout) → HTTP status.
3. Authenticated every cited arXiv ID by comparing the arXiv-returned title to our citation.

## Results

| Check | Result |
|-------|--------|
| Unique URLs | 89 |
| Resolve `200 OK` | 84 |
| Real but bot-blocked / timeout (`000`/`403`) | 3 (VS Code blog, MS opensource blog, openai.com) |
| Fixed | 1 — truncated LF A2A press URL (was 404) → full URL (now 200) |
| Dead / fabricated | **0** |
| **arXiv papers authenticated (title matched)** | **5 / 5 ✅** |

**arXiv authenticity:**
- `2604.03551` ✅ *AgenticFlict: A Large-Scale Dataset of Merge Conflicts in AI Coding Agent PRs*
- `2602.16873` ✅ *AdaptOrch: Task-Adaptive Multi-Agent Orchestration…*
- `2508.02994` ✅ *When AIs Judge AIs: …Agent-as-a-Judge…*
- `2601.13671` ✅ *The Orchestration of Multi-Agent Systems…* (also verified prior session)
- `2510.02557` ✅ *Orchestrating Human-AI Teams: The Manager Agent…*

**Bot-blocked but real** (exist in a browser, block `curl`): `code.visualstudio.com`,
`opensource.microsoft.com`, `openai.com`. Treat as Tier A primary (official) despite the block.

## Credibility tiers

### Tier A — Primary / authoritative (load-bearing safe)
- **Harness docs:** `code.claude.com/docs`, `developers.openai.com/codex`, `opencode.ai/docs`,
  Anthropic/OpenAI engineering blogs, Claude Agent SDK repo.
- **Protocol specs/repos:** `agentclientprotocol.com` + repo, `zed.dev`, `modelcontextprotocol.io`,
  `github.com/a2aproject/A2A`, `agents.md`, Linux Foundation / LF AI&Data press, JetBrains blog.
- **Project repos (verified):** microsoft/conductor, sipyourdrink-ltd/bernstein, smtg-ai/claude-squad,
  BloopAI/vibe-kanban, devflowinc/uzi, generalaction/emdash, dagger/container-use, imbue-ai/sculptor,
  ComposioHQ/agent-orchestrator, nwiizo/ccswarm, conductor-oss/conductor, andyrewlee/awesome-agent-orchestrators.
- **arXiv (all 5 authenticated).** Official vendor blogs: Docker, Dagger, GitHub, VS Code.

### Tier B — Reputable secondary (corroborate)
Augment Code guides, WorkOS, Braintrust, Langfuse, Addy Osmani, Peter J. Thomson, Simon Willison
commentary, CircleCI blog, `digitalapplied.com`, `shanedeconinck.be`, security roundups (`sysid.github.io`).

### Tier C — Marketing / vendor-stake (features only, not verdicts)
`nimbalyst.com`, `morphllm.com`, `mintmcp.com`, `bunnyshell.com`, `northflank.com`, `truefoundry.com`,
`getmaxim`/`braintrust` comparison framing, and "best-X" listicles. ⚠️ several rank their own product #1.

## Audit guidance
- **Standards/harness mechanics, ACP/MCP/A2A facts, patterns** → cite Tier A (mostly already).
- **Stars / "current version" / adoption numbers** → re-verify against each repo's releases.
- **Vendor benchmarks & incident roundups** → directional; flagged inline in the docs.
- **Unverified products** dropped during research: "TeamHero", "Async" (no repo/site found);
  "Gastown"/"Antigravity" mentioned but no public repo.

## Reproduce
```bash
grep -rhoE 'https?://[^ )<>]+' research/ | sed -E 's/[.,)]+$//' | sort -u > /tmp/urls.txt
while read u; do printf '%s %s\n' "$(curl -sIL -o /dev/null -w '%{http_code}' --max-time 18 -A 'Mozilla/5.0' "$u")" "$u"; done < /tmp/urls.txt
curl -s "https://arxiv.org/abs/<ID>" | grep -oiP '(?<=<title>).*?(?=</title>)'   # arXiv title check
```
