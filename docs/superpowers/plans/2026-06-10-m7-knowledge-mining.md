# M7 — Knowledge Mining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An offline miner (`orch mine`) scans the durable span store for repeated patterns across runs and emits *candidate* lessons that the `auditor` role vets and writes through the existing gated `mcp__knowledge__write` path (spec §8.1).

**Architecture:** Pure read-model over `spans.sqlite` (same store the M6d lenses read). Three deterministic pattern detectors (no LLM): recurring step failures, repeated review rejections, recurring tool/MCP failures — each requiring evidence in ≥ `min_runs` distinct runs. Candidates render to `.orchestrator/knowledge/candidates.md` (regenerated, derived data, clearly marked UNVETTED). Governance unchanged: the miner never writes lessons; the auditor reads candidates as a knowledge source and approves through the deny-wins gated write (M6b).

**Tech Stack:** Python 3.11, sqlite3 + `json_extract`, Typer CLI, pytest.

**Span facts the miner reads** (verified against `executors.py`/`message_bus.py`/`query.py`):
- root `run` span: `run.id`, `pipeline` — maps trace_id → run_id.
- `step` span: `step.id`, `step.role`, `step.is_error`, `step.type`.
- `message` span: `msg.from/to/kind/body`; review loop-back emits `kind="verdict"` with `msg.to` = rejected step.
- `tool_call` span: `tool.name`, `tool.status` (`"failed"` on failure).
- `mcp.call` span (cleanup track): `mcp.tool`, `mcp.is_error`, `step.id`.

---

### Task 1: `Candidate` + recurring step failures

**Files:**
- Create: `orchestrator/knowledge/miner.py`
- Test: `tests/unit/test_miner.py`

- [ ] Write failing tests: seed a span DB (direct row inserts, reuse the `test_gc.py` seeding idiom) with `implement` failing in 2 of 3 runs and `plan` failing in 1 → `mine(db)` returns one `recurring_step_failure` candidate for `implement` (runs listed, count=2), none for `plan`; `min_runs=3` returns none.
- [ ] Run: `uv run pytest tests/unit/test_miner.py -q` → FAIL (no module).
- [ ] Implement `Candidate` (frozen dataclass: `kind`, `subject`, `runs: tuple[str, ...]`, `count`, `text`) and `mine(span_db, *, min_runs=2)` with the trace→run map + the step-failure detector:

```python
def _trace_runs(conn) -> dict[str, str]:
    rows = conn.execute(
        "SELECT trace_id, json_extract(attrs, '$.\"run.id\"') FROM spans WHERE name = 'run'"
    )
    return {str(t): str(r) for t, r in rows if r is not None}

# detector: SELECT spans WHERE name='step' AND json_extract(attrs,'$."step.is_error"')
# group by step.id → {step: {run_id, ...}}; emit when len(runs) >= min_runs
```

- [ ] Run tests → PASS. Commit.

### Task 2: repeated review rejections

**Files:** modify `orchestrator/knowledge/miner.py`, extend `tests/unit/test_miner.py`

- [ ] Failing test: seed `message` spans `kind="verdict"` to step `implement` in 2 runs (2 + 1 rejections) → one `repeated_rejection` candidate, count=3, runs=2, text contains the last feedback body (truncated to 200 chars).
- [ ] Implement detector (group verdict messages by `msg.to`; candidate when distinct runs ≥ min_runs; keep last body by start_ns). Run → PASS. Commit.

### Task 3: recurring tool / MCP failures

**Files:** modify `orchestrator/knowledge/miner.py`, extend `tests/unit/test_miner.py`

- [ ] Failing test: `tool_call` spans `tool.status="failed"` for `Bash` in 2 runs → `recurring_tool_failure` candidate; `mcp.call` spans with `mcp.is_error=true` for tool `write` in 2 runs → candidate with subject `mcp:write`; single-run failures ignored.
- [ ] Implement both queries in one detector (normalize: `tool_call`→`tool.name`, `mcp.call`→`f"mcp:{mcp.tool}"`). Run → PASS. Commit.

### Task 4: candidates file renderer

**Files:** modify `orchestrator/knowledge/miner.py`, extend `tests/unit/test_miner.py`

- [ ] Failing test: `write_candidates(cands, path)` writes markdown with an UNVETTED header (mentions auditor vetting + gated write), one `- [kind] text (runs: …)` bullet per candidate sorted by count desc, parent dirs created; empty list → file states "No candidates mined."
- [ ] Implement; run → PASS. Commit.

### Task 5: `orch mine` CLI

**Files:** modify `orchestrator/cli.py`, extend `tests/unit/test_miner.py` (CliRunner)

- [ ] Failing tests: `orch mine --repo <r>` with seeded `$ORCH_SPAN_DB` prints candidates and writes `<repo>/.orchestrator/knowledge/candidates.md`; `--min-runs 3` filters; no patterns → "no candidates mined." exit 0; `--out` overrides the path.
- [ ] Implement:

```python
@app.command()
def mine(
    repo: Path = typer.Option(Path("."), "--repo"),
    min_runs: int = typer.Option(2, "--min-runs"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Mine the span store for candidate lessons (spec §8.1). Auditor vets; never auto-written."""
```

- [ ] Run → PASS. Full suite + ruff. Commit.

### Task 6: example wiring + closed-loop seam test

**Files:**
- Create: `examples/feature-pipeline/.orchestrator/knowledge/candidates.yaml`
- Modify: `examples/feature-pipeline/.orchestrator/roles/auditor.yaml` (read grant)
- Test: extend `tests/unit/test_miner.py` or `tests/integration/test_knowledge_closed_loop.py`

- [ ] Failing test: workspace with a `candidates` source granted to a role → `build_knowledge_mcp` exposes it in `ORCH_KB_SOURCES`; lexical `search` over a written candidates.md finds a mined line (mine → file → searchable: the auditor can read candidates through the existing MCP path).
- [ ] Add the example source + auditor grant; verify `tests/integration/test_example_compiles.py` still passes. Run full suite + ruff. Commit.

### Task 7: note + merge

- [ ] Write `docs/superpowers/notes/2026-06-10-m7-mining.md` (what landed, deferred items).
- [ ] Full suite + ruff; merge `m7-knowledge-mining` → `main` (no-ff), push.

## Self-review
- Spec §8.1 coverage: capture (detectors over span store) ✓, codify (candidates file) ✓, propagate (auditor source + existing gated write) ✓, "depends on M6d span store" ✓ (reads same DB), governance preserved (no auto-write) ✓.
- Deliberately NOT in M7: LLM-based pattern summarization; auto-scheduling the miner after runs; writing candidates into lessons.md directly.
