# M4 — Review Loop + Agent-as-Judge + Verdict Routing + Test-Count Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on the cyclic `on_reject` edge. A `review` agent step produces a structured **verdict** (approve|reject); a verdict-aware router sends approve → forward and reject → back to `implement`, bounded by `max_retries`; a **test-count gate** runs alongside `success_criteria` so an agent can't "go green" by deleting tests. Demonstrated by `orch run review-demo` running `classify → plan → implement → review ⟲ → test` end-to-end (reject once, then approve), through the real compiled LangGraph `StateGraph`.

**Architecture:** Consolidate evaluation logic into `orchestrator/eval/` (spec §11): `verdict.py` (structured output parsing) + `criteria.py` (`success_criteria` runner + test-count gate). The `review` agent step parses its harness result into `output_data` (`{verdict: approve|reject}`). The `DeterministicScheduler` passes a **verdict-aware router** to the existing `wire_edges(router=...)` seam (M3 pre-wired this): for a conditional (`on_reject`) source it reads the verdict from the shared `RunContext` and the per-step execution count, routing reject → the `on_reject` target while attempts remain, else forward. `run_agent_step` gains a per-step attempt counter and a `/{attempt}` branch suffix (fixing the M3 worktree-branch-collision follow-up so cycle re-entry doesn't fail).

**Tech Stack:** Python 3.11, LangGraph 1.x (`StateGraph.ainvoke` with cyclic edges + `recursion_limit`), Pydantic v2, asyncio, OTel spans, pytest + pytest-asyncio. Builds on M1–M3.

---

## Context for the implementer

You are extending a working M1–M3 codebase (128 tests passing at baseline). M3 shipped: the `DeterministicScheduler` executes the compiled `StateGraph` end-to-end for **linear** pipelines (`classify task → plan → implement`), with `{{...}}` dataflow templating and a `success_criteria`/retry inner loop. M4 turns on the **cyclic** review loop.

Key existing facts you MUST respect:

- **Package manager is `uv`. There is NO system pip.** Run everything via `uv run --extra dev ...` (pytest) / `uv run orch ...` (CLI) / `uv run --extra dev ruff check .` (lint). **Run ruff after every task** — keep it clean.
- TDD throughout: failing test first → confirm fail → implement → confirm pass → full suite green + ruff clean → commit. One commit per task.
- Tests run against the **fake harness** (`tests/fixtures/fake_harness/fake_harness.py`, zero API cost), driven via `ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])` or `$ORCH_CLAUDE_BIN`. It routes scripts by prompt keyword (`$ORCH_FAKE_SCRIPT_DIR`) or an explicit file (`$ORCH_FAKE_SCRIPT`), logs invocations (`$ORCH_FAKE_CALLS`), and supports `$ORCH_FAKE_TOUCH`/`$ORCH_FAKE_EXIT`/`$ORCH_FAKE_STDERR_BYTES`. M4 adds `$ORCH_FAKE_STATE` (per-keyword counter → numbered script variants) and `$ORCH_FAKE_DELETE` (delete a file, to test the test-count gate).
- Reference syntax is `{{ ... }}` (locked in M3).

Relevant existing code (read before the tasks that touch them):
- `orchestrator/runtime/executors.py` — `_render_prompt`, `_capture_diff`, `_run_success_criteria`, `_drive_harness` (returns an `_Aggregate` with `.output`, `.result_text`, `.cost_usd`, `.tokens`, `.is_error`), `run_agent_step` (worktree + success_criteria/retry loop), `_parse_task_output` + `_ENUM_RE`, `run_task_step`.
- `orchestrator/runtime/scheduler.py` — `DeterministicScheduler` (`_make_node`, `_build` calls `wire_edges(builder, ir)`, `run` does `ainvoke({"ctx": ctx})`).
- `orchestrator/runtime/state.py` — `Artifact` (has `output_data`), `RunContext` (`record`), `GraphState`.
- `orchestrator/compile/compiler.py` — `wire_edges(builder, ir, *, router=None)` (router is `(source, targets) -> route_fn`; forward-only default picks `targets[0]`; the IR emits forward `needs` edges BEFORE `on_reject` back-edges, so `targets[0]` is the forward successor).
- `orchestrator/compile/ir.py` — `build_ir` (on_reject sources get all-conditional outgoing edges; forward edges precede reject edges).
- `orchestrator/config/schemas.py` — `Step` (`on_reject`, `max_retries`, `output_schema`, `success_criteria`, `role`, `type`), `StepType`.
- `examples/feature-pipeline/.orchestrator/` — roles `reviewer` (read-only), `implementer` (edit); `feature.yaml` has the full spine incl. `review (on_reject: implement)`, plus `audit`/`approve` gate/`merge` (those are M5 — M4's demo stops at `test`).

**Scope boundary for M4 (do NOT build — later milestones):**
- `gate`/HITL (`interrupt`/resume), SQLite checkpointer, merge→PR, conflict gate → **M5**.
- Orchestrator agent / message bus / knowledge injection / OpenCode adapter / `orch status` → **M6**.
- Parallel/best-of-n + state reducers, `AgenticSupervisor` → deferred.
- Cross-step **filesystem** change propagation (each agent step runs in a fresh worktree off HEAD; implement's edits are captured as `diff`/`output` but NOT applied to HEAD, so `test`/`review` see implement's work only via the injected `{{implement.output}}` text, not the filesystem). This is an isolation-model limitation resolved by merge (M5). M4's review is agent-as-judge over the injected output text — correct for the MVP.

M4's demo is a new linear-plus-one-cycle pipeline `review-demo` (`classify → plan → implement → review ⟲ → test`). The full `feature.yaml` still cannot fully run (its `approve` gate is M5).

---

## File structure

| File | Responsibility |
|------|----------------|
| `orchestrator/eval/__init__.py` | **New.** Re-export verdict + criteria helpers. |
| `orchestrator/eval/verdict.py` | **New.** `parse_output(output, output_schema)` (moved/generalized from executors' `_parse_task_output`) + `Verdict` constants. |
| `orchestrator/eval/criteria.py` | **New.** `run_success_criteria(criteria, cwd)` (moved from executors) + `count_tests(root)` + `test_count_regressed(before, after)`. |
| `orchestrator/runtime/state.py` | **Modify.** Add `RunContext.attempts: dict[str,int]`. |
| `orchestrator/runtime/executors.py` | **Modify.** Import from `eval`; per-step attempt counter + `/{attempt}` branch suffix; parse `output_data` (from the harness result) in `run_agent_step`; run the test-count gate alongside `success_criteria`. |
| `orchestrator/runtime/scheduler.py` | **Modify.** Build + pass a verdict-aware router to `wire_edges`; set `recursion_limit` on `ainvoke`. |
| `examples/feature-pipeline/.orchestrator/pipelines/review-demo.yaml` | **New.** `classify → plan → implement → review ⟲ → test` demo. |
| `examples/feature-pipeline/.orchestrator/roles/reviewer.yaml` | (exists) read-only reviewer — no change expected. |
| `tests/fixtures/fake_harness/fake_harness.py` | **Modify.** `$ORCH_FAKE_STATE` (per-keyword counter → `K.<n>.ndjson` variants; add `review` keyword) + `$ORCH_FAKE_DELETE`. |
| `tests/fixtures/fake_harness/scripts/review.ndjson` · `review.1.ndjson` · `review.2.ndjson` | **New.** Verdict scripts (fallback approve; attempt 1 reject; attempt 2 approve). |
| `tests/unit/test_verdict.py` · `test_criteria.py` · `tests/integration/test_review_loop.py` · `test_test_count_gate.py` | **New** tests. |
| `tests/unit/test_fake_harness.py` · `tests/integration/test_agent_step.py` · `test_task_step.py` | **Modify** (new fake-harness behaviors; branch-suffix assertion; imports from `eval`). |

---

## M4 design decisions (read before starting)

1. **Verdict comes from the harness *result*, not the chat text.** `run_agent_step` parses `output_data` from the final `result` text (`_Aggregate.result_text`), not the concatenated `MessageChunk` text (which stays `artifact.output` for display). So a reviewer can narrate ("Reviewing…") in chat while the machine-readable verdict lives in the result. Parsing is active only when the step declares an `output_schema`.
2. **Per-step attempt counter in `RunContext.attempts`.** `run_agent_step` increments `ctx.attempts[step.id]` at the start of each execution and uses it as a `/{attempt}` branch suffix (`orch/{run_id}/{step.id}/{attempt}`) — fixing the M3 worktree-branch-collision follow-up so re-entering `implement` on the cycle creates a distinct worktree/branch. The verdict router reads `ctx.attempts[reject_target]` to bound the loop.
3. **Verdict-aware router via the existing `wire_edges(router=...)` seam.** The scheduler passes a router. For a conditional (`on_reject`) source it returns a `route_fn(state)` that reads the source step's verdict and: `approve` → forward target; `reject` AND `attempts[reject_target] <= reject_target.max_retries` → reject target (the back-edge); otherwise (approve, exhausted, or missing/invalid verdict) → forward target. `to_state_graph` (compile-time) keeps the forward-only default — unchanged. **Loop termination** is guaranteed by the `max_retries` bound; `recursion_limit=100` on `ainvoke` is a defensive cap, not the real bound.
4. **`max_retries` is shared by both loops.** The same `Step.max_retries` bounds the inner `success_criteria` retry (M3, within one execution) and the outer review-reject loop (M4, re-executions). Acceptable MVP overload — documented.
5. **Test-count gate runs alongside `success_criteria`** (spec §6). When a step has `success_criteria`, capture the test-function count in the worktree *before* the harness drive (baseline = fresh checkout) and *after*; if it regressed (fewer tests), fail the step (`is_error=True`) even if `success_criteria` passed. `count_tests` is a heuristic regex over `test_*.py`/`*_test.py` files — MVP, language-specific to pytest-style. Steps without `success_criteria` skip the gate.
6. **Evaluation logic lives in `orchestrator/eval/`** (spec §11). M4 moves `_parse_task_output` → `eval/verdict.py::parse_output` and `_run_success_criteria` → `eval/criteria.py::run_success_criteria`, and adds the test-count gate there. Behavior-preserving for the moved functions (existing task/agent tests stay green).
7. **Fake-harness verdict variation via numbered script variants.** With `$ORCH_FAKE_STATE` set, the harness keeps a per-keyword invocation counter and prefers `<keyword>.<n>.ndjson` (e.g. `review.1.ndjson` reject, `review.2.ndjson` approve), falling back to `<keyword>.ndjson`. Without `$ORCH_FAKE_STATE`, behavior is exactly as M3 (back-compat). The `review` keyword is added to routing.

---

## Task 1: `orchestrator/eval/` — verdict parsing + criteria (consolidation)

**Files:**
- Create: `orchestrator/eval/__init__.py`, `orchestrator/eval/verdict.py`, `orchestrator/eval/criteria.py`
- Modify: `orchestrator/runtime/executors.py` (import from `eval`; drop the moved code)
- Test: `tests/unit/test_verdict.py`, `tests/unit/test_criteria.py`

Move `_parse_task_output` → `eval/verdict.py::parse_output` and `_run_success_criteria` → `eval/criteria.py::run_success_criteria`; add `count_tests` + `test_count_regressed` (used in Task 4). Behavior-preserving for the moved logic.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_verdict.py`:

```python
from orchestrator.eval.verdict import Verdict, parse_output


def test_no_schema_returns_none():
    assert parse_output("anything", None) == (None, False)


def test_enum_field_from_json():
    data, err = parse_output('{"kind": "feature"}', {"kind": "enum[bugfix,feature,refactor]"})
    assert data == {"kind": "feature"} and err is False


def test_enum_bare_value_single_field():
    data, err = parse_output("approve", {"verdict": "enum[approve,reject]"})
    assert data == {"verdict": "approve"} and err is False


def test_enum_invalid_value_is_error():
    data, err = parse_output('{"verdict": "maybe"}', {"verdict": "enum[approve,reject]"})
    assert data is None and err is True


def test_verdict_constants():
    assert Verdict.APPROVE == "approve"
    assert Verdict.REJECT == "reject"
```

Create `tests/unit/test_criteria.py`:

```python
import subprocess
from pathlib import Path

from orchestrator.eval.criteria import (
    count_tests,
    run_success_criteria,
    test_count_regressed,
)


def test_run_success_criteria_ok(tmp_path):
    ok, out = run_success_criteria("echo hi && true", tmp_path)
    assert ok is True
    assert "hi" in out


def test_run_success_criteria_fail(tmp_path):
    ok, out = run_success_criteria("echo boom >&2; false", tmp_path)
    assert ok is False
    assert "boom" in out


def test_count_tests_counts_functions(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_one():\n    assert True\n\nasync def test_two():\n    assert True\n"
    )
    (tmp_path / "tests" / "helpers_b.py").write_text("def not_a_test():\n    pass\n")
    assert count_tests(tmp_path) == 2


def test_count_tests_ignores_git_dir(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "test_x.py").write_text("def test_x():\n    pass\n")
    assert count_tests(tmp_path) == 1


def test_test_count_regressed():
    assert test_count_regressed(3, 2) is True
    assert test_count_regressed(2, 2) is False
    assert test_count_regressed(2, 5) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/unit/test_verdict.py tests/unit/test_criteria.py -v`
Expected: FAIL — `orchestrator.eval` does not exist.

- [ ] **Step 3: Create the eval package**

Create `orchestrator/eval/__init__.py`:

```python
"""Evaluation layer: verdicts + success criteria + test-count gate (spec §6, §9)."""

from orchestrator.eval.criteria import (
    count_tests,
    run_success_criteria,
    test_count_regressed,
)
from orchestrator.eval.verdict import Verdict, parse_output

__all__ = [
    "parse_output",
    "Verdict",
    "run_success_criteria",
    "count_tests",
    "test_count_regressed",
]
```

Create `orchestrator/eval/verdict.py`:

```python
"""Structured output parsing for task/review steps (spec §6)."""

from __future__ import annotations

import json
import re

_ENUM_RE = re.compile(r"enum\[([^\]]*)\]")


class Verdict:
    """Agent-as-judge verdict values (spec §6 review loop)."""

    APPROVE = "approve"
    REJECT = "reject"


def parse_output(output: str, output_schema: dict | None) -> tuple[dict | None, bool]:
    """Parse a step's textual output into structured output_data.

    If output_schema declares enum field(s), accept either a JSON object
    {field: value} or a bare value (single-field schema), and validate enum
    membership. Returns (output_data, is_error). No schema -> (None, False).
    """
    if not output_schema:
        return None, False

    data: dict | None = None
    try:
        loaded = json.loads(output)
        if isinstance(loaded, dict):
            data = loaded
    except (json.JSONDecodeError, TypeError):
        data = None

    for field_name, spec in output_schema.items():
        allowed = None
        if isinstance(spec, str):
            m = _ENUM_RE.fullmatch(spec.strip())
            if m:
                allowed = [v.strip() for v in m.group(1).split(",") if v.strip()]
        if allowed is None:
            continue
        value = None
        if data is not None and field_name in data:
            value = str(data[field_name]).strip()
        elif len(output_schema) == 1:
            value = output.strip()
        if value not in allowed:
            return None, True
        data = {**(data or {}), field_name: value}

    return data, False
```

Create `orchestrator/eval/criteria.py`:

```python
"""success_criteria runner + test-count gate (spec §6, §9)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# pytest-style test functions: `def test_...` / `async def test_...`.
_TEST_FN = re.compile(r"^[ \t]*(async[ \t]+)?def[ \t]+test\w*[ \t]*\(", re.MULTILINE)
_SKIP_DIRS = {".git", ".worktrees", ".venv", "__pycache__", "node_modules"}


def run_success_criteria(criteria: str, cwd: Path) -> tuple[bool, str]:
    """Run the success_criteria shell command in `cwd`. Returns (ok, combined output)."""
    proc = subprocess.run(criteria, cwd=cwd, shell=True, capture_output=True, text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def count_tests(root: Path) -> int:
    """Count pytest-style test functions under `root` (heuristic, MVP)."""
    root = Path(root)
    total = 0
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        name = path.name
        if not (name.startswith("test_") or name.endswith("_test.py")):
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        total += len(_TEST_FN.findall(text))
    return total


def test_count_regressed(before: int, after: int) -> bool:
    """True when the post-edit test count is lower than the pre-edit baseline."""
    return after < before
```

- [ ] **Step 4: Rewire `executors.py` to import from `eval`**

In `orchestrator/runtime/executors.py`:
- Remove `import json` and `import re` (now only needed in `eval`), and remove `_ENUM_RE`, `_parse_task_output`, and `_run_success_criteria`.
- Add import: `from orchestrator.eval.verdict import parse_output` and `from orchestrator.eval.criteria import run_success_criteria`.
- In `run_agent_step`, change the `_run_success_criteria(...)` call to `run_success_criteria(...)`.
- In `run_task_step`, change `_parse_task_output(output, step.output_schema)` to `parse_output(output, step.output_schema)`.

(Keep `import subprocess` — `_capture_diff` still uses it.)

- [ ] **Step 5: Run the tests + full suite + ruff**

Run: `uv run --extra dev python -m pytest tests/unit/test_verdict.py tests/unit/test_criteria.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green (task/agent tests still pass — behavior preserved), lint clean.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/eval/ orchestrator/runtime/executors.py tests/unit/test_verdict.py tests/unit/test_criteria.py
git commit -m "feat(m4): orchestrator/eval — verdict parsing + criteria/test-count helpers"
```

---

## Task 2: Per-step attempt counter + `/{attempt}` branch suffix

**Files:**
- Modify: `orchestrator/runtime/state.py` (add `RunContext.attempts`)
- Modify: `orchestrator/runtime/executors.py` (`run_agent_step` increments + suffixes the branch)
- Test: `tests/integration/test_agent_step.py` (add a re-entry test; fix the existing branch assertion)

Fixes the M3 follow-up: re-entering a step on the reject cycle must not collide on the worktree branch name.

- [ ] **Step 1: Add `attempts` to `RunContext`**

In `orchestrator/runtime/state.py`, add the field to `RunContext`:

```python
@dataclass
class RunContext:
    run_id: str
    inputs: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    attempts: dict[str, int] = field(default_factory=dict)

    def record(self, artifact: Artifact) -> None:
        self.artifacts[artifact.step_id] = artifact
        self.total_cost_usd += artifact.cost_usd
```

- [ ] **Step 2: Write the failing test + fix the existing branch assertion**

In `tests/integration/test_agent_step.py`:

(a) The existing `test_agent_step_captures_diff_when_harness_edits` asserts `artifact.branch.endswith("implement")`. The branch now ends with `/{attempt}`. Change that assertion to:

```python
    assert "/implement/" in artifact.branch  # branch now carries an attempt suffix
```

(b) Add a re-entry test proving two executions of the same step get distinct branches (no `WorktreeError`):

```python
async def test_repeated_agent_step_uses_distinct_branches(tmp_path, monkeypatch):
    import sys

    from orchestrator.config.schemas import Step
    from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
    from orchestrator.runtime.executors import run_agent_step
    from orchestrator.runtime.state import RunContext

    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({"id": "implement", "role": "implementer", "prompt": "do the work"})
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="reentry", inputs={"task": "t"})

    a1 = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)
    a2 = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)

    assert a1.branch != a2.branch
    assert a1.branch.endswith("/1")
    assert a2.branch.endswith("/2")
    assert ctx.attempts["implement"] == 2
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: FAIL — branch has no suffix yet / re-entry collides or counts wrong.

- [ ] **Step 4: Increment attempts + suffix the branch in `run_agent_step`**

In `orchestrator/runtime/executors.py`, in `run_agent_step`, replace the branch computation:

```python
    role = workspace.roles[step.role]
    caps = resolve_capabilities(role, workspace)
    attempt_no = ctx.attempts.get(step.id, 0) + 1
    ctx.attempts[step.id] = attempt_no
    branch = f"orch/{ctx.run_id}/{step.id}/{attempt_no}"
```

(The rest of `run_agent_step` is unchanged for this task.)

- [ ] **Step 5: Run the tests + full suite + ruff**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green, lint clean. (If the CLI smoke/test asserts a branch format, confirm it still holds — `test_run_cli` only checks substrings like `"implement"`, which still appear.)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/runtime/state.py orchestrator/runtime/executors.py tests/integration/test_agent_step.py
git commit -m "fix(m4): per-step attempt counter + /{attempt} branch suffix (cycle re-entry safe)"
```

---

## Task 3: Agent-step verdict (`output_data`) parsing

**Files:**
- Modify: `orchestrator/runtime/executors.py` (`run_agent_step` parses `output_data` from the result)
- Test: `tests/integration/test_agent_step.py` (add a verdict test)

A `review` agent step produces a structured verdict. `run_agent_step` parses `output_data` from the harness **result** (not the chat text) when `output_schema` is set.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_agent_step.py`:

```python
async def test_agent_step_parses_verdict_from_result(tmp_path, monkeypatch):
    import sys

    from orchestrator.config.schemas import Step
    from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
    from orchestrator.runtime.executors import run_agent_step
    from orchestrator.runtime.state import RunContext

    # A canned script whose RESULT is the verdict JSON, with chat text too.
    script = tmp_path / "verdict.ndjson"
    script.write_text(
        '{"type":"system","subtype":"init","session_id":"v1","tools":[],"cwd":"."}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Reviewing."}]}}\n'
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"{\\"verdict\\": \\"reject\\"}","total_cost_usd":0.005,'
        '"usage":{"input_tokens":10,"output_tokens":5},"session_id":"v1"}\n'
    )
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(script))
    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "review", "role": "reviewer", "prompt": "Review {{task}}",
        "output_schema": {"verdict": "enum[approve,reject]"},
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="rv", inputs={"task": "t"})

    art = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)

    assert art.output_data == {"verdict": "reject"}
    assert art.output == "Reviewing."          # chat text, not the result JSON
    assert art.is_error is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py::test_agent_step_parses_verdict_from_result -v`
Expected: FAIL — `output_data` is None for agent steps.

- [ ] **Step 3: Parse `output_data` in `run_agent_step`**

In `orchestrator/runtime/executors.py`, ensure `parse_output` is imported (Task 1 added it). In `run_agent_step`, after the retry loop and before building the `Artifact`, parse the verdict from the **last drive's result text** (`agg` is bound to the final attempt after the loop):

```python
            diff = _capture_diff(worktree.path)
            output_data, parse_error = parse_output(agg.result_text, step.output_schema)
            if parse_error:
                is_error = True
            step_span.set_attribute("step.is_error", is_error)

        artifact = Artifact(
            step_id=step.id,
            output=output,
            diff=diff,
            branch=branch,
            cost_usd=total_cost,
            tokens=total_tokens,
            is_error=is_error,
            output_data=output_data,
        )
```

(Note: `output` stays `agg.output` = chat text; the verdict is parsed from `agg.result_text`. A step with no `output_schema` gets `output_data=None`.)

- [ ] **Step 4: Run the test + full suite + ruff**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green, lint clean.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/runtime/executors.py tests/integration/test_agent_step.py
git commit -m "feat(m4): agent steps parse output_data (verdict) from the harness result"
```

---

## Task 4: Test-count gate

**Files:**
- Modify: `orchestrator/runtime/executors.py` (`run_agent_step` runs the gate alongside `success_criteria`)
- Modify: `tests/fixtures/fake_harness/fake_harness.py` (`$ORCH_FAKE_DELETE`)
- Test: `tests/integration/test_test_count_gate.py`; `tests/unit/test_fake_harness.py` (add `$ORCH_FAKE_DELETE` test)

When a step has `success_criteria`, fail it if the agent reduced the test count (spec §6: can't "go green" by deleting assertions).

- [ ] **Step 1: Add `$ORCH_FAKE_DELETE` to the fake harness + its unit test**

In `tests/fixtures/fake_harness/fake_harness.py`, alongside the `$ORCH_FAKE_TOUCH` handling, add:

```python
    delete = os.environ.get("ORCH_FAKE_DELETE")
    if delete:
        p = Path(delete)
        if p.exists():
            p.unlink()
```

Add to `tests/unit/test_fake_harness.py`:

```python
def test_fake_delete_removes_file(tmp_path, monkeypatch):
    import os

    victim = tmp_path / "doomed.txt"
    victim.write_text("x")
    env = {**os.environ, "ORCH_FAKE_SCRIPT": str(PLAN), "ORCH_FAKE_DELETE": str(victim)}
    subprocess.run(
        [sys.executable, str(FAKE), "-p", "hi", "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    assert not victim.exists()
```

- [ ] **Step 2: Write the failing gate integration test**

Create `tests/integration/test_test_count_gate.py`:

```python
import subprocess
import sys
from pathlib import Path

from orchestrator.config.schemas import Step
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.config.loader import load_workspace
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _repo_with_tests(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)

    def git(*a):
        subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@e.com")
    git("config", "user.name", "T")
    git("config", "commit.gpgsign", "false")
    (path / "test_sample.py").write_text(
        "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n"
    )
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return path


def _step():
    return Step.model_validate({
        "id": "implement", "role": "implementer", "prompt": "work",
        "success_criteria": "true",  # criteria itself passes
    })


async def test_gate_fails_when_tests_deleted(tmp_path, monkeypatch):
    configure_tracing(exporter=InMemorySpanExporter())
    repo = _repo_with_tests(tmp_path / "repo")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    # The harness deletes the test file inside its worktree cwd.
    monkeypatch.setenv("ORCH_FAKE_DELETE", "test_sample.py")
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="gate1", inputs={"task": "t"})

    art = await run_agent_step(ws, ws.pipelines["feature"], _step(), ctx, repo=repo, adapter=adapter)
    assert art.is_error is True
    assert "test-count" in art.output.lower()


async def test_gate_passes_when_tests_intact(tmp_path, monkeypatch):
    configure_tracing(exporter=InMemorySpanExporter())
    repo = _repo_with_tests(tmp_path / "repo")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.delenv("ORCH_FAKE_DELETE", raising=False)
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="gate2", inputs={"task": "t"})

    art = await run_agent_step(ws, ws.pipelines["feature"], _step(), ctx, repo=repo, adapter=adapter)
    assert art.is_error is False
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_test_count_gate.py tests/unit/test_fake_harness.py -v`
Expected: FAIL — gate not implemented (deleted-tests run reports `is_error=False`).

- [ ] **Step 4: Wire the gate into `run_agent_step`**

In `orchestrator/runtime/executors.py`, import the helpers (Task 1): `from orchestrator.eval.criteria import count_tests, run_success_criteria, test_count_regressed`.

In `run_agent_step`, capture the baseline right after creating the worktree, and apply the gate after the retry loop when `success_criteria` is set:

```python
    worktree = create_worktree(Path(repo), branch=branch)
    baseline_tests = count_tests(worktree.path)
    try:
        with tracer.start_as_current_span(SPAN_STEP) as step_span:
            ...
            # (retry loop unchanged) ...

            diff = _capture_diff(worktree.path)
            # Test-count gate (spec §6): can't go green by deleting tests.
            if step.success_criteria:
                after_tests = count_tests(worktree.path)
                if test_count_regressed(baseline_tests, after_tests):
                    is_error = True
                    output = (
                        f"{output}\n[test-count gate: tests dropped "
                        f"{baseline_tests}->{after_tests}]"
                    )
                step_span.set_attribute("test_count.before", baseline_tests)
                step_span.set_attribute("test_count.after", after_tests)

            output_data, parse_error = parse_output(agg.result_text, step.output_schema)
            if parse_error:
                is_error = True
            step_span.set_attribute("step.is_error", is_error)
        ...
```

(Place the gate before the `output_data` parse from Task 3, both inside the `with step_span` block, before building the `Artifact`.)

- [ ] **Step 5: Run the tests + full suite + ruff**

Run: `uv run --extra dev python -m pytest tests/integration/test_test_count_gate.py tests/unit/test_fake_harness.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green, lint clean.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/runtime/executors.py tests/fixtures/fake_harness/fake_harness.py tests/integration/test_test_count_gate.py tests/unit/test_fake_harness.py
git commit -m "feat(m4): test-count gate (fail if an agent deletes tests under success_criteria)"
```

---

## Task 5: Verdict-aware router + cyclic execution

**Files:**
- Modify: `orchestrator/runtime/scheduler.py` (verdict router + `recursion_limit`)
- Modify: `tests/fixtures/fake_harness/fake_harness.py` (`$ORCH_FAKE_STATE` + `review` keyword + numbered variants)
- Create: `tests/fixtures/fake_harness/scripts/review.ndjson`, `review.1.ndjson`, `review.2.ndjson`
- Test: `tests/integration/test_review_loop.py`; `tests/unit/test_fake_harness.py` (numbered-variant test)

The cyclic core: route `review`'s verdict (`approve` → forward, `reject` → back to `implement`) bounded by `max_retries`.

- [ ] **Step 1: Add numbered-variant routing + `review` keyword to the fake harness**

In `tests/fixtures/fake_harness/fake_harness.py`, replace the script-dir selection block with keyword routing for `classify`/`review`, plus `$ORCH_FAKE_STATE` numbered variants:

```python
    # Script selection: explicit file wins; else route within a dir by prompt keyword.
    script_env = os.environ.get("ORCH_FAKE_SCRIPT")
    script_dir = os.environ.get("ORCH_FAKE_SCRIPT_DIR")
    if script_env:
        script = Path(script_env)
    elif script_dir:
        pl = prompt.lower()
        if "classify" in pl:
            keyword = "classify"
        elif "review" in pl:
            keyword = "review"
        else:
            keyword = "default"
        script = Path(script_dir) / f"{keyword}.ndjson"
        state_file = os.environ.get("ORCH_FAKE_STATE")
        if state_file and keyword != "default":
            import json as _json

            try:
                state = _json.loads(Path(state_file).read_text())
            except (OSError, ValueError):
                state = {}
            n = int(state.get(keyword, 0)) + 1
            state[keyword] = n
            Path(state_file).write_text(_json.dumps(state))
            numbered = Path(script_dir) / f"{keyword}.{n}.ndjson"
            if numbered.exists():
                script = numbered
        if not script.exists():
            script = Path(script_dir) / "default.ndjson"
    else:
        script = DEFAULT_SCRIPT
```

Add to `tests/unit/test_fake_harness.py`:

```python
def test_state_selects_numbered_review_variant(tmp_path, monkeypatch):
    import os

    state = tmp_path / "state.json"
    env = {
        **os.environ,
        "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR),
        "ORCH_FAKE_STATE": str(state),
    }

    def run():
        return subprocess.run(
            [sys.executable, str(FAKE), "-p", "Please review this", "--output-format", "stream-json"],
            env=env, capture_output=True, text=True,
        ).stdout

    first = run()   # review.1.ndjson -> reject
    second = run()  # review.2.ndjson -> approve
    assert "reject" in first
    assert "approve" in second
```

- [ ] **Step 2: Create the review verdict scripts**

Create `tests/fixtures/fake_harness/scripts/review.1.ndjson`:

```
{"type":"system","subtype":"init","session_id":"rev-1","tools":[],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Reviewing the implementation."}]}}
{"type":"result","subtype":"success","is_error":false,"result":"{\"verdict\": \"reject\"}","total_cost_usd":0.005,"usage":{"input_tokens":30,"output_tokens":10},"session_id":"rev-1"}
```

Create `tests/fixtures/fake_harness/scripts/review.2.ndjson`:

```
{"type":"system","subtype":"init","session_id":"rev-2","tools":[],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Looks good now."}]}}
{"type":"result","subtype":"success","is_error":false,"result":"{\"verdict\": \"approve\"}","total_cost_usd":0.005,"usage":{"input_tokens":30,"output_tokens":10},"session_id":"rev-2"}
```

Create `tests/fixtures/fake_harness/scripts/review.ndjson` (fallback = approve):

```
{"type":"system","subtype":"init","session_id":"rev-0","tools":[],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Reviewing."}]}}
{"type":"result","subtype":"success","is_error":false,"result":"{\"verdict\": \"approve\"}","total_cost_usd":0.005,"usage":{"input_tokens":30,"output_tokens":10},"session_id":"rev-0"}
```

- [ ] **Step 3: Write the failing cyclic-execution test**

Create `tests/integration/test_review_loop.py`:

```python
import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Mode, Pipeline
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.scheduler import DeterministicScheduler
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _loop_pipeline() -> Pipeline:
    # implement -> review (reject->implement) -> test. Minimal cycle.
    return Pipeline.model_validate({
        "name": "loop",
        "mode": "declarative",
        "inputs": {"task": "string"},
        "steps": [
            {"id": "implement", "role": "implementer", "prompt": "Implement {{task}}",
             "success_criteria": "true", "max_retries": 2},
            {"id": "review", "role": "reviewer", "needs": ["implement"],
             "prompt": "Please review {{implement.output}}",
             "output_schema": {"verdict": "enum[approve,reject]"},
             "on_reject": "implement"},
            {"id": "test", "role": "implementer", "needs": ["review"],
             "prompt": "Run the checks", "success_criteria": "true"},
        ],
    })


async def test_review_loop_rejects_then_approves(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state.json"))
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("ORCH_FAKE_CALLS", str(calls))
    configure_tracing(exporter=InMemorySpanExporter())

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    scheduler = DeterministicScheduler(ws, adapter, repo)

    ctx = await scheduler.run(_loop_pipeline(), {"task": "add a widget"}, run_id="loop1")

    # implement ran twice (initial + one reject), review ran twice, test ran once.
    assert ctx.attempts["implement"] == 2
    assert ctx.attempts["review"] == 2
    assert "test" in ctx.artifacts
    assert ctx.artifacts["review"].output_data == {"verdict": "approve"}  # last verdict
    assert ctx.artifacts["test"].is_error is False
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_review_loop.py -v`
Expected: FAIL — the forward-only router always goes to `test`; `implement` never re-runs (`attempts["implement"] == 1`).

- [ ] **Step 5: Implement the verdict router in the scheduler**

In `orchestrator/runtime/scheduler.py`, add `END` import and a verdict router; pass it to `wire_edges`; set `recursion_limit`. Update imports and `_build`/`run`:

```python
from langgraph.graph import END, StateGraph

from orchestrator.eval.verdict import Verdict
```

Add a router builder method and use it:

```python
    def _verdict_router(self, pipeline: Pipeline):
        by_id = {s.id: s for s in pipeline.steps}

        def router(source: str, targets: list[str]):
            reject_target = by_id[source].on_reject
            forward = [t for t in targets if t != reject_target]

            def route_fn(state: GraphState) -> str:
                ctx = state["ctx"]
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

    def _build(self, pipeline: Pipeline):
        ir = build_ir(pipeline)
        by_id = {s.id: s for s in pipeline.steps}
        builder = StateGraph(GraphState)
        for node_id in ir.nodes:
            builder.add_node(node_id, self._make_node(pipeline, by_id[node_id]))
        wire_edges(builder, ir, router=self._verdict_router(pipeline))
        return builder.compile()
```

And in `run`, bound the cyclic invocation with a defensive recursion limit (the real bound is `max_retries`):

```python
            await graph.ainvoke({"ctx": ctx}, {"recursion_limit": 100})
```

- [ ] **Step 6: Run the tests + full suite + ruff**

Run: `uv run --extra dev python -m pytest tests/integration/test_review_loop.py tests/unit/test_fake_harness.py -v`
Expected: PASS — `implement` re-runs once on reject, then `review` approves, then `test` runs.

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green (the M3 `triage` scheduler test — no conditional edges — is unaffected since the router is only invoked for conditional sources), lint clean. Run the suite twice to confirm the cyclic test is deterministic.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/runtime/scheduler.py tests/fixtures/fake_harness/ tests/integration/test_review_loop.py tests/unit/test_fake_harness.py
git commit -m "feat(m4): verdict-aware router executes the bounded on_reject review loop"
```

---

## Task 6: Demo pipeline + CLI run + verification

**Files:**
- Create: `examples/feature-pipeline/.orchestrator/pipelines/review-demo.yaml`
- Test: `tests/integration/test_run_cli.py` (add a review-demo run test)

Add the canonical M4 demo pipeline and confirm it runs through the CLI (the CLI full-run path from M3 already uses the controller/scheduler — which now has the verdict router — so no CLI code change is needed).

- [ ] **Step 1: Create the demo pipeline**

Create `examples/feature-pipeline/.orchestrator/pipelines/review-demo.yaml`:

```yaml
# M4 demo: classify (task) -> plan -> implement -> review (reject->implement) -> test.
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
    prompt: 'Please review this implementation:\n{{implement.output}}\nReply with JSON {"verdict": "approve|reject"}.'
    output_schema: { verdict: "enum[approve,reject]" }
    on_reject: implement
  - id: test
    role: implementer
    needs: [review]
    prompt: "Run the checks for {{task}}"
    success_criteria: "true"
```

Confirm it compiles (the cyclic on_reject must validate):

Run: `uv run --extra dev python -c "from orchestrator.config.loader import load_workspace; from orchestrator.compile.compiler import compile_pipeline; ws=load_workspace('examples/feature-pipeline/.orchestrator'); r=compile_pipeline(ws,'review-demo'); print(r.ok, r.errors)"`
Expected: `True []`

- [ ] **Step 2: Write the failing CLI test**

Add to `tests/integration/test_run_cli.py`:

```python
def test_run_review_demo_loops_then_completes(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state.json"))

    result = runner.invoke(
        app,
        ["run", "review-demo", "--task", "add a widget",
         "--root", str(dest), "--repo", str(repo)],
    )
    assert result.exit_code == 0, result.output
    # review approved on the 2nd pass; verdict surfaced; test ran.
    assert "review" in result.output
    assert "approve" in result.output
    assert "test" in result.output
```

- [ ] **Step 3: Run to verify failure (then pass — no CLI change expected)**

Run: `uv run --extra dev python -m pytest tests/integration/test_run_cli.py::test_run_review_demo_loops_then_completes -v`
Expected: initially FAIL only if `review-demo.yaml` is missing or the verdict scripts/state aren't wired. With Tasks 1–5 done and the pipeline created, this should PASS without touching `cli.py`. If it fails for a real reason (e.g., the printed output doesn't include the verdict), inspect — the `_print_artifact` helper already prints `output_data`, so `approve` should appear via `review`'s `output_data`. Do NOT add CLI code unless a genuine gap exists; if one does, fix minimally and note it.

- [ ] **Step 4: Full verification**

Run: `uv run --extra dev python -m pytest`
Expected: ALL green (M1–M4).

Run: `uv run --extra dev ruff check .`
Expected: clean.

Manual smoke (the headline M4 capability — the review loop end-to-end):

```bash
PY=$(uv run python -c 'import sys; print(sys.executable)')
ORCH_CLAUDE_BIN="$PY tests/fixtures/fake_harness/fake_harness.py" \
ORCH_FAKE_SCRIPT_DIR="tests/fixtures/fake_harness/scripts" \
ORCH_FAKE_STATE="$(mktemp)" \
uv run orch run review-demo --task "add a widget" --root examples/feature-pipeline/.orchestrator --repo .
```

Expected: prints `run <id>: pipeline 'review-demo' (5 steps)` with OK lines for classify/plan/implement/review/test; `review` shows `output_data: {'verdict': 'approve'}`; a total cost line. Then `git status` shows nothing stray (worktrees auto-removed; `.worktrees/` gitignored).

- [ ] **Step 5: Commit**

```bash
git add examples/feature-pipeline/.orchestrator/pipelines/review-demo.yaml tests/integration/test_run_cli.py
git commit -m "feat(m4): review-demo pipeline + CLI review-loop run end-to-end"
```

---

## Self-review (against spec §6, §12 M4 + M3 follow-ups)

**Spec coverage check:**
- **M4 = "review loop + agent-as-judge + test-count gate."** → Task 3 (verdict from review agent), Task 5 (verdict router + bounded cyclic execution), Task 4 (test-count gate), Task 6 (demo). ✅
- **review writes a verdict; approve→test, reject→implement, bounded by max_retries (spec §6).** Task 5 router. ✅
- **test-count gate alongside success_criteria (spec §6).** Task 4. ✅
- **agent-as-judge = read-only reviewer role.** review uses `reviewer` (read-only); verdict parsed from result. ✅
- **eval/ layer (spec §11).** Task 1: `eval/verdict.py` + `eval/criteria.py`. ✅
- **M3 follow-up folded in:** worktree branch-name collision on cycle re-entry → per-step attempt counter + `/{attempt}` suffix (Task 2); verdict router via the pre-wired `wire_edges(router=)` kwarg (Task 5). ✅

**Deliberately deferred (noted in-task):** gate/HITL + checkpointer + merge (M5); knowledge/MCP/status/OpenCode (M6); parallel reducers + AgenticSupervisor (later); cross-step filesystem change propagation (merge/M5 — review judges injected output text, not the filesystem); `Done.is_error` vs `success_criteria` precedence (carried from M3); real `--resume` across retries.

**Type consistency check:** `parse_output`/`Verdict` from `eval.verdict` used in `executors.py` (agent + task) and `scheduler.py` (router). `count_tests`/`run_success_criteria`/`test_count_regressed` from `eval.criteria` used in `executors.py`. `RunContext.attempts` written in `executors.py`, read in `scheduler.py` router. Branch suffix `/{attempt}` consistent with the updated `test_agent_step` assertions. `wire_edges(router=...)` signature matches the M3 seam. ✅

**Placeholder scan:** every code step has complete code; no TBD/TODO. ✅

---

## Execution handoff

**Dependency-correct execution order:**

```
1 → 2 → 3 → 4 → 5 → 6
```

Notes:
- Task 1 is a behavior-preserving consolidation (moves `_parse_task_output`/`_run_success_criteria` into `eval/`); run the full suite after it to confirm task/agent steps still pass.
- Tasks 2 and 3 are independent small additions to `run_agent_step` (attempt counter/branch; verdict parsing); Task 4 layers the gate on the same function — implement in order to avoid edit collisions.
- Task 5 is the cyclic core (verdict router) and Task 4 (test-count gate) are the highest-risk — they warrant dedicated review.
- Task 6 should need **no `cli.py` change** (the M3 full-run path already routes through the controller/scheduler); if a genuine gap appears, fix minimally.

This plan is intended for **superpowers:subagent-driven-development**: one fresh implementer subagent per task, spec-compliance then code-quality review between tasks (dedicated review on Tasks 4 and 5), in an isolated worktree, finishing by merging to `orchestrator-design` (the established M-series workflow).
