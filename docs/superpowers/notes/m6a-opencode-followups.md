# M6a OpenCode Adapter — Follow-ups

> M6a shipped **ready-to-merge**: **190 tests green, ruff clean**. It adds a second
> `HarnessAdapter` (`OpenCodeCLIAdapter`) and a per-role `HarnessRegistry`, proving the project's
> swappability thesis — **harness ≠ model**. A pipeline can now run different steps on different
> harnesses: the `mixed-harness` example classifies on Claude (a `task` step) and implements on
> OpenCode (an `agent` step bound to the `opencoder` role). The role declares `model: zhipu/glm-4.6`,
> but note **that field is not yet threaded to the adapter at runtime** (see "Deferred" below) — what
> M6a actually proves is per-**harness** routing; per-role **model** selection is a separate, still-open
> dimension carried since M1. The
> `DeterministicScheduler` resolves the adapter per `role.harness` in `_make_node` (agent steps) and
> uses the registry default for task/merge/gate steps; a bare adapter still works via
> `HarnessRegistry.single` (back-compat). `OpenCodeCLIAdapter` spawns `opencode run --format json`,
> parses its NDJSON into the normalized event model, synthesizes a `Done` at stream end (OpenCode has
> no single result event), and translates `ResolvedCaps` into an OpenCode permission config injected
> via `OPENCODE_CONFIG` (a system-temp file, so the worktree diff stays clean).
>
> Built and tested entirely against a **fake `opencode` binary** (`tests/fixtures/fake_opencode/`,
> zero API cost) that defines the NDJSON contract — mirroring how the Claude adapter was built in M2.
> Manual CLI smoke confirmed end-to-end: `orch run mixed-harness` runs `classify` on the Claude fake
> and `implement` on the OpenCode fake, capturing the OpenCode edit diff (`feature.py`).

## Headline risk: real-vs-fake reconciliation

- **OpenCode NDJSON field names are not 100% pinned from docs.** The fake binary is the contract; the
  parser (`parse_opencode_line`) is written **tolerantly**. Before pointing at the real `opencode`
  binary, verify against it:
  - tool name location — parser accepts `tool` **or** `name`;
  - file path location — parser accepts `input.path` **or** `input.file_path`;
  - cost/tokens — assumed on `step_finish` as `cost` / `tokens`;
  - **whether a final/error event exists** — currently `Done` is synthesized at stream end with
    `is_error = (returncode != 0)`. If OpenCode emits an explicit error/result event, prefer it.
  - session id — assumed `sessionID` on `step_start`.
  This mirrors how the real `claude` binary was wired after M2. Until reconciled, the adapter is
  proven only against the fake.

## Caps translation is best-effort (no OS sandbox)

- OpenCode has **no OS sandbox** (spec §4.1): filesystem/network are not OS-enforced. The
  orchestrator's **worktree is the real isolation boundary**. `build_permission_config` translates
  `ResolvedCaps` to an OpenCode `permission` map at the tool level only: read-only → `edit: deny`,
  `bash: deny`; edit role → `edit: allow`, `bash` object with `shell_deny` patterns mapped to `deny`
  and `"*": "allow"`; credential paths (`*.env`, `**/.ssh/**`, `**/.aws/**`) always read-denied. This
  is the chosen fidelity for M6a — it constrains the agent, it does not sandbox the OS. The
  `shell_deny` → bash-pattern mapping is `"<pat>*"`-style prefix globbing; real OpenCode glob
  semantics should be confirmed during reconciliation.
- The permission config is written **outside** the worktree (`tempfile.mkstemp`, pointed at via
  `OPENCODE_CONFIG`), so agent diffs never include it. `cancel()` unlinks it; a leaked temp file in
  `$TMPDIR` on a non-cancelled path is acceptable for MVP.

## Deferred / out of M6a scope (not bugs)

- **`role.model` is not threaded to any adapter — project-wide gap, NOT an M6a regression.**
  `Role.model` (`schemas.py`) has been unconsumed since M1: the Claude adapter does not even accept a
  `model` param, and `HarnessRegistry.from_env()` builds `OpenCodeCLIAdapter()` with no model. The
  registry is keyed by `Harness`, not by `(harness, model)`, so a per-role model would require
  resolving/constructing adapters per step rather than per harness — an architectural change beyond
  M6a's scope. Consequence: an OpenCode step runs on OpenCode's default model regardless of the role's
  `model:` declaration. The adapter is *ready* for it (`OpenCodeCLIAdapter(model=...)` + `glm` alias),
  so wiring it is a small follow-up once the registry/scheduler grow per-role adapter resolution.
  M6a's milestone proof is the **harness** swap (routing), not the model swap.
- **`build_permission_config` does not consume `caps.deny_read` / `caps.write_scope`.** It hardcodes a
  fixed `_READ_DENY` list and a blanket `edit: allow` for edit roles, rather than translating the
  resolver's computed `deny_read` (`.git`, `.claude`, `~/.kube`, `~/.config/gh`, …) or the role's
  `filesystem.write` scope. This is consistent with "best-effort, no OS sandbox, worktree is the
  boundary," but the deny-read set OpenCode receives is narrower than what Claude enforces — fold into
  the reconciliation pass alongside the NDJSON field-name verification.
- **`Codex` adapter not built.** `Harness.codex` is a valid enum value but
  `HarnessRegistry.adapter_for(Harness.codex)` raises `KeyError` (asserted in `test_registry.py`).
- **`output_schema` not passed to OpenCode.** `prompt(..., output_schema=...)` is accepted but unused
  by the OpenCode adapter (same threaded-but-not-translated state as the Claude adapter).
- **MCP servers still `[]`.** `start_session` records `mcp_servers` but the adapter does not configure
  them. The knowledge provider (which would populate MCP servers) is the next sub-milestone, **M6b**.
- **Resume is a no-op handle** (`resume()` returns the session). Real `--session`/`--continue`
  re-prompt wiring across agent retries is not done (carried from the Claude adapter).
- **Model aliasing** is a one-entry map (`glm` → `zhipu/glm-4.6`); roles otherwise pass
  `provider/model` through verbatim.

## Remaining M6 scope (after M6a)

- M6b+: orchestrator agent (run-owner, message bus, worker Q&A); knowledge provider (core +
  on-demand lexical + auditor-gated write); `orch status` (read checkpoints/spans); safety baseline
  polish. These are the rest of the M6 scope per spec §12; M6a was the OpenCode adapter only.
