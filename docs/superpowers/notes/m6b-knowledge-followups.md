# M6b Knowledge Provider — Follow-ups

> M6b shipped **ready-to-merge**: **224 tests green, ruff clean**. It adds the
> knowledge provider (spec §8) across four layers. (1) **Lexical engine**
> (`orchestrator/knowledge/lexical.py`): pure term-frequency line matching over a
> configurable set of glob sources; no embeddings (spec defers). Python 3.11's
> `Path.glob("dir/**")` returns only directories, so the engine appends `/**/*`
> whenever a pattern ends in `/**`. (2) **Stdio MCP server**
> (`orchestrator/knowledge/mcp_server.py`): hand-rolled JSON-RPC 2.0
> newline-delimited server; no MCP SDK dependency. Implements
> `initialize`/`notifications/initialized`/`ping`/`tools/list`/`tools/call` —
> enough for a tools-only server. `search` is always offered; `write` is listed
> only when a write target is configured (deny-wins gating enforced by the
> provider that constructs the `ServerState`, with a defense-in-depth re-check
> inside the handler). `write` appends a one-line dated bullet (`- (YYYY-MM-DD)
> <lesson>`) to the target file. (3) **Provider**
> (`orchestrator/knowledge/provider.py`): `inject_core` copies the files listed
> in `core.yaml`'s `inject` key from the real repo into the agent's worktree
> (missing paths are silently skipped); `build_knowledge_mcp` turns
> `ResolvedCaps.knowledge_read`/`knowledge_write` into an `McpServer` descriptor
> — deny-wins: the write target env var is set ONLY when `caps.knowledge_write` is
> non-empty. (4) **MCP wiring in both adapters**: Claude writes an
> `mcpServers`-keyed JSON to a `tempfile.mkstemp` temp path and passes it via
> `--mcp-config`; `extra_allowed_tools` gets `mcp__<server>` entries so the tool
> allow-list covers the server. OpenCode folds an `mcp` key (each entry: `type:
> "local"`, `command` as a list, `environment` dict, `enabled: true`) into the
> OPENCODE_CONFIG JSON. Both files are written outside the worktree so agent
> diffs are never polluted; cleaned up in `cancel()`. (5) **Executor integration**
> (`orchestrator/runtime/executors.py`): `inject_core` is called before the
> harness drive; injected paths are passed to `_capture_diff(exclude=...)` so
> read-only core files are invisible in the captured diff. `build_knowledge_mcp`
> passes `root = Path(repo)` (the real repo, not the discarded worktree) so
> durable lessons persist past the run. Task steps do NOT receive the knowledge
> MCP (`_drive_harness` defaults `mcp_servers=()`).
>
> Built and tested entirely against the **existing fake harnesses** (zero API
> cost). The closed-loop integration test drives the MCP server directly as a
> subprocess, proving the full search→write path through the stdio wire format.

## Headline risk: real-vs-fake MCP reconciliation

The MCP wire format is written from docs and pinned by the fakes, NOT verified
against the real `claude`/`opencode` binaries. Specifically unverified:

- **Claude `--mcp-config` JSON shape**: the file uses top-level `mcpServers` with
  per-server keys `command` (string), `args` (list), `env` (object). If Claude's
  actual schema differs (e.g. nests differently, renames `env`), startup will
  silently fail to mount the server.
- **OpenCode `mcp` config shape**: `type: "local"`, `command` as a list,
  `environment` as the env field name, `enabled: true`. Any mismatch in field
  names or the list-vs-string distinction for `command` will silently drop the
  server.
- **Claude tool-allow syntax**: `extra_allowed_tools` receives `mcp__<server>`
  (e.g. `mcp__knowledge`) to allow all of a server's tools. The real `claude`
  binary may require `mcp__<server>__<tool>` per-tool entries instead of a
  server-level wildcard — unconfirmed.
- **End-to-end MCP call path**: because a fake harness never opens an MCP
  connection, "agent calls `mcp__knowledge__search` / `mcp__knowledge__write`"
  is proven only as the **sum** of independent tests — the server speaks MCP
  correctly (unit + closed-loop integration); the provider builds the right
  descriptor (unit); the adapter passes the right config (MCP-wiring integration
  tests). There is no single fake-harness e2e of a live MCP call. Reconcile
  against the real binaries before relying on live retrieval in production runs.

This mirrors the M6a NDJSON field-name reconciliation deferral; the pattern and
the risk are the same.

## MVP fidelity notes

- **Lexical only**: search is term-frequency line matching; no embeddings, no
  semantic similarity. Spec explicitly defers vector search.
- **Python 3.11 glob workaround**: `_iter_files` detects patterns ending in `/**`
  and appends `/**/*` to also match files at depth; without this, `Path.glob`
  returns only directories.
- **Write = append a bullet**: `write` appends `- (YYYY-MM-DD) <lesson>\n` to the
  first granted writable source's first configured path (defaulting to
  `.orchestrator/knowledge/lessons.md`). It creates parent directories if absent.
- **MCP server method coverage**: `initialize`, `notifications/initialized`,
  `ping`, `tools/list`, `tools/call`. This is sufficient for a tools-only server;
  resource/prompt methods are not implemented (not needed for spec §8 MVP).
- **Config written once per session**: both adapters write the MCP/permission
  config in `start_session`, not per `prompt` call, so repeated prompts within
  the same session do not orphan temp files.

## Deferred / out of M6b scope (not bugs)

- **Task steps don't receive the knowledge MCP.** `run_task_step` calls
  `_drive_harness` with the default `mcp_servers=()`. Task steps are cheap
  read-only glue; adding knowledge MCP to them is possible but not part of M6b's
  scope.
- **No `orch status` view of knowledge writes or MCP-call spans (M6c).** A write
  is a file append; MCP tool calls are not span-instrumented because the fake
  harness never actually invokes them. Spans for knowledge writes and MCP calls
  belong in the observability pass (M6c).
- **`_rpc_helpers.py` is used by two stdio tests; a third should reuse them.**
  `test_kb_mcp_stdio.py` and `test_knowledge_closed_loop.py` both import from
  `tests/integration/_rpc_helpers.py`. Any future stdio integration test should
  reuse those helpers rather than copy the send/read pattern.
- **Temp config files may leak in `$TMPDIR` on a non-cancelled path.** Both
  adapters clean up in `cancel()`; if a session ends without cancellation the
  temp file is orphaned. Acceptable for MVP, same behavior as M6a's OpenCode
  permission config.
- **`role.model` still not threaded to adapters.** Carried project-wide gap from
  M1/M6a — unchanged by M6b. The `Role.model` field has been unconsumed since M1;
  `HarnessRegistry` is keyed by `Harness`, not `(harness, model)`.
- **MCP server process lifecycle is owned by the harness.** The orchestrator
  spawns the MCP server as a subprocess (the harness manages the connection); there
  is no orchestrator-side teardown or health-check for the server process.
- **`build_knowledge_mcp` write target = first granted writable source's first
  path.** When multiple writable sources are granted, only the first source's
  first path is used as the append target. Multiple writable sources are not
  individually addressable at write time.

## Remaining M6 scope (after M6b)

- **Orchestrator agent**: run-owner, message bus, worker Q&A (M6c).
- **`orch status`**: read checkpoints/spans including knowledge-write events and
  MCP-call spans (M6c).
- **Safety baseline polish** (M6c+).

These are the rest of the M6 scope per spec §12; M6b was the knowledge provider
only.
