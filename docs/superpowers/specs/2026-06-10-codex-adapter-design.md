# Codex adapter — design (2026-06-10)

> Closes the declared-but-unimplemented harness gap: `Harness.codex` exists in the enum
> (`orchestrator/config/schemas.py`) but `HarnessRegistry.from_env()` cannot route to it.
> Third real adapter behind the spec §5 swappability seam, alongside ClaudeCode and OpenCode.

## Goal

A `CodexCLIAdapter` that drives OpenAI Codex via `codex exec --json` as a pipeline step,
emitting the same normalized `Event` stream as the other adapters, with the knowledge-base
MCP server wired in so codex roles can read (and, when granted, write) knowledge.

Non-goals: ACP transport (future `ACPAdapter`, spec §5), codex-native session resume
(mirrors the other adapters' MVP stance: `resume()` returns the handle unchanged),
per-tool capability translation beyond what codex exposes.

## Shape

New file `orchestrator/harness/codex.py`, mirroring `opencode.py` (closest pattern:
no single result event, no usable OS sandbox, worktree = isolation boundary):

- `parse_codex_line(obj, items) -> list[Event]` — pure JSONL-object → normalized events.
- `_mcp_overrides(servers) -> list[str]` — `McpServer` list → `-c` CLI override flags.
- `CodexCLIAdapter` — async streaming subprocess wrapper (near-copy of OpenCode's
  `_stream`: concurrent stderr drain, synthesized `Done`).

Registered in `HarnessRegistry.from_env()` as `Harness.codex: CodexCLIAdapter()`.

## Invocation

```
codex exec -C <cwd> --json --dangerously-bypass-approvals-and-sandbox \
  [-m <model>] <mcp -c overrides…> <prompt>
```

- Binary default `["codex"]`; honors `$ORCH_CODEX_BIN` (consistent with the other two).
- Stdout streamed as JSONL; stderr drained concurrently (chatty child must never block
  on a full pipe; non-zero exit reports its stderr tail — same as both peers).
- Model: optional `provider/model`-style string from the role, passed via `-m`. A
  per-session model overrides the construction default (same precedence as OpenCode).

### Sandbox: always bypass

Codex's own `-s workspace-write` sandbox uses bubblewrap, which fails to initialize in
externally-isolated environments (`bwrap: loopback: Failed RTM_NEWADDR` — the exact
failure that invalidated the first bench codex runs). The orchestrator already owns
isolation: each agent step runs in a throwaway git worktree (spec §4/§9), and OpenCode
ships with no OS sandbox at all under the same accepted MVP stance. So: one code path,
always `--dangerously-bypass-approvals-and-sandbox`, worktree is the hard boundary.
No env toggle, no `-s` mapping. (Documented trade-off: codex gets shell/network its
caps profile might not intend; same MVP posture as OpenCode, revisit with the
container/microVM sandbox deferred in spec §9.)

## MCP wiring (knowledge base)

**Constraint discovered during design:** codex auth (`auth.json`) lives in
`$CODEX_HOME` (`~/.codex`). A temp `CODEX_HOME` pointing at a generated `config.toml`
— the OpenCode-style approach — would break authentication. Rejected.

**Chosen mechanism (verified live against `codex mcp list`):** `-c` config overrides,
which layer on top of the user's real config, preserving auth and existing servers,
with nothing to clean up:

```python
-c mcp_servers.<name>.command=<json.dumps(s.command)>   # TOML string
-c mcp_servers.<name>.args=<json.dumps(list(s.args))>   # TOML array
-c mcp_servers.<name>.env.<KEY>=<json.dumps(value)>     # one per env key
```

`-c` values are parsed as TOML; `json.dumps` of a `str` / `list[str]` is valid TOML for
those types, and per-key `env.<KEY>` dotted paths avoid TOML inline-table syntax
entirely (the knowledge server's `ORCH_KB_SOURCES` value is itself a JSON blob — it
round-trips fine as a quoted TOML string; verified). Flags are passed via
`create_subprocess_exec` argv — no shell, no extra quoting layer.

This wires the existing knowledge provider (`orchestrator/knowledge/provider.py`)
unchanged: codex roles get `mcp__knowledge__*` read (and auditor-gated write) like
Claude/OpenCode roles do.

## Event mapping

Real `codex exec --json` schema, verified against captured transcripts in
`bench/results/*/C_codex/transcript.txt`:

| codex JSONL event | normalized `Event` |
|---|---|
| `thread.started {thread_id}` | `SessionStarted(thread_id)` |
| `item.completed` + `item.type=agent_message` | `MessageChunk(item.text)` |
| `item.started` + `command_execution` | `ToolCall("command", "in_progress")` |
| `item.completed` + `command_execution` | `ToolCall("command", "completed")` |
| `item.completed` + `file_change` → each `changes[]` entry | `FileEdit(path, kind)` with `add→create`, `update→modify`, `delete→delete` — completed only, so a change isn't double-counted (codex repeats the payload on `item.started`) |
| `turn.completed {usage}` | `Cost(usd=0.0, tokens=input_tokens+output_tokens)` — codex reports no cost; tokens summed, USD left 0 (consistent with bench `parse_codex_jsonl` deriving cost externally) |
| `item.completed` + `error` | remembered; surfaced in the synthesized `Done` |

Codex emits no single "result" event → **synthesize `Done` at stream end** (mirrors
OpenCode): result = accumulated `agent_message` text. `is_error=True` when the process
exits non-zero (append stderr tail, last 500 chars) — error items alone with a zero
exit do not fail the step (codex emits non-fatal `error` items, e.g. config
deprecation warnings; observed in every captured transcript).

`items` parameter: id → item-type map mutated across calls (symmetry with the other
parsers' `tool_names`), used to pair `item.started`/`item.completed`.

## Capabilities

`ResolvedCaps` cannot translate to codex flags under always-bypass (codex has no
allowed/disallowed tool flags in exec mode). As with OpenCode, the enforced
boundaries are: the worktree (filesystem), the orchestrator's diff capture + merge
gates (what lands), and knowledge-write gating (auditor path). `caps` is accepted
and stored on the session for forward compatibility (future sandboxed codex / ACP).

## Registry & tests

- `from_env()` adds `Harness.codex: CodexCLIAdapter()`.
- `tests/unit/test_registry.py::test_unregistered_harness_raises` currently uses
  `Harness.codex` as its unregistered example — switch it to an explicitly empty
  registry (`HarnessRegistry({})` + any harness) so the invariant survives; extend
  `test_from_env_*` to assert codex resolves (honoring `$ORCH_CODEX_BIN`).
- Parser unit tests over the real captured event shapes (thread.started, agent_message,
  command_execution started/completed, file_change, turn.completed usage, error item).
- `_mcp_overrides` unit tests incl. the JSON-blob-in-env round-trip.
- `tests/fixtures/fake_codex/` NDJSON script + adapter E2E (mirrors `fake_opencode`):
  stream events, synthesized Done, non-zero-exit → `is_error` + stderr tail.

TDD throughout (test first per unit).

## Out of scope / follow-ups

- Bench `agent_codex` keeps its direct subprocess call (bench deliberately drives raw
  binaries; switching contestant C to the adapter would change what's being measured).
- Codex-native `resume`/`fork` session continuation.
- Cost in USD for codex runs (no price feed; tokens are recorded).
