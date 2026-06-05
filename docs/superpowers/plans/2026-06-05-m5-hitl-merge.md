# M5 — HITL Gate + Resume + Merge→PR + Conflict Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the human-in-the-loop `approve` gate (LangGraph `interrupt()` → SQLite checkpoint → `orch resume`), and a `merge` step that sequential-rebases agent diffs onto the base branch and opens a PR, raising a HITL conflict gate on rebase conflicts.

**Architecture:** The `DeterministicScheduler` compiles its `StateGraph` with an `AsyncSqliteSaver` checkpointer keyed by `thread_id=run_id`. A `gate` step calls `interrupt()`, which checkpoints and halts the run; `orch resume <id> --approve|--reject` reloads the checkpoint and re-enters via `Command(resume=...)`. A conditional edge after the gate routes approve→forward / reject→END. The `merge` step (`type: task`, `merge_strategy: sequential-rebase`) builds an integration branch off the base, applies upstream agent diffs with `git apply --3way`, opens a PR (push + `gh`), and on apply-conflict raises its own `interrupt()` conflict gate.

**Tech Stack:** Python 3.11, LangGraph 1.2.x (`interrupt`, `Command`, `AsyncSqliteSaver`, `JsonPlusSerializer`), Pydantic v2, Typer, pytest-asyncio, OpenTelemetry. Package manager: **uv** (`uv run --extra dev python -m pytest`, `uv run --extra dev ruff check .`). NEVER system pip.

**Empirically validated before writing this plan (spikes):**
- `interrupt(payload)` inside a node halts `ainvoke`, which returns a dict containing key `"__interrupt__"` (a list of `Interrupt` objects, `.value` = the payload). The checkpointer is mandatory for interrupt to work.
- A *separate* `AsyncSqliteSaver` instance over the same db file + same `thread_id` reloads the pending interrupt; `ainvoke(Command(resume=value), config)` re-runs the interrupted node (from the top — `interrupt()` returns `value` instead of halting) and continues. This is the `orch run` → `orch resume` (separate process) path.
- `RunContext`/`Artifact` dataclasses round-trip through the SQLite checkpointer, but emit a "Deserializing unregistered type … blocked in a future version" warning unless registered. Setting `saver.serde = JsonPlusSerializer(allowed_msgpack_modules=[(module, qualname), …])` silences it. (`from_conn_string()` does NOT accept `serde=`; set the attribute after construction.)
- `git add -N` (intent-to-add) before `git diff` makes NEW files appear in the diff *with content* — required so merge can replay files the agent created (today `_capture_diff` only lists untracked names).
- `git apply --3way <diff>` cleanly applies a diff onto the same base; when the base has advanced on the same lines it returns rc≠0 and leaves `<<<<<<<` conflict markers — reliable conflict detection.

**Conventions to follow (carried from M1–M4):**
- Every new subagent runs `uv run --extra dev ruff check .` before declaring done (line-length 100; ruff drift bit M3).
- Fake-binary testing pattern (zero API cost): inject via constructor or `$ORCH_*_BIN`. This plan adds a fake `gh` mirroring the fake harness.
- Tests live under `tests/unit/` (pure logic) and `tests/integration/` (graph/CLI/git). `asyncio_mode="auto"`.

---

## File Structure

- `pyproject.toml` — add `langgraph-checkpoint-sqlite` to `dependencies`.
- `orchestrator/runtime/state.py` — extend `RunContext` (status, pipeline_name, gate_decisions, pending_interrupt); add `RunStatus` enum + serde-module registry constant.
- `orchestrator/runtime/executors.py` — fix `_capture_diff` (intent-to-add); add `run_gate_step`; add `run_merge_step`.
- `orchestrator/runtime/merge.py` (NEW) — `MergeConflict` exception, `build_integration_branch`/`apply_diffs`, `open_pull_request` (+ `$ORCH_GH_BIN` seam).
- `orchestrator/runtime/scheduler.py` — checkpointer wiring; unified router (verdict + gate); pause detection; new `resume()` method.
- `orchestrator/compile/ir.py` — gate steps become conditional sources.
- `orchestrator/cli.py` — `run` reports a paused gate; implement `resume`.
- `examples/feature-pipeline/.orchestrator/pipelines/full.yaml` (NEW) — classify→plan→implement→review⟲→test→audit→approve(gate)→merge demo.
- `tests/fixtures/fake_gh/fake_gh.py` (NEW) + `__init__.py` — fake `gh` binary.
- `tests/unit/test_capture_diff.py`, `tests/unit/test_merge.py` (NEW).
- `tests/integration/test_hitl_gate.py`, `tests/integration/test_merge_step.py`, `tests/integration/test_resume_cli.py`, `tests/integration/test_full_pipeline.py` (NEW).

---

## Task 1: State extensions + serde registration

**Files:**
- Modify: `orchestrator/runtime/state.py`
- Test: `tests/unit/test_state_m5.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_state_m5.py
from orchestrator.runtime.state import RunContext, RunStatus, CHECKPOINT_SERDE_MODULES


def test_runcontext_m5_defaults():
    ctx = RunContext(run_id="r1")
    assert ctx.status == RunStatus.RUNNING
    assert ctx.pipeline_name == ""
    assert ctx.gate_decisions == {}
    assert ctx.pending_interrupt is None


def test_runcontext_records_gate_decision():
    ctx = RunContext(run_id="r1")
    ctx.gate_decisions["approve"] = "approve"
    assert ctx.gate_decisions["approve"] == "approve"


def test_serde_modules_cover_state_types():
    # The checkpointer must be allowed to (de)serialize our dataclasses.
    assert ("orchestrator.runtime.state", "RunContext") in CHECKPOINT_SERDE_MODULES
    assert ("orchestrator.runtime.state", "Artifact") in CHECKPOINT_SERDE_MODULES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_state_m5.py -v`
Expected: FAIL (`ImportError: cannot import name 'RunStatus'`).

- [ ] **Step 3: Implement**

Edit `orchestrator/runtime/state.py`. Add the enum + constant near the top (after imports) and extend `RunContext`:

```python
from enum import Enum

class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"      # halted at a HITL gate, checkpointed, awaiting `orch resume`
    COMPLETED = "completed"
    ERROR = "error"

# Dataclasses the SQLite checkpointer must be allowed to (de)serialize.
CHECKPOINT_SERDE_MODULES = [
    ("orchestrator.runtime.state", "RunContext"),
    ("orchestrator.runtime.state", "Artifact"),
]
```

Extend `RunContext` (keep existing fields + `record`):

