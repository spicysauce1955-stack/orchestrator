# Harness Invocation Reference — Claude Code, Codex, OpenCode

*(Tavily research, 2026-06-02.)* Implementation-oriented reference for driving each coding-agent
harness **non-interactively**, so we can build a uniform adapter. **Key cross-cutting finding:**
all three can also be driven through **Zed's Agent Client Protocol (ACP)** — see
[`concepts/protocols.md`](concepts/protocols.md) — which is likely a better adapter than bespoke
subprocess wrappers. This doc covers the *native* CLI/SDK surface each exposes.

## At a glance

| Capability | Claude Code | Codex CLI | OpenCode |
|---|---|---|---|
| Headless invoke | `claude -p "…"` | `codex exec "…"` | `opencode run "…"` |
| JSON output | `--output-format json` / `stream-json` (+`--json-schema`) | `--json` (NDJSON) (+`--output-schema`) | `--format json` (NDJSON); SDK schema |
| Resume | `--continue`, `--resume <id>` | `codex exec resume --last`/`<id>` | `--continue`, `--session <id>` |
| MCP | `--mcp-config`, `.mcp.json` | `codex mcp add`, config.toml | `opencode mcp add`, config |
| Sandbox / auto-approve | `--dangerously-skip-permissions`, `--permission-mode auto`, `--allowedTools` | `--full-auto`, `--sandbox <lvl>` (read-only default; OS-level) | `--dangerously-skip-permissions` (policy only, no OS sandbox) |
| Official SDK | **Claude Agent SDK** (Py + TS, full runtime) | Codex SDK (TS app-server; Py JSON-RPC) | `@opencode-ai/sdk` (TS, HTTP client) + `opencode serve` REST |
| HTTP server | No (SDK only) | No | **Yes** — `opencode serve` (OpenAPI) |
| Models | Anthropic only | OpenAI + Azure + Bedrock + OSS | 75+ providers (`provider/model`) |
| ACP support | via `claude-agent-acp` adapter | via `codex-acp` adapter | native (`opencode acp`) |
| Auth (CI) | `ANTHROPIC_API_KEY` | `CODEX_API_KEY`/`OPENAI_API_KEY` | provider env vars / `auth.json` |

## Claude Code

- **Headless:** `claude -p "task"` (alias `--print`); reads stdin (`cat x | claude -p`); `--add-dir <path>` for working dirs; `--bare` skips user config/MCP for clean runs.
- **Structured output:** `--output-format json` returns one object: `{result, session_id, total_cost_usd, duration_ms, num_turns, is_error}`. `stream-json` emits NDJSON events (`system/init` carries `session_id`). `--json-schema <str>` coerces the result to a schema. Exit 0/1 + `is_error`.
- **Diffs/changed files** are NOT in the JSON result — capture via `Bash(git diff)` in `--allowedTools`.
- **Resume:** `--continue` (most recent in CWD), `--resume <id>`; SDK `resume=`, `continue_conversation=`, `fork=`. Sessions at `~/.claude/projects/<path>/*.jsonl`.
- **Models:** `--model sonnet|opus|haiku` or full IDs; `ANTHROPIC_MODEL` env.
- **MCP:** `--mcp-config <file|json>`, project `.mcp.json`, or `mcpServers` in settings. Tools appear as `mcp__<server>__<tool>`. `strictMcpConfig` to fail on broken servers.
- **Permissions:** `--allowedTools "Read,Edit,Bash(git )"` / `--disallowedTools`; `--permission-mode` ∈ `default|acceptEdits|plan|auto|bypassPermissions`. `--dangerously-skip-permissions` = full bypass (Anthropic: run only in container/VM/CI). `auto` mode (Mar 2026) uses a classifier (⚠️ 17% false-negative rate — not safe alone for unattended). Refuses to bypass as root unless in a recognized sandbox. Org override: `permissions.disableBypassPermissionsMode`.
- **SDK (Claude Agent SDK** — renamed from "Claude Code SDK", Sept 2025): `pip install claude-agent-sdk` / `npm i @anthropic-ai/claude-agent-sdk`. Async generator `query(prompt, options)`; `ClaudeAgentOptions(allowed_tools, cwd, model, mcp_servers, permission_mode, max_turns, max_budget_usd, resume, output_format)`. Also a **Managed Agents** REST API (Anthropic-hosted). Vendor-locked to Claude.
- **Auth:** `ANTHROPIC_API_KEY`, `apiKeyHelper` script, or `claude login` (OAuth).

## OpenAI Codex CLI

