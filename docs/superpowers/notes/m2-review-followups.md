# M2 Review Follow-ups

> From the final holistic review of M2 (2026-06-04). M2 shipped **ready-with-minor-nits**:
> 96 tests green, ruff clean, `orch run --only plan` runs a single agent step end-to-end against
> the fake harness (capabilities → worktree → adapter → nested OTel spans → diff → artifact).
> The one [IMPORTANT] finding (a fail-open in capability translation) was **fixed before merge**
> (commit `f3042f1`): `ResolvedCaps` is now properly typed in `claude_code.py` and the
> `isinstance`-returns-`[]` guard is gone. The items below are deferred deliberately.

## Pick up early in M3 (cheap, real correctness wins)

- **Drain subprocess stderr (`harness/claude_code.py`).** `_stream` spawns `claude` with
  `stderr=PIPE` but never reads it. Harmless with the fake harness, but a real `claude` binary
  emitting lots of stderr can fill the pipe buffer and deadlock at `await proc.wait()`. Fix:
  `stderr=asyncio.subprocess.DEVNULL`, or drain it concurrently with stdout. Do this before M3
  wires the real binary into longer runs.

## Tied to M3 scope (typed I/O / DAG executor)

- **`output_schema` is plumbed but ignored.** `run_agent_step` threads `step.output_schema` into
  `adapter.prompt(...)`, but the adapter does not translate it to `--json-schema` (or equivalent).
  Clean no-op deferral today; when M3 adds typed I/O, wire it through (or drop the parameter until
  then so it doesn't read as "wired but broken").
- **Prompt rendering is minimal (M2 design decision #5).** `_render_prompt` only substitutes
  declared top-level input names (`<task>` → value) and uses a role-default for prompt-less steps.
  Full dataflow templating + `<step.output>` substitution is M3. This still sidesteps the open
  `<...>`-vs-prose syntax question (see M1 follow-ups) — revisit the syntax decision when M3 builds
  real templating.

## Architectural revisit (flagged in the plan's own self-review)

- **Diff capture location.** Spec §5 assigns diff capture to the *adapter*; M2 pragmatically kept
  `_capture_diff` in the executor (which owns the worktree). Revisit in M3 once multiple adapters /
  the DAG executor exist — decide whether the adapter should own it (e.g., an adapter
  `capture_diff(cwd)` method the executor calls).

## Representation-without-enforcement (deferred per spec §9, not a bug)

- `ResolvedCaps` computes all 7 dimensions, but `translate` only emits
  `--add-dir` / `--permission-mode` / `--allowedTools` / `--disallowedTools`. The other dimensions
  (`write_scope`, `network_egress`, `shell_deny`, `deny_read`, `knowledge_*`, `push_to_main`,
  `open_pr`) are resolved but not yet enforced at the harness. Network/secrets/OS-sandbox
  enforcement is deferred per spec §9 (M6 / documented-deferred). When wiring real enforcement,
  start with `deny_read` (Claude Code sandbox `denyRead`) and the shell deny-list.
- **MCP wiring deferred (M6).** `start_session` accepts `mcp_servers` but M2 always passes `[]`;
  `--mcp-config` generation + knowledge MCP (`mcp__knowledge__search`/`__write`) is M6.
- **`resume`/`cancel` minimal.** `resume` returns the handle unchanged; re-prompting a resumed
  session with `--resume <harness_session_id>` lands with the DAG executor (M3).