```python
@dataclass
class RunContext:
    run_id: str
    inputs: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    attempts: dict[str, int] = field(default_factory=dict)
    pipeline_name: str = ""                 # set by the scheduler; lets `resume` rebuild the graph
    status: RunStatus = RunStatus.RUNNING
    gate_decisions: dict[str, str] = field(default_factory=dict)  # gate step id -> "approve"|"reject"
    pending_interrupt: dict | None = None   # payload of the gate the run is paused at (for reporting)
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_state_m5.py -v`
Expected: PASS. Also run the full suite to confirm no regression: `uv run --extra dev python -m pytest -q`.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/state.py tests/unit/test_state_m5.py
git commit -m "feat(m5): RunContext gains status/pipeline_name/gate_decisions + serde module registry"
```

---

## Task 2: Add the SQLite checkpointer dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency via uv**

Run (from repo root):

```bash
uv add langgraph-checkpoint-sqlite
```

This adds `langgraph-checkpoint-sqlite>=3.1` to `[project].dependencies` and updates `uv.lock`. (It pulls in `aiosqlite`.)

- [ ] **Step 2: Verify the imports resolve**

Run:

```bash
uv run python -c "from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver; from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer; from langgraph.types import interrupt, Command; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(m5): add langgraph-checkpoint-sqlite for HITL checkpoint/resume"
```

---

## Task 3: `_capture_diff` includes new-file content (intent-to-add)

**Why:** Merge replays captured diffs. Today `_capture_diff` only appends `+++ untracked: <name>` lines (no content), so a file the agent *created* cannot be merged. Intent-to-add (`git add -N`) makes `git diff` emit a real patch (incl. `/dev/null` → file body) for new files.

**Files:**
- Modify: `orchestrator/runtime/executors.py` (`_capture_diff`)
- Test: `tests/unit/test_capture_diff.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_capture_diff.py
import subprocess
from pathlib import Path

from orchestrator.runtime.executors import _capture_diff


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def test_capture_diff_includes_new_file_content(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "new.txt").write_text("brand new\n")          # untracked / created
    (repo / "f.txt").write_text("line1\nCHANGED\nline3\n")  # modified tracked
    diff = _capture_diff(repo)
    assert "new.txt" in diff
    assert "brand new" in diff          # content present, not just the name
    assert "CHANGED" in diff