- **Headless:** `codex exec "task"` (interactive `codex` opens a TUI). `-` reads stdin. `--skip-git-repo-check` for non-git dirs. `cd` to the repo first (reads CWD).
- **Structured output:** `--json` → NDJSON stream (`thread.started`, `turn.*`, `item.*` incl. file changes / command exec / MCP calls, `error`). `--output-schema <file>` validates/shapes the final JSON.
- **Resume:** `codex exec resume [<id>|--last|--all]`; sessions at `~/.codex/sessions/`. ⚠️ resuming an `--ephemeral` session silently creates a new one.
- **Models/config:** `--model gpt-5.x|o4-mini|…` or `-c model=…`; `~/.codex/config.toml` (`model`, `model_provider`, `model_reasoning_effort`). Providers: `openai` (Responses API; Chat Completions deprecated Feb 2026), `oss` (Ollama/LM Studio), `azure`, `amazon-bedrock`. `[profiles.*]` bundles.
- **MCP:** `codex mcp add … | --url … | login`; stored under `[mcp_servers]`. `required=true` fails the run on startup error.
- **Sandbox/approval (two axes):** `--sandbox read-only|workspace-write|danger-full-access` × `approval_policy untrusted|on-request|never`. `--full-auto` = workspace-write + auto-approve (overrides `--sandbox`). `.git/`, `.codex/`, `.agents/` are auto read-only even in workspace-write. OS-level: macOS Seatbelt (`sandbox-exec`), Linux Landlock+seccomp (on by default), Windows restricted token. `--dangerously-bypass-approvals-and-sandbox` for external-sandbox use only.
- **SDK:** TS app-server SDK (`codex.startThread()` → `thread.run()`); Python controls the app-server over **JSON-RPC**. No full agent SDK parity with Claude; the intended programmatic path is `codex exec --json` as a subprocess.
- **Auth:** `codex login` (ChatGPT OAuth) or `OPENAI_API_KEY`/`CODEX_API_KEY` (CI).

## OpenCode

- **Headless surfaces (3):** `opencode run "task"` (one-shot), `opencode serve` (persistent **HTTP/OpenAPI server**, SSE at `/event`), `opencode acp` (JSON-RPC stdio for ACP clients).
- **`run` flags:** `--model provider/model`, `--dir`, `--file`, `--continue/-c`, `--session/-s`, `--fork`, `--format default|json`, `--agent`, `--dangerously-skip-permissions`, `--attach` (to a running server).
- **Structured output:** `--format json` → NDJSON (`step_start`, `text`, `tool_use`, `tool_result`, `step_finish` with `.part.tokens` + `.part.cost`). SDK `outputFormat: {type:'json_schema', schema}`.
- **Resume:** `--continue`, `--session <id>`, `--fork`; `opencode export <id>` / `import`. Sessions as JSON under `~/.local/share/opencode/storage/`.
- **HTTP API:** `POST /session`, `/session/:id/message` (sync), `/session/:id/prompt_async`, `/session/:id/command`, `/session/:id/shell`, `GET /mcp`, etc.
- **Models:** `provider/model`; 75+ providers; `model` + `small_model` in `opencode.json`; merged project/global config.
- **MCP:** `opencode mcp add [--url]`, dynamic via `POST /mcp`; status at `GET /mcp`.
- **Permissions:** `permission` map (`edit|bash|"rm -rf "` → `allow|ask|deny`); default allow-all; `--dangerously-skip-permissions`. **No native OS sandbox** — must be provided externally. ⚠️ known bug (#13851) where `run` preset can override agent permissions in some versions.
- **SDK:** official `@opencode-ai/sdk` (TS HTTP client over `opencode serve`); no official Python SDK (subprocess `opencode run --format json`).
- **Auth:** `opencode auth login` or provider env vars; creds in `~/.local/share/opencode/auth.json`.

## Implications for our adapter

- **Prefer ACP as the primary adapter** (uniform sessions/streaming/permissions across all three) and keep **native headless (`-p`/`exec`/`run --format json`) as a fallback** for capabilities ACP doesn't expose or harnesses that lack an adapter.
- **All three: parse NDJSON event streams** for tool calls, file edits, cost/tokens, and session IDs → maps cleanly onto our explicit-I/O + run-context model.
- **Diffs**: don't rely on JSON result fields — capture `git diff` in the agent's worktree (ties to the worktree-isolation pattern, [`concepts/orchestration-patterns.md`](concepts/orchestration-patterns.md)).
- **Cost/tokens** are emitted by all three (Claude `total_cost_usd`; OpenCode `step_finish.cost`; Codex token counts) → feed the run-context budget.
- **Sandbox is uneven**: Codex strongest (OS-level), Claude has a native sandbox + bypass, OpenCode has none → the orchestrator must supply isolation (worktree/container) itself. See [`concepts/safety-sandboxing.md`](concepts/safety-sandboxing.md).

Sources: see [`sources.md`](sources.md) → "Harness invocation".
