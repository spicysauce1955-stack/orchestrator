# Codex Adapter — Progress Log (2026-06-10)

Spec: `docs/superpowers/specs/2026-06-10-codex-adapter-design.md` ·
Plan: `docs/superpowers/plans/2026-06-10-codex-adapter.md` ·
Follow-ups: `docs/superpowers/notes/codex-adapter-followups.md`

First item of the post-MVP queue (cleanup track → M7 → M8 → M9). Closed the
declared-but-unimplemented harness gap: `Harness.codex` existed in the enum since M1
but had no adapter — `from_env()` could not route to it. Both merges pushed to origin:
implementation `be36592`, real-binary fixes `274ed35`. Suite 297 green, ruff clean.

## What was built

`orchestrator/harness/codex.py`, mirroring the OpenCode adapter (closest pattern: no
single result event, no usable OS sandbox):

- **`parse_codex_line`** — pure JSONL parser for `codex exec --json`, shapes verified
  against captured bench transcripts: `thread.started`→SessionStarted,
  `agent_message`→MessageChunk, `command_execution`→ToolCall,
  `mcp_tool_call`→ToolCall(`mcp__<server>__<tool>`), `file_change`→FileEdit
  (**item.completed only** — started repeats the payload), `turn.completed`
  usage→Cost (usd=0.0: codex reports no price), error items→non-events.
- **`_mcp_overrides`** — McpServer → `-c mcp_servers.*` TOML override flags.
  **Key design discovery: codex `auth.json` lives in `$CODEX_HOME`, so the
  OpenCode-style temp-config approach would break authentication.** `-c` overrides
  layer on the real config instead (verified live vs `codex mcp list`); `json.dumps`
  of str/list[str] is valid TOML; per-key `env.<KEY>` dotted paths avoid inline
  tables. No temp file, nothing to clean up.
- **`CodexCLIAdapter`** — async streaming subprocess wrapper: always
  `--dangerously-bypass-approvals-and-sandbox` (codex's bwrap sandbox cannot init in
  externally-isolated environments — the failure that invalidated the first bench
  codex runs; the orchestrator's worktree is the isolation boundary, same MVP stance
  as OpenCode), concurrent stderr drain, synthesized `Done` at stream end (non-zero
  exit → last error items + stderr tail; non-fatal error items alone never fail a
  step). Honors `$ORCH_CODEX_BIN`. Registered in `HarnessRegistry.from_env()`.

Process: 4 TDD tasks executed subagent-driven, each with two-stage review (spec
compliance, then quality). Review fixes folded in: `ORCH_KB_WRITE_TARGET` env-key
coverage, exact flag-count assertion, clean `[codex exited N]` message when no
detail, `cancel()` and unknown-`kind` fallback pinned by tests.

## Real-binary validation (codex-cli 0.135.0)

Three staged smokes, mirroring the bench's de-risk discipline:

1. **Direct drive** — file creation through the adapter: session id, FileEdit,
   Cost (44k tokens), non-error Done, correct file on disk. PASS.
2. **Knowledge MCP read** — planted fact in a KB source, wired the real
   `orchestrator.knowledge.mcp_server` via `-c` overrides; codex retrieved it with
   `mcp__knowledge__search`. Auth preserved, existing user servers intact. PASS.
3. **Governed pipeline E2E** — new `bench-codex.yaml` + `codex_implementer` role
   (mirrors `bench-oc.yaml`): run `c5d213a8` implement (95-line diff, 251k tokens)
   → merge → **ttl_cache hidden suite 12/12**; `orch status` resolves both steps
   from the span store. PASS. (Context: governed claude historically scored 11/12
   on this task; raw claude 12/12.)

## The 9th real-vs-fake bug

Smoke 2 initially showed zero ToolCall events: **real codex emits MCP calls as their
own `mcp_tool_call` item type** (`server`/`tool`/`arguments`/`status` fields), which
the parser dropped — MCP usage produced no tool span (an observability hole feeding
the M6d "MCP-call spans" gap). Fixed TDD: mapped to `mcp__<server>__<tool>` with the
item's own status (covers `failed` on completed items), captured shape added to
parser tests, fake fixture, and E2E. This continues the pattern: every adapter's
fakes have masked at least one real wire-format difference (5 Claude, 2 OpenCode,
1 codex sandbox, now 1 codex MCP) — **real-binary smokes after any new adapter are
non-negotiable.**

## Deferred (see codex-adapter-followups.md)

- `_stream` GeneratorExit abandonment orphans the subprocess — in ALL THREE adapters
  (inherited pattern); fix is one cross-cutting commit.
- Codex USD cost always 0.0 (tokens recorded; no price feed).
- Codex-native resume/fork not wired (MVP stance shared by all adapters).

## Next

Cleanup round: M6d follow-ups (cross-process knowledge-write spans, resume-trace fix
landed earlier, span-DB GC) + the cross-cutting GeneratorExit fix → then M7
(knowledge mining) → M8 (templates + `orch init`) → M9 (best-of-n; premise still
questioned by the benchmark meta-finding — consider the un-hinted/multi-component
benchmark experiment first).