def test_capture_diff_is_reapplyable(tmp_path):
    """The captured diff applies cleanly onto a fresh checkout of the same base."""
    repo = _init_repo(tmp_path)
    (repo / "new.txt").write_text("brand new\n")
    (repo / "f.txt").write_text("line1\nCHANGED\nline3\n")
    diff = _capture_diff(repo)
    # Reset the working tree, then re-apply.
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
    (repo / "new.txt").unlink()
    proc = subprocess.run(
        ["git", "apply", "--3way", "-"], cwd=repo, input=diff, text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (repo / "new.txt").read_text() == "brand new\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_capture_diff.py -v`
Expected: FAIL (`test_capture_diff_includes_new_file_content`: "brand new" not in diff — only the name is).

- [ ] **Step 3: Implement**

Replace `_capture_diff` in `orchestrator/runtime/executors.py`:

```python
def _capture_diff(cwd: Path) -> str:
    """Diff of all changes in the worktree, including newly created files.

    `git add -N` (intent-to-add) registers untracked files so `git diff` emits a
    full patch (with content) for them — required so a captured diff can be
    re-applied by the merge step. Intent-to-add does not stage content, so it
    leaves the working tree otherwise untouched.
    """
    subprocess.run(
        ["git", "add", "-A", "-N"], cwd=cwd, capture_output=True, text=True
    )
    return subprocess.run(
        ["git", "diff"], cwd=cwd, capture_output=True, text=True
    ).stdout
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/unit/test_capture_diff.py -v`
Expected: PASS.

Then the full suite — the existing agent-step tests assert on diff line counts; confirm they still pass (the diff now includes new-file content, which is a superset):

Run: `uv run --extra dev python -m pytest -q`
Expected: PASS. If a pre-existing test asserted the *exact* old `+++ untracked:` marker string, update that assertion to match the real patch (search: `grep -rn "untracked" tests/`).

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/executors.py tests/unit/test_capture_diff.py
git commit -m "feat(m5): capture new-file content in diffs via intent-to-add (mergeable)"
```

---

## Task 4: Checkpointer wiring in the scheduler

**Why:** `interrupt()` requires a checkpointer. Wire `AsyncSqliteSaver` into `DeterministicScheduler` with `thread_id=run_id` and the serde allowlist, and have `run()` set `ctx.pipeline_name` + detect/record an interrupt.

**Files:**
- Modify: `orchestrator/runtime/scheduler.py`
- Test: `tests/integration/test_checkpointer.py`

This task adds the plumbing; the gate node that actually calls `interrupt()` lands in Task 5. To test the checkpointer in isolation, the test uses a tiny in-test graph hook is overkill — instead test that (a) `run()` sets `pipeline_name`/`status`, (b) a checkpoint db file is created, on an existing M4 pipeline driven by the fake harness.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_checkpointer.py
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


async def test_run_sets_pipeline_name_and_writes_checkpoint(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)
    ctx = await sched.run(ws.pipelines["review-demo"], {"task": "add x"}, "run-ckpt-1")
    assert ctx.pipeline_name == "review-demo"
    assert ctx.status == RunStatus.COMPLETED
    assert db.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_checkpointer.py -v`
Expected: FAIL (`DeterministicScheduler.__init__() got an unexpected keyword argument 'checkpoint_db'`).

- [ ] **Step 3: Implement**

Edit `orchestrator/runtime/scheduler.py`:

```python
from contextlib import asynccontextmanager

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from orchestrator.runtime.state import (
    CHECKPOINT_SERDE_MODULES, GraphState, RunContext, RunStatus,
)

_SERDE = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_SERDE_MODULES)
```

Update `__init__` to accept the db path; default under the repo:

```python
def __init__(self, workspace, adapter, repo, *, checkpoint_db: Path | None = None) -> None:
    self.workspace = workspace
    self.adapter = adapter
    self.repo = Path(repo)
    self.checkpoint_db = (
        Path(checkpoint_db) if checkpoint_db is not None
        else self.repo / ".orch" / "checkpoints.sqlite"
    )

@asynccontextmanager
async def _saver(self):
    self.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_db)) as saver:
        saver.serde = _SERDE  # from_conn_string() doesn't accept serde=; set it here
        yield saver
```

Change `_build` to take a saver and compile with it:

```python
def _build(self, pipeline: Pipeline, saver):
    ir = build_ir(pipeline)
    by_id = {s.id: s for s in pipeline.steps}
    builder = StateGraph(GraphState)
    for node_id in ir.nodes:
        builder.add_node(node_id, self._make_node(pipeline, by_id[node_id]))
    wire_edges(builder, ir, router=self._router(pipeline))  # _router added in Task 5
    return builder.compile(checkpointer=saver)
```

Rewrite `run()` to use the saver + thread_id and detect interrupts:

```python
async def run(self, pipeline, inputs, run_id) -> RunContext:
    ctx = RunContext(run_id=run_id, inputs=dict(inputs), pipeline_name=pipeline.name)
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
    tracer = get_tracer()
    async with self._saver() as saver:
        graph = self._build(pipeline, saver)
        with tracer.start_as_current_span(SPAN_RUN) as run_span:
            run_span.set_attribute("run.id", run_id)
            run_span.set_attribute("pipeline", pipeline.name)
            result = await graph.ainvoke({"ctx": ctx}, config)
        return self._finalize(result)

def _finalize(self, result: dict) -> RunContext:
    ctx = result["ctx"]
    interrupts = result.get("__interrupt__")
    if interrupts:
        ctx.status = RunStatus.PAUSED
        ctx.pending_interrupt = dict(interrupts[0].value)
    elif ctx.status == RunStatus.RUNNING:
        ctx.status = RunStatus.COMPLETED
    return ctx
```

> NOTE: This task references `self._router` (Task 5) — until Task 5 lands, temporarily keep the existing `wire_edges(builder, ir, router=self._verdict_router(pipeline))` call so this task compiles and its test passes. Task 5 renames it to `_router`. (Implementer: if doing strict task-at-a-time, leave `_verdict_router` wired here and switch to `_router` in Task 5.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_checkpointer.py -v`
Expected: PASS.

Run the full suite: `uv run --extra dev python -m pytest -q` — the existing `test_scheduler.py` / `test_review_loop.py` must still pass (they call `run()` the same way; `_finalize` now sets `status=COMPLETED`, which they don't assert on).

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/scheduler.py tests/integration/test_checkpointer.py
git commit -m "feat(m5): scheduler compiles with AsyncSqliteSaver checkpointer (thread_id=run_id)"
```

---

## Task 5: Gate step + conditional routing (approve→forward / reject→END)

**Why:** A `gate` step with `require_approval` must `interrupt()` the run; on resume the decision routes the graph. The gate node stores its decision in `ctx.gate_decisions[step.id]`; a conditional edge reads it.

**Files:**
- Modify: `orchestrator/compile/ir.py` (gate steps become conditional sources)
- Modify: `orchestrator/runtime/executors.py` (add `run_gate_step`)
- Modify: `orchestrator/runtime/scheduler.py` (gate node branch; unify `_verdict_router`→`_router` to handle gates)
- Test: `tests/integration/test_hitl_gate.py`, `tests/unit/test_ir_gate.py`

- [ ] **Step 1: Write the failing IR unit test**

```python
# tests/unit/test_ir_gate.py
from orchestrator.compile.ir import build_ir
from orchestrator.config.schemas import Pipeline, Step, StepType


def test_gate_step_outgoing_edges_are_conditional():
    pipe = Pipeline(
        name="p",
        steps=[
            Step(id="audit", type=StepType.task, prompt="x"),
            Step(id="approve", type=StepType.gate, require_approval=True, needs=["audit"]),
            Step(id="merge", type=StepType.task, needs=["approve"], merge_strategy="sequential-rebase"),
        ],
    )
    ir = build_ir(pipe)
    approve_edges = [e for e in ir.edges if e.source == "approve"]
    assert approve_edges, "gate must have an outgoing edge"
    assert all(e.conditional for e in approve_edges), "gate edges must be conditional"
    # merge is still reachable as the forward target
    assert any(e.target == "merge" for e in approve_edges)
```

- [ ] **Step 2: Write the failing HITL integration test**

```python
# tests/integration/test_hitl_gate.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _gate_pipeline() -> Pipeline:
    # Minimal: one task then a gate. No merge (that's Task 6/7).
    return Pipeline(
        name="gateonly",
        steps=[
            Step(id="audit", type=StepType.task, prompt="audit {{task}}"),
            Step(id="approve", type=StepType.gate, require_approval=True, needs=["audit"]),
        ],
    )


def _sched(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    repo = _git_repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    return DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)


async def test_run_pauses_at_gate(tmp_path, monkeypatch):
    sched = _sched(tmp_path, monkeypatch)
    ctx = await sched.run(_gate_pipeline(), {"task": "ship it"}, "run-gate-1")
    assert ctx.status == RunStatus.PAUSED
    assert ctx.pending_interrupt is not None
    assert ctx.pending_interrupt.get("step_id") == "approve"
    # gate has not recorded a decision yet
    assert "approve" not in ctx.gate_decisions


async def test_resume_approve_completes(tmp_path, monkeypatch):
    sched = _sched(tmp_path, monkeypatch)
    await sched.run(_gate_pipeline(), {"task": "ship it"}, "run-gate-2")
    ctx = await sched.resume("run-gate-2", "approve")
    assert ctx.status == RunStatus.COMPLETED
    assert ctx.gate_decisions["approve"] == "approve"


async def test_resume_reject_ends_run(tmp_path, monkeypatch):
    sched = _sched(tmp_path, monkeypatch)
    await sched.run(_gate_pipeline(), {"task": "ship it"}, "run-gate-3")
    ctx = await sched.resume("run-gate-3", "reject")
    assert ctx.status == RunStatus.COMPLETED  # the run ends cleanly (rejected, not errored)
    assert ctx.gate_decisions["approve"] == "reject"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --extra dev python -m pytest tests/unit/test_ir_gate.py tests/integration/test_hitl_gate.py -v`
Expected: FAIL (gate edges not conditional; gate node raises `NotImplementedError`; `resume` missing).

- [ ] **Step 4: Implement — IR**

In `orchestrator/compile/ir.py`, treat gate steps as conditional sources. Change the `reject_sources` line and the `conditional=` predicate:

```python
from orchestrator.config.schemas import StepType  # add import

# A step is a branch point if it declares on_reject OR is a gate (approve/reject).
conditional_sources = {s.id for s in steps if s.on_reject} | {
    s.id for s in steps if s.type == StepType.gate
}
```

Then build edges with `conditional=e.source in conditional_sources`, and update the `terminals` predicate so a gate is not wrongly treated as terminal when it has no `needs`-successor — gates always route (approve→successor, reject→END). Keep the existing terminal logic (a gate with a forward successor is not in `needed`-less set issues; a gate with no successor still routes to END via the router). Leave `terminals` as-is; the router returns END when there is no forward target.

> Edge ordering note: `build_ir` already emits forward (`needs`) edges before back-edges. For a gate, the single forward edge (e.g. `approve→merge`) is the only outgoing edge, so `targets[0]` is the forward successor — consistent with the router below.

- [ ] **Step 5: Implement — gate executor**

In `orchestrator/runtime/executors.py` add:

```python
from langgraph.types import interrupt

def run_gate_step(step: Step, ctx: RunContext) -> str:
    """HITL gate: interrupt() halts+checkpoints the run; on resume returns the decision.

    The payload shown to the human summarizes the run so far. The returned value
    ('approve'|'reject') is stored in ctx.gate_decisions for the conditional edge.
    """
    last = next(reversed(ctx.artifacts.values()), None) if ctx.artifacts else None
    payload = {
        "step_id": step.id,
        "prompt": f"Approve step '{step.id}'? Reply approve|reject.",
        "run_id": ctx.run_id,
        "last_output": (last.output[:500] if last else ""),
        "total_cost_usd": ctx.total_cost_usd,
    }
    decision = interrupt(payload)
    decision = "reject" if str(decision).lower() == "reject" else "approve"
    ctx.gate_decisions[step.id] = decision
    return decision
```

Gate steps are synchronous (no harness/worktree); `interrupt()` is called directly. (It raises `GraphInterrupt` internally on first pass — do NOT wrap it in try/except.)

- [ ] **Step 6: Implement — scheduler node + unified router**

In `orchestrator/runtime/scheduler.py`:

In `_make_node`, replace the `else: raise NotImplementedError` gate branch:

```python
else:  # gate
    run_gate_step(step, ctx)
```

(import `run_gate_step`).

Rename `_verdict_router` to `_router` and extend it to handle gate sources:

```python
def _router(self, pipeline: Pipeline):
    by_id = {s.id: s for s in pipeline.steps}

    def router(source: str, targets: list[str]):
        src = by_id[source]
        reject_target = src.on_reject
        forward = [t for t in targets if t != reject_target]

        def route_fn(state: GraphState) -> str:
            ctx = state["ctx"]
            if src.type == StepType.gate:
                # approve -> forward successor; reject -> END
                if ctx.gate_decisions.get(source) == "reject":
                    return END
                return forward[0] if forward else END
            # verdict (on_reject) source
            art = ctx.artifacts.get(source)
            verdict = (art.output_data or {}).get("verdict") if art else None
            if (
                verdict == Verdict.REJECT
                and reject_target is not None
                and ctx.attempts.get(reject_target, 0) <= by_id[reject_target].max_retries
            ):
                return reject_target
            return forward[0] if forward else END

        return route_fn

    return router
```

Update `_build` (Task 4) to call `self._router(pipeline)`.

Add the `resume` method:

```python
async def resume(self, run_id: str, decision: str) -> RunContext:
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
    async with self._saver() as saver:
        # Reload state to discover which pipeline this run belongs to.
        # We build a throwaway graph only to read state; pipeline comes from ctx.
        state = await saver.aget(config)
        if state is None:
            raise KeyError(f"no checkpoint for run '{run_id}'")
        ctx_pre = state["channel_values"]["ctx"]
        pipeline = self.workspace.pipelines[ctx_pre.pipeline_name]
        graph = self._build(pipeline, saver)
        result = await graph.ainvoke(Command(resume=decision), config)
        return self._finalize(result)
```

> IMPLEMENTER NOTE: `saver.aget(config)` returns the raw checkpoint dict; the channel values live under `["channel_values"]`. If the structure differs in langgraph-checkpoint-sqlite 3.1, use the compiled graph's `aget_state` instead: build the graph first with any pipeline is impossible (need pipeline to build) — so prefer reading `ctx_pre.pipeline_name` from the checkpoint dict. Verify the exact key with a one-off `uv run python -c` against a real checkpoint during implementation; adjust the accessor. The contract that MUST hold: `resume` recovers `pipeline_name` from the checkpoint without the caller passing it.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/unit/test_ir_gate.py tests/integration/test_hitl_gate.py -v`
Expected: PASS. Then full suite: `uv run --extra dev python -m pytest -q` (existing review-loop/scheduler tests must still pass — `_router` is a superset of `_verdict_router`).

- [ ] **Step 8: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/compile/ir.py orchestrator/runtime/executors.py orchestrator/runtime/scheduler.py tests/unit/test_ir_gate.py tests/integration/test_hitl_gate.py
git commit -m "feat(m5): HITL gate step (interrupt) + resume + approve/reject conditional routing"
```

---

## Task 6: Merge module — apply diffs onto an integration branch + verdict guard

**Files:**
- Create: `orchestrator/runtime/merge.py`
- Test: `tests/unit/test_merge.py`

This task builds the pure git mechanics (no interrupt, no PR yet). The merge *step executor* (which wires this into the graph + conflict gate + PR) lands in Task 7.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_merge.py
import subprocess
from pathlib import Path

import pytest

from orchestrator.runtime.merge import MergeConflict, apply_diffs, base_branch


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _diff_for(repo, edits: dict[str, str]) -> str:
    """Produce a reapplyable diff by editing a throwaway worktree off HEAD."""
    wt = repo / ".worktrees" / "tmp"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "HEAD"], cwd=repo, check=True)
    for name, content in edits.items():
        (wt / name).write_text(content)
    subprocess.run(["git", "add", "-A", "-N"], cwd=wt, check=True)
    diff = subprocess.run(["git", "diff"], cwd=wt, capture_output=True, text=True).stdout
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=True)
    return diff


def test_base_branch(tmp_path):
    repo = _repo(tmp_path)
    assert base_branch(repo) == "main"


def test_apply_diffs_clean(tmp_path):
    repo = _repo(tmp_path)
    diff = _diff_for(repo, {"f.txt": "line1\nCHANGED\nline3\n", "new.txt": "hello\n"})
    branch = apply_diffs(repo, "orch/r1/merge", [diff], base="main")
    # the integration branch exists and carries the changes
    show = subprocess.run(
        ["git", "show", f"{branch}:new.txt"], cwd=repo, capture_output=True, text=True
    )
    assert show.returncode == 0 and show.stdout == "hello\n"


def test_apply_diffs_conflict_raises(tmp_path):
    repo = _repo(tmp_path)
    diff = _diff_for(repo, {"f.txt": "line1\nMINE\nline3\n"})
    # Advance base on the same line so the diff no longer applies cleanly.
    (repo / "f.txt").write_text("line1\nTHEIRS\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "advance"], cwd=repo, check=True)
    with pytest.raises(MergeConflict) as exc:
        apply_diffs(repo, "orch/r1/merge", [diff], base="main")
    assert "f.txt" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_merge.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.runtime.merge`).

- [ ] **Step 3: Implement**

Create `orchestrator/runtime/merge.py`:

```python
"""Merge manager (spec §6): sequential-rebase agent diffs onto base → PR.

MVP merges by re-applying captured agent diffs onto a fresh integration branch
off the base (the diffs were captured off the same base, so a clean apply is the
no-conflict case). A failed `git apply --3way` is a rebase conflict → HITL.
PR creation is a thin seam (push + `gh`), faked in tests via $ORCH_GH_BIN.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class MergeConflict(RuntimeError):
    """Raised when a captured diff does not apply cleanly onto the current base."""


def base_branch(repo: Path) -> str:
    """The branch the run targets (the repo's current branch)."""
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def apply_diffs(repo: Path, branch: str, diffs: list[str], *, base: str) -> str:
    """Create `branch` off `base`, apply each diff (3-way), commit. Returns branch.

    Raises MergeConflict (and cleans up the integration worktree) if any diff
    fails to apply. Idempotent: a pre-existing integration worktree/branch is
    removed first so resume/retry starts clean.
    """
    repo = Path(repo)
    safe = branch.replace("/", "-")
    wt = repo / ".worktrees" / safe
    # Clean any stale integration worktree/branch (retry-safe).
    _git(repo, "worktree", "remove", "--force", str(wt))
    _git(repo, "branch", "-D", branch)
    wt.parent.mkdir(parents=True, exist_ok=True)

    res = _git(repo, "worktree", "add", "-b", branch, str(wt), base)
    if res.returncode != 0:
        raise MergeConflict(f"could not create integration branch: {res.stderr.strip()}")
    try:
        for diff in diffs:
            if not diff.strip():
                continue
            proc = subprocess.run(
                ["git", "apply", "--3way", "-"],
                cwd=wt, input=diff, text=True, capture_output=True,
            )
            if proc.returncode != 0:
                files = _conflicted_files(wt)
                raise MergeConflict(
                    f"rebase conflict applying diff in {', '.join(files) or '?'}: "
                    f"{proc.stderr.strip()}"
                )
            _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", f"orchestrator: integrate ({branch})")
    except MergeConflict:
        _git(repo, "worktree", "remove", "--force", str(wt))
        _git(repo, "branch", "-D", branch)
        raise
    # Keep the branch; remove the worktree (the branch is what the PR pushes).
    _git(repo, "worktree", "remove", "--force", str(wt))
    return branch


def _conflicted_files(wt: Path) -> list[str]:
    out = _git(wt, "diff", "--name-only", "--diff-filter=U").stdout
    return [ln for ln in out.splitlines() if ln.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_merge.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/merge.py tests/unit/test_merge.py
git commit -m "feat(m5): merge module — apply agent diffs onto integration branch, conflict raises"
```

---

## Task 7: Merge step executor + conflict gate + verdict guard

**Why:** Wire `merge.py` into a graph node: collect upstream agent diffs, refuse on a non-`approve` terminal review verdict, apply diffs, and on `MergeConflict` raise a HITL conflict gate (`interrupt()`); on resume `approve`→retry, `reject`→fail.

**Files:**
- Modify: `orchestrator/runtime/executors.py` (add `run_merge_step`)
- Modify: `orchestrator/runtime/scheduler.py` (route `task` steps with `merge_strategy` to `run_merge_step`)
- Test: `tests/integration/test_merge_step.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_merge_step.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
GH = Path(__file__).parents[1] / "fixtures" / "fake_gh" / "fake_gh.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _sched(tmp_path, monkeypatch, repo):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_GH_BIN", f"{sys.executable} {GH}")
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")  # implement creates a file
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    return DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)


def _pipeline_with_merge() -> Pipeline:
    return Pipeline(
        name="mergetest",
        steps=[
            Step(id="implement", role="implementer", prompt="do {{task}}", success_criteria="true"),
            Step(id="merge", type=StepType.task, needs=["implement"],
                 merge_strategy="sequential-rebase"),
        ],
    )


async def test_merge_creates_branch_and_opens_pr(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    sched = _sched(tmp_path, monkeypatch, repo)
    # local bare remote so `git push origin` works
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    ctx = await sched.run(_pipeline_with_merge(), {"task": "add feature"}, "run-merge-1")
    assert ctx.status == RunStatus.COMPLETED
    merge_art = ctx.artifacts["merge"]
    assert not merge_art.is_error
    assert merge_art.output_data and merge_art.output_data.get("pr_url")


async def test_merge_refuses_on_reject_verdict(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    sched = _sched(tmp_path, monkeypatch, repo)
    pipe = Pipeline(
        name="mergeguard",
        steps=[
            Step(id="implement", role="implementer", prompt="do {{task}}", success_criteria="true"),
            Step(id="review", role="reviewer", needs=["implement"], prompt="review",
                 output_schema={"verdict": "enum[approve,reject]"}),
            Step(id="merge", type=StepType.task, needs=["review"],
                 merge_strategy="sequential-rebase"),
        ],
    )
    # Drive review to "reject": use the numbered review scripts (review.1 = reject).
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    # Pre-seed the counter so the first review call hits review.1 (reject). See fake harness.
    ctx = await sched.run(pipe, {"task": "x"}, "run-merge-guard")
    merge_art = ctx.artifacts.get("merge")
    assert merge_art is not None and merge_art.is_error
    assert "verdict" in merge_art.output.lower()
```

> IMPLEMENTER NOTE on the reject-verdict test: the existing fake harness routes `review` → `review.ndjson` (approve) by default and uses `$ORCH_FAKE_STATE` numbered variants. If seeding the reject variant first is awkward, instead drive reject by writing a dedicated script and setting `ORCH_FAKE_SCRIPT` for a single-review pipeline, or construct the `review` artifact's `output_data={"verdict":"reject"}` directly via a unit-level test of the guard helper. The REQUIRED assertion: a merge step refuses (is_error, message mentions the verdict) when the last review verdict is not `approve`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_merge_step.py -v`
Expected: FAIL (`run_merge_step` missing / merge raises NotImplementedError).

- [ ] **Step 3: Implement — `run_merge_step`**

In `orchestrator/runtime/executors.py`:

```python
from langgraph.types import interrupt

from orchestrator.runtime.merge import MergeConflict, apply_diffs, base_branch, open_pull_request


def _terminal_verdict(ctx: RunContext) -> str | None:
    """The last recorded review verdict, if any step produced one."""
    verdict = None
    for art in ctx.artifacts.values():
        if art.output_data and "verdict" in art.output_data:
            verdict = art.output_data["verdict"]
    return verdict


async def run_merge_step(
    workspace: Workspace, pipeline: Pipeline, step: Step, ctx: RunContext,
    *, repo: Path, adapter: HarnessAdapter,
) -> Artifact:
    """Merge upstream agent diffs onto base → open PR. Conflict → HITL conflict gate."""
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_STEP) as span:
        span.set_attribute("step.id", step.id)
        span.set_attribute("step.type", "merge")

        # Verdict guard (M4 follow-up): never merge a non-approved change.
        verdict = _terminal_verdict(ctx)
        if verdict is not None and verdict != "approve":
            span.set_attribute("merge.blocked_verdict", verdict)
            art = Artifact(step_id=step.id, output=f"merge refused: review verdict is '{verdict}', not approve",
                           diff="", branch="", cost_usd=0.0, tokens=0, is_error=True)
            ctx.record(art)
            return art

        # Collect diffs from upstream agent steps, in pipeline order.
        diffs = [
            a.diff for s in pipeline.steps
            if s.type == StepType.agent and (a := ctx.artifacts.get(s.id)) and a.diff.strip()
        ]
        base = base_branch(Path(repo))
        branch = f"orch/{ctx.run_id}/merge"
        try:
            apply_diffs(Path(repo), branch, diffs, base=base)
        except MergeConflict as conflict:
            # HITL conflict gate (spec §6): stop & ask.
            decision = interrupt({
                "step_id": step.id, "kind": "conflict", "run_id": ctx.run_id,
                "prompt": "Merge conflict. Resolve base and reply approve to retry, reject to abort.",
                "detail": str(conflict),
            })
            if str(decision).lower() == "reject":
                art = Artifact(step_id=step.id, output=f"merge aborted on conflict: {conflict}",
                               diff="", branch="", cost_usd=0.0, tokens=0, is_error=True)
                ctx.record(art)
                return art
            # approve → retry once (base presumably resolved by the human).
            apply_diffs(Path(repo), branch, diffs, base=base)

        pr = open_pull_request(Path(repo), branch, base=base, title=f"orchestrator: {ctx.run_id}")
        span.set_attribute("merge.branch", branch)
        span.set_attribute("merge.pr_url", pr)
        art = Artifact(step_id=step.id, output=f"opened PR for {branch} -> {base}: {pr}",
                       diff="", branch=branch, cost_usd=0.0, tokens=0, is_error=False,
                       output_data={"pr_url": pr, "branch": branch, "base": base})
        ctx.record(art)
        return art
```

- [ ] **Step 4: Implement — PR seam in `merge.py`**

Append `open_pull_request` to `orchestrator/runtime/merge.py`:

```python
def _gh_binary() -> list[str]:
    env = os.environ.get("ORCH_GH_BIN")
    return env.split() if env else ["gh"]


def open_pull_request(repo: Path, branch: str, *, base: str, title: str) -> str:
    """Push the integration branch to origin and open a PR. Returns the PR URL.

    Uses `gh` (overridable via $ORCH_GH_BIN for tests). If there is no `origin`
    remote, returns a local pseudo-ref (MVP: no remote configured).
    """
    has_origin = _git(repo, "remote", "get-url", "origin").returncode == 0
    if not has_origin:
        return f"local:{branch}"  # MVP: nothing to push to
    push = _git(repo, "push", "-q", "origin", branch)
    if push.returncode != 0:
        raise MergeConflict(f"git push failed: {push.stderr.strip()}")
    proc = subprocess.run(
        [*_gh_binary(), "pr", "create", "--base", base, "--head", branch,
         "--title", title, "--body", "Opened by orchestrator."],
        cwd=repo, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MergeConflict(f"gh pr create failed: {proc.stderr.strip()}")
    return proc.stdout.strip()
```

- [ ] **Step 5: Implement — route merge in the scheduler**

In `orchestrator/runtime/scheduler.py` `_make_node`, the `task` branch must dispatch merge steps to `run_merge_step`:

```python
if step.type == StepType.task:
    if step.merge_strategy is not None:
        await run_merge_step(self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self.adapter)
    else:
        await run_task_step(self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self.adapter)
```

(import `run_merge_step`). Also: `run_task_step` currently raises `NotImplementedError` when `merge_strategy is not None` — that branch is now unreachable from the scheduler, but leave the guard (it protects `--only`/direct callers). Update its message to note merge runs via the scheduler.

- [ ] **Step 6: Create the fake `gh` binary**

Create `tests/fixtures/fake_gh/__init__.py` (empty) and `tests/fixtures/fake_gh/fake_gh.py`:

```python
#!/usr/bin/env python3
"""Fake `gh` for tests. Records argv to $ORCH_GH_ARGV (if set), prints a PR URL."""
import os
import sys
from pathlib import Path


def main() -> int:
    argv_file = os.environ.get("ORCH_GH_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(sys.argv[1:]))
    # `gh pr create ...` -> print a fake URL on stdout (what the real gh does).
    if len(sys.argv) >= 3 and sys.argv[1] == "pr" and sys.argv[2] == "create":
        print("https://github.com/example/repo/pull/1")
    return int(os.environ.get("ORCH_GH_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/integration/test_merge_step.py -v`
Expected: PASS. Then full suite: `uv run --extra dev python -m pytest -q`.

- [ ] **Step 8: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/executors.py orchestrator/runtime/merge.py orchestrator/runtime/scheduler.py tests/integration/test_merge_step.py tests/fixtures/fake_gh/
git commit -m "feat(m5): merge step — diffs->integration branch->PR, verdict guard, conflict gate"
```

---

## Task 8: Conflict-gate resume (integration)

**Why:** Prove the merge conflict gate pauses the run and that `resume --approve` (after the human fixes the base) completes and `resume --reject` aborts.

**Files:**
- Test: `tests/integration/test_conflict_gate.py`

(No new production code expected — Task 7 implemented the conflict gate. This task is a dedicated integration test that exercises the cross-process pause/resume path for conflicts. If it reveals a gap, fix in Task 7's modules.)

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_conflict_gate.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "shared.txt").write_text("alpha\nbeta\ngamma\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


async def test_merge_conflict_pauses_then_aborts(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    # implement edits shared.txt's middle line in its worktree...
    monkeypatch.setenv("ORCH_FAKE_EDIT_FILE", "shared.txt")  # see note below
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)
    pipe = Pipeline(
        name="conflict",
        steps=[
            Step(id="implement", role="implementer", prompt="edit {{task}}", success_criteria="true"),
            Step(id="merge", type=StepType.task, needs=["implement"],
                 merge_strategy="sequential-rebase"),
        ],
    )
    # Advance base on the same line BEFORE merge applies the (already-captured) diff.
    # Simplest deterministic approach: the merge's apply runs against current HEAD;
    # we make implement's diff conflict by committing a clashing change to HEAD after
    # implement's worktree was created off the original base. Achieve this with a
    # monkeypatched hook OR by using two implement-like steps. See IMPLEMENTER NOTE.
    ctx = await sched.run(pipe, {"task": "shared.txt"}, "run-conflict-1")
    assert ctx.status == RunStatus.PAUSED
    assert ctx.pending_interrupt.get("kind") == "conflict"
    # Human aborts.
    ctx2 = await sched.resume("run-conflict-1", "reject")
    assert ctx2.status == RunStatus.COMPLETED
    assert ctx2.artifacts["merge"].is_error
```

> IMPLEMENTER NOTE (conflict construction): inducing a real apply-conflict deterministically with the fake harness needs the base to diverge from where implement's diff was captured. Two viable approaches — pick whichever is cleanest:
> 1. **Fake-harness edit hook:** extend the fake harness to *modify* an existing tracked file (not just touch a new one) via a new env var (e.g. `ORCH_FAKE_EDIT_FILE` → rewrite its middle line). Then add a pre-merge step (a second `task`/agent) or a test fixture that commits a clashing change to the repo HEAD between implement and merge. Since steps run off HEAD and merge applies off HEAD, you must mutate repo HEAD mid-run — do this with a tiny custom node or by committing in the test before constructing the diff.
> 2. **Unit-style seam (preferred if (1) is fiddly):** test `run_merge_step`'s conflict path directly — pre-build a `RunContext` whose implement artifact carries a `diff` that conflicts with an advanced base, call `run_merge_step` through a one-node graph with the checkpointer, assert PAUSED + `kind=conflict`, then resume. This avoids fake-harness gymnastics while still exercising the real interrupt/resume path.
>
> Choose the approach that yields a deterministic conflict. The REQUIRED assertions: (a) a merge conflict pauses with `pending_interrupt["kind"]=="conflict"`; (b) `resume(..., "reject")` ends the run with `merge.is_error`. Optionally also assert `resume(..., "approve")` retries after the base is fixed.

- [ ] **Step 2: Run + iterate to green**

Run: `uv run --extra dev python -m pytest tests/integration/test_conflict_gate.py -v`
Expected: PASS once the conflict is constructed deterministically. If the fake-harness edit hook (approach 1) is used, add the env var handling to `tests/fixtures/fake_harness/fake_harness.py` (mirroring `ORCH_FAKE_TOUCH`: if `ORCH_FAKE_EDIT_FILE` is set and the file exists, rewrite a line) and commit that fixture change here.

- [ ] **Step 3: ruff + commit**

```bash
uv run --extra dev ruff check .
git add tests/integration/test_conflict_gate.py tests/fixtures/fake_harness/fake_harness.py
git commit -m "test(m5): merge conflict gate pauses + resume aborts/retries"
```

---

## Task 9: CLI — `run` reports a paused gate; `resume` command

**Files:**
- Modify: `orchestrator/cli.py`
- Test: `tests/integration/test_resume_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_resume_cli.py
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app

runner = CliRunner()
FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
ROOT = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def test_run_pauses_and_resume_completes(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_CHECKPOINT_DB", str(db))
    common = ["--root", str(ROOT), "--repo", str(repo)]
    # full.yaml ends in approve(gate)->merge; with no origin, PR is a local ref.
    res = runner.invoke(app, ["run", "full", "--task", "add x", *common])
    assert res.exit_code == 0, res.output
    assert "paused" in res.output.lower()
    assert "orch resume" in res.output
    # extract run id from output (printed as `run <id>`)
    run_id = next(t for line in res.output.splitlines() if "run " in line
                  for t in line.split() if len(t) == 8 and t.isalnum())
    res2 = runner.invoke(app, ["resume", run_id, "--approve", *common])
    assert res2.exit_code == 0, res2.output
    assert "merge" in res2.output.lower()


def test_resume_unknown_run_errors(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    monkeypatch.setenv("ORCH_CHECKPOINT_DB", str(db))
    res = runner.invoke(app, ["resume", "deadbeef", "--approve",
                              "--root", str(ROOT), "--repo", str(repo)])
    assert res.exit_code != 0
    assert "no" in res.output.lower() and "deadbeef" in res.output
```

> IMPLEMENTER NOTE: the run-id extraction in the test depends on the `run` command printing `run <8-hex-id>`. Ensure `run` prints the run id near the pause message. Make the checkpoint DB path overridable via `$ORCH_CHECKPOINT_DB` (and a `--state-db` option) so `run` and `resume` share it in the test; default stays `<repo>/.orch/checkpoints.sqlite`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_resume_cli.py -v`
Expected: FAIL (resume is a `_not_implemented` stub; run doesn't report pause).

- [ ] **Step 3: Implement**

In `orchestrator/cli.py`:

- Add a helper to resolve the checkpoint db: `$ORCH_CHECKPOINT_DB` → else `repo/.orch/checkpoints.sqlite`. Pass it to `make_controller`/`DeterministicScheduler`. Add `make_controller(..., checkpoint_db=...)` passthrough in `controller.py`.
- In `run`, after `controller.run(...)`, branch on `ctx.status`:

```python
from orchestrator.runtime.state import RunStatus

if ctx.status == RunStatus.PAUSED:
    p = ctx.pending_interrupt or {}
    typer.echo(f"run {run_id}: PAUSED at gate '{p.get('step_id')}'")
    typer.echo(f"  {p.get('prompt', 'approval required')}")
    typer.echo(f"  resume with: orch resume {run_id} --approve   (or --reject)")
    return  # exit 0: paused is not an error
```

(Place this before the per-step summary, or print the summary then the pause banner — keep run_id visible.)

- Replace the `resume` stub:

```python
@app.command()
def resume(
    run_id: str = typer.Argument(...),
    approve: bool = typer.Option(False, "--approve", help="Approve the pending gate."),
    reject: bool = typer.Option(False, "--reject", help="Reject the pending gate."),
    root: Path = typer.Option(Path(".orchestrator"), "--root"),
    repo: Path = typer.Option(Path("."), "--repo"),
) -> None:
    """Resume a run paused at a HITL gate."""
    if approve == reject:
        typer.echo("error: pass exactly one of --approve / --reject.")
        raise typer.Exit(2)
    decision = "approve" if approve else "reject"
    try:
        workspace = load_workspace(root)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}")
        raise typer.Exit(1) from exc
    configure_tracing(exporter=None)
    adapter = ClaudeCodeCLIAdapter()
    controller = make_controller(Mode.declarative, workspace, adapter, repo,
                                 checkpoint_db=_checkpoint_db(repo))
    try:
        ctx = asyncio.run(controller.resume(run_id, decision))
    except KeyError as exc:
        typer.echo(f"error: no paused run '{run_id}' found.")
        raise typer.Exit(1) from exc
    if ctx.status == RunStatus.PAUSED:
        p = ctx.pending_interrupt or {}
        typer.echo(f"run {run_id}: PAUSED again at '{p.get('step_id')}' — {p.get('prompt','')}")
        typer.echo(f"  resume with: orch resume {run_id} --approve  (or --reject)")
        return
    typer.echo(f"run {run_id}: {ctx.status.value} ({len(ctx.artifacts)} steps)")
    for step_id, art in ctx.artifacts.items():
        _print_artifact(art, run_id, brief=True)
    typer.echo(f"total cost: ${ctx.total_cost_usd:.4f}")
    if any(a.is_error for a in ctx.artifacts.values()):
        raise typer.Exit(1)
