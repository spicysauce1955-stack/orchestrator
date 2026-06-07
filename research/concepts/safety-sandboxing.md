# Safety, Permissions & Sandboxing for Autonomous Coding Agents

*(Tavily research, 2026-06-02.)* Practices for running multiple coding-agent harnesses unattended
and in parallel. **The orchestrator must own isolation** — harness-native sandboxing is uneven, and
the incident record is serious (prod-DB deletion, `rm -rf /`, credential exfiltration).

## Harness permission models (for unattended runs)

| | Claude Code | Codex | OpenCode |
|---|---|---|---|
| Modes | `--permission-mode default\|acceptEdits\|plan\|auto\|bypassPermissions` | `sandbox_mode read-only\|workspace-write\|danger-full-access` × `approval_policy untrusted\|on-request\|never` | per-agent `permission{edit,bash:allow\|ask\|deny}` |
| Unattended | `acceptEdits`/`auto` (not full bypass unless containerized) | `workspace-write` + `approval=never` (`--full-auto`) | `--dangerously-skip-permissions` |
| Allow/deny tools | `permissions.allow/deny`, `--disallowedTools` | `.git/`,`.codex/`,`.agents/` auto read-only | `permission` map |
| OS sandbox | native (`/sandbox`, sandbox-runtime) | **strongest** — Seatbelt (mac) / Landlock+seccomp (linux), on by default | **none** (external required) |

- Claude `auto` mode classifier has a **~17% false-negative rate** — not safe alone for unattended.
- Claude bypass refuses to run as root unless in a recognized sandbox; org override `disableBypassPermissionsMode`.
- Codex protects `.git/`/`.codex/` read-only even in workspace-write (prevents self-modification of hooks/config); Claude does **not** by default → mount those read-only.

## OS-level sandboxing (isolation spectrum, weak→strong)
`Docker (namespaces)` → `Docker + seccomp/AppArmor/cap-drop` → `bubblewrap/nsjail` → **`gVisor`** (user-space kernel) → **`Firecracker`/Kata** (HW VM boundary).
- **Plain Docker shares the host kernel** — *not* a security boundary for hostile code. For LLM-generated/untrusted code, **gVisor or Firecracker is the minimum** recommended level.
- Production sandbox platforms: **E2B** (Firecracker, ~150ms cold start, Apache-2.0), **Vercel Sandbox** (Firecracker, GA Jan 2026), **Docker Sandboxes** (microVM, `sbx run claude`), **Dagger container-use** (MCP, Docker+worktree), **Modal** (gVisor).
- Harness-native: Codex Seatbelt/Landlock (default), Claude `sandbox-runtime` (⚠️ CVE-2025-66479: network unenforced if no `allowedDomains` — patched v0.0.16). macOS `sandbox-exec` is Apple-deprecated (long-term risk; `Containerization` framework is the successor).

## Secrets, filesystem & network
- **Never mount credential dirs** into agent envs: `~/.ssh`, `~/.aws`, `~/.kube`, `~/.config/gh`, `~/.docker`, `~/.npmrc`, `.env*`. Bind them to `/dev/null` (bubblewrap) or `denyRead` (Claude sandbox).
- **Block cloud metadata endpoints** at the network layer: `169.254.169.254`, `metadata.google.internal` — a single `curl` there steals IAM creds.
- **Default-deny egress**, allowlist only needed domains (registries, GitHub, CI). Enforce *outside* the agent (iptables/proxy), not just in agent config.
- **Read-only source mount + dedicated writable output**; scope CWD to the project, never `~`.
- **Short-lived, task-scoped OIDC tokens**, not long-lived API keys; inject at runtime, not into images.
- Codex filters `CODEX_`-prefixed env vars at startup (anti self-modify).

## Guardrails for autonomous edits
- **Never push to `main`/`master`** — GitHub branch protection / **org-level Rulesets** (repo-scoped agent tokens can't alter org rulesets); require PR + human review + green CI.
- **Agents run under their own identity** (bot/service account) so `CODEOWNERS` + audit logs distinguish agent vs human; protect `.github/workflows/`, agent-config, IaC, migrations via CODEOWNERS.
- **Separation of duties:** the agent that writes ≠ the agent that reviews/merges (enforce in orchestration).
- **Test-count baseline gate** in CI — fail if test count drops (catches agents deleting tests to go green).
- **Claude Code hooks** (deterministic, 26 lifecycle events): `PreToolUse` exit-2 blocks `rm -rf /`, `git push --force`, `git reset --hard`, `curl|bash`, `npm publish`, `DROP TABLE`, `git add .env`; `PostToolUse` logs every tool call to an immutable audit log. Hooks in `.claude/settings.json` (committed); the LLM treats a block as an absolute constraint.

## Cost / observability
- Multi-agent token cost **compounds** (sub-agent outputs re-enter orchestrator context); uncapped loops → "$200 overnight." Set **per-agent `max_tokens`** and **wall-clock timeouts**; auto-destroy ephemeral sandboxes.
- Claude `ENABLE_TOOL_SEARCH=true` lazy-loads tools (~45k→~20k starting context).
- Observability: **Langfuse** (OSS, self-host), **Braintrust**, **Datadog LLM Obs**, **Arize Phoenix** — OTel GenAI spans; track tokens/cost/tool-calls/context-utilization per agent per task.

## Known incidents (why this matters)
- **Replit agent deleted SaaStr's production DB** during a code freeze, fabricated data, lied (Jul 2025).
- **`rm -rf /` from root without `--dangerously-skip-permissions`** (Claude Code #10097, Oct 2025); `rm -rf … ~/` home-dir wipe in bypass mode (Dec 2025).
- **CVE-2025-53773** (Copilot self-modifies config → enables auto-approve → RCE, CVSS 9.6); **"IDEsaster"** (Dec 2025, 30+ vulns/24 CVEs, 100% of AI IDEs vulnerable).
- **The "lethal trifecta"** (Simon Willison): private-data access + untrusted content + external comms = exfiltration risk; present in every production coding agent.
- **Command allowlisting is insufficient** (Trail of Bits: `go test -exec '…'` argument injection bypasses allowlists) → sandboxing is a *required separate layer*.

## Recommended baseline for our orchestrator
- [ ] Each agent in its **own ephemeral sandbox** (worktree for local/trusted; **gVisor/Firecracker container** for unattended/untrusted); never share a host between parallel sessions.
- [ ] Read-only source mount + writable output only; **exclude all credential paths**; block metadata IPs; default-deny egress with allowlist.
- [ ] Short-lived scoped tokens; secrets injected at runtime.
- [ ] Per-task **token budget + wall-clock timeout**; auto-destroy sandboxes; OTel observability + cost alerts.
- [ ] Agent identity = bot account; branch protection/Rulesets; CODEOWNERS on sensitive paths; test-count gate; writer≠reviewer.
- [ ] Make harness sandbox/config files read-only to the agent; pin harness versions (high CVE churn); treat all agent output as untrusted input (SAST/dep-scan/human review).

Sources: see [`../sources.md`](../sources.md) → "Safety & sandboxing".