```

(import `Mode`, `RunStatus`; add `_checkpoint_db(repo)` helper.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/integration/test_resume_cli.py -v`
Expected: PASS. (Requires `full.yaml` from Task 10 — if executing strictly in order, write a minimal gate-only pipeline file for this test, or reorder so Task 10's `full.yaml` exists first. Recommended: create `full.yaml` as the FIRST step of this task if not present.)

Full suite: `uv run --extra dev python -m pytest -q`.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/cli.py orchestrator/runtime/controller.py tests/integration/test_resume_cli.py
git commit -m "feat(m5): orch run reports paused gate + orch resume --approve/--reject"
```

---

## Task 10: Full-pipeline example + end-to-end smoke

**Files:**
- Create: `examples/feature-pipeline/.orchestrator/pipelines/full.yaml`
- Test: `tests/integration/test_full_pipeline.py`

- [ ] **Step 1: Create the example pipeline**

`examples/feature-pipeline/.orchestrator/pipelines/full.yaml`:

```yaml
# M5 demo: the full spec §3 shape — classify -> plan -> implement -> review (reject->implement)
# -> test -> audit -> approve (HITL gate) -> merge (PR). Run pauses at `approve`; resume to merge.
mode: declarative
inputs: { task: string }
steps:
  - id: classify
    type: task
    prompt: 'Classify {{task}} as exactly one of: bugfix | feature | refactor. Reply with JSON {"kind": "<one>"}.'
    output_schema: { kind: "enum[bugfix,feature,refactor]" }
  - id: plan
    role: planner
    needs: [classify]
    prompt: "Task: {{task}}\nKind: {{classify.output.kind}}\nWrite a short implementation plan."
  - id: implement
    role: implementer
    needs: [plan]
    prompt: "Implement this plan:\n{{plan.output}}"
    success_criteria: "true"
    max_retries: 2
  - id: review
    role: reviewer
    needs: [implement]
    prompt: 'Review this implementation:\n{{implement.output}}\nReply with JSON {"verdict": "approve|reject"}.'
    output_schema: { verdict: "enum[approve,reject]" }
    on_reject: implement
  - id: test
    role: implementer
    needs: [review]
    prompt: "Run the checks for {{task}}"
    success_criteria: "true"
  - id: audit
    role: auditor
    needs: [test]
    prompt: "Audit the change for {{task}} and summarize."
  - id: approve
    type: gate
    needs: [audit]
    require_approval: true
  - id: merge
    type: task
    needs: [approve]
    merge_strategy: sequential-rebase
```

- [ ] **Step 2: Verify it compiles**

Run: `cd examples/feature-pipeline && uv run orch compile full --root .orchestrator` (from repo root, adjust paths) — or via test below. Expected: compiles; edges show `approve -?-> merge` (conditional) and the `review -?-> implement` back-edge.

Add an assertion to `tests/integration/test_example_compiles.py` if that test enumerates pipelines, OR rely on the smoke test below.

- [ ] **Step 3: Write the end-to-end smoke test**

```python
# tests/integration/test_full_pipeline.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
GH = Path(__file__).parents[1] / "fixtures" / "fake_gh" / "fake_gh.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    return repo


async def test_full_pipeline_pause_resume_merge(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")
    monkeypatch.setenv("ORCH_GH_BIN", f"{sys.executable} {GH}")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)

    ctx = await sched.run(ws.pipelines["full"], {"task": "add a feature"}, "run-full-1")
    assert ctx.status == RunStatus.PAUSED
    assert ctx.pending_interrupt["step_id"] == "approve"
    assert "merge" not in ctx.artifacts  # merge has not run yet

    ctx2 = await sched.resume("run-full-1", "approve")
    assert ctx2.status == RunStatus.COMPLETED
    assert ctx2.artifacts["merge"].output_data["pr_url"]
    # the implement diff (feature.py) is on the integration branch
    branch = ctx2.artifacts["merge"].output_data["branch"]
    show = subprocess.run(["git", "show", f"{branch}:feature.py"], cwd=repo,
                          capture_output=True, text=True)
    assert show.returncode == 0


async def test_full_pipeline_reject_at_gate_skips_merge(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)
    await sched.run(ws.pipelines["full"], {"task": "add a feature"}, "run-full-2")
    ctx = await sched.resume("run-full-2", "reject")
    assert ctx.status == RunStatus.COMPLETED
    assert "merge" not in ctx.artifacts  # reject routed to END, merge never ran
```

> IMPLEMENTER NOTE: `full.yaml` runs `review` once → approve (default `review.ndjson`). Ensure the fake-harness `$ORCH_FAKE_STATE` counter yields approve on the single review call (the M4 default routes `review`→approve via `review.ndjson` when no numbered variant matches the count). If the review rejects-then-approves by default, the loop still terminates and reaches the gate — adjust only if the test flakes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev python -m pytest tests/integration/test_full_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add examples/feature-pipeline/.orchestrator/pipelines/full.yaml tests/integration/test_full_pipeline.py
git commit -m "feat(m5): full.yaml demo + e2e pause->resume->merge->PR smoke"
```

---

## Task 11: Manual CLI smoke + review follow-ups note

**Files:**
- Create: `docs/superpowers/notes/m5-review-followups.md`

- [ ] **Step 1: Manual smoke (real CLI, fake binaries)**

From repo root, with a throwaway git repo + bare origin + fake binaries, run `orch run full` then `orch resume <id> --approve` and confirm the pause banner, the `orch resume` hint, and the PR line print. Document the exact commands + output in the note. (This mirrors the M3/M4 manual smoke.)

- [ ] **Step 2: Write the follow-ups note**

Capture, with rationale: anything deferred (e.g. real conflict resolution beyond abort/retry, `gh`-less PR path, per-step vs run-level checkpoint GC, `orch status` reading checkpoints — M6), and confirm what M5 shipped. Mirror the structure of `docs/superpowers/notes/m4-review-followups.md`.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/notes/m5-review-followups.md
git commit -m "docs(m5): manual smoke + M5 review follow-ups"
```

---

## Final Review (after all tasks)

Dispatch a final holistic reviewer (most capable model) over the whole M5 diff against this plan and spec §6. Focus areas:
- **Resume never replays an agent** (spec §3.367): gates sit at deterministic boundaries (`approve` after `audit`; conflict gate inside `merge`). Confirm resuming re-runs only the gate/merge node, not upstream agent steps. (The checkpointer restores prior artifacts; the interrupted node re-runs from its top — verify no agent re-execution by inspecting `ctx.attempts` / span trace across a resume.)
- **Checkpoint serialization**: no "unregistered type" warnings (serde allowlist), and `RunContext` round-trips faithfully across the separate-process resume path.
- **Verdict guard + gate**: a non-approve terminal verdict blocks merge; a human `reject` at the gate routes to END (merge never runs).
- **Conflict gate**: abort path leaves no dangling integration worktree/branch; retry path is idempotent.
- **No scope leak**: agentic mode still `NotImplementedError`; no M6 (orchestrator agent, knowledge, OpenCode, `orch status`) work.

Then use **superpowers:finishing-a-development-branch** to complete (merge to `orchestrator-design`, per the established milestone workflow).

## Self-Review (performed against spec §6 + M4 follow-ups)

- **Spec coverage:** HITL gate (`interrupt`+checkpoint+resume) → Tasks 4,5,9. SQLite checkpointer → Tasks 2,4. Merge→PR (sequential-rebase) → Tasks 3,6,7. Conflict→HITL gate → Tasks 7,8. Non-approve-verdict block (M4 follow-up) → Task 7. `orch resume` CLI → Task 9. End-to-end demo → Task 10. ✓
- **Placeholder scan:** every code step carries real code; the two intentionally-flexible spots (conflict construction in Task 8, reject-verdict seeding in Task 7) carry explicit IMPLEMENTER NOTES with a required-assertion contract and a concrete fallback, not "TBD". ✓
- **Type consistency:** `RunStatus` enum (Task 1) used in scheduler/CLI (Tasks 4,5,9); `_router` rename (Task 5) reconciled with `_build` (Task 4) via an explicit note; `run_merge_step`/`open_pull_request`/`apply_diffs`/`MergeConflict` signatures match across Tasks 6,7; `output_data["pr_url"]/["branch"]/["base"]` consistent in Tasks 7,10. ✓
- **Ordering risk:** Task 9's CLI test and Task 10's `full.yaml` — Task 9 notes the dependency and says create `full.yaml` first if executing strictly in order. ✓
```
