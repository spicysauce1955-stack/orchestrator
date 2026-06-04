# M3 — Full DAG Executor + Task Step + success_criteria/retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a multi-step pipeline end-to-end through the compiled LangGraph — `classify (task) → plan (agent) → implement (agent)` — with real cross-step dataflow (`{{step.output}}` templating) and a `success_criteria` shell-gate + bounded retry inner loop, all reachable via `orch run <pipeline> --task <t>`.

**Architecture:** A `DeterministicScheduler` (the declarative Controller, spec §6) builds an **executable** LangGraph `StateGraph` from the pipeline IR — real node closures instead of M1's placeholders — threading a single shared `RunContext` through nodes. Each node dispatches to a `task` executor (cheap LLM-glue via the harness adapter, no worktree, output parsed against `output_schema`) or the M2 `agent` executor (now extended with the `success_criteria`/retry inner loop). Prompts are rendered with a `{{ ... }}` template engine resolving pipeline inputs and prior step outputs. This is where **open question #13 gets re-tested for real**: the typed pipeline + worktree steps execute on an actually-invoked `StateGraph`.

**Tech Stack:** Python 3.11, LangGraph 1.x (`StateGraph.ainvoke`), Pydantic v2, asyncio, OTel spans, pytest + pytest-asyncio. Builds on M1 (config/compiler) + M2 (harness adapter, capabilities, worktree, spans, `run_agent_step`).

---

## Context for the implementer

You are extending a working M1+M2 codebase. M2 shipped: the `HarnessAdapter` Protocol + `ClaudeCodeCLIAdapter`, capability resolution, git-worktree isolation, OTel spans, and `run_agent_step` (one agent step end-to-end), reachable via `orch run --only <step>`. M3 makes the **whole pipeline** run.

Key existing facts you MUST respect:

- **Package manager is `uv`. There is NO system pip.** Run everything via `uv run --extra dev ...` (e.g. `uv run --extra dev python -m pytest`). The CLI is `uv run orch ...`.
- TDD throughout: failing test first → confirm it fails → implement → confirm pass → full suite green → commit. Frequent commits (one per task).
- Tests run against a **fake harness stub binary** (`tests/fixtures/fake_harness/fake_harness.py`, zero API cost). The `ClaudeCodeCLIAdapter` is constructed with `binary=[sys.executable, str(FAKE)]` in tests, or honors `$ORCH_CLAUDE_BIN`. The fake harness reads `$ORCH_FAKE_SCRIPT` / `$ORCH_FAKE_SCRIPT_DIR` / `$ORCH_FAKE_TOUCH` / `$ORCH_FAKE_EXIT` / `$ORCH_FAKE_CALLS` env vars.
- Ruff selects `E,F,I,UP,B`, ignores `UP042`, has `flake8-bugbear.extend-immutable-calls = ["typer.Option","typer.Argument"]`. Keep clean: `uv run --extra dev ruff check .`.
- **Reference syntax decision (locked by the user for M3): `{{ ... }}`.** Both compile-time validation (`validate.py`) and runtime templating use `{{name}}` / `{{step.output}}` / `{{step.output.field}}`, with optional inner whitespace (`{{ task }}`). Prose containing angle brackets (`List<T>`) must NOT be treated as a reference.

Relevant existing code (read before starting the tasks that touch them):
- `orchestrator/config/schemas.py` — `Step` (fields `type`, `role`, `prompt`, `output_schema`, `needs`, `success_criteria`, `max_retries`, `on_reject`, ...), `StepType` (task|agent|gate), `Mode` (declarative|agentic), `Pipeline`, `Defaults`.
- `orchestrator/compile/ir.py` — `Edge`, `GraphIR`, `build_ir(pipeline)` (needs→edges, on_reject→conditional back-edge, entrypoints/terminals).
- `orchestrator/compile/compiler.py` — `RunState` (placeholder TypedDict for *compile-time* lowering — leave it for `orch compile`), `_placeholder_node`, `to_state_graph(pipeline, ir)`, `compile_pipeline`.
- `orchestrator/compile/validate.py` — `_ancestors`, `_has_cycle`, `validate_dag`, `_REF` regex + `validate_typed_io`, `validate_file_scope`.
- `orchestrator/runtime/state.py` — `Artifact`, `RunContext` (`record(artifact)` stores by `step_id` + rolls up cost).
- `orchestrator/runtime/executors.py` — `_render_prompt`, `_capture_diff`, `run_agent_step(workspace, pipeline, step, ctx, *, repo, adapter)`.
- `orchestrator/harness/claude_code.py` — `ClaudeCodeCLIAdapter` (`start_session`, `prompt`, `_stream`, `translate`), `parse_line`.
- `orchestrator/cli.py` — `run` (currently requires `--only`).

**Scope boundary for M3 (do NOT build these — later milestones):**
- Review loop / verdict-driven `on_reject` routing / agent-as-judge / test-count gate → **M4**.
- HITL `gate` step (`interrupt`/resume) / SQLite checkpointer / merge→PR / conflict gate → **M5**.
- Orchestrator agent / message bus / knowledge injection (core + MCP) / OpenCode adapter / `orch status` → **M6**.
- `AgenticSupervisor` Controller, best-of-n / parallel branches (and the state reducers they'd need) → deferred.

M3's runnable demo is a **linear** pipeline `classify → plan → implement`. Conditional (`on_reject`) edges are wired structurally (forward-only router, unchanged from M1) but their verdict logic is M4. `gate` steps are not executed in M3 (the demo has none); a gate node raises `NotImplementedError` pointing at M5.

---

## File structure

| File | Responsibility |
|------|----------------|
| `orchestrator/runtime/template.py` | **New.** `render_template(template, inputs, artifacts)` — `{{ ... }}` resolution at runtime. |
| `orchestrator/runtime/scheduler.py` | **New.** `DeterministicScheduler` — builds + `ainvoke`s the executable `StateGraph`. |
| `orchestrator/runtime/controller.py` | **New.** `make_controller(mode, ...)` — the mode seam (declarative now; agentic raises). |
| `orchestrator/runtime/state.py` | **Modify.** Add `Artifact.output_data`; add `GraphState` TypedDict (`{"ctx": RunContext}`). |
| `orchestrator/runtime/executors.py` | **Modify.** Use `render_template`; extract shared `_drive_harness`; add `success_criteria`/retry loop to `run_agent_step`; add `run_task_step`. |
| `orchestrator/runtime/__init__.py` | **Modify.** Re-export new symbols. |
| `orchestrator/compile/compiler.py` | **Modify.** Extract `wire_edges(builder, ir, *, router=None)`; `to_state_graph` uses it. |
| `orchestrator/compile/validate.py` | **Modify.** `{{ ... }}` regex; require step-output refs to be transitive ancestors; reject deep field refs; drop the cycle-masking dangling guard. |
| `orchestrator/harness/claude_code.py` | **Modify.** Drain subprocess stderr (M2 follow-up). |
| `examples/feature-pipeline/.orchestrator/pipelines/feature.yaml` | **Modify.** `<task>` → `{{task}}` in the classify prompt. |
| `examples/feature-pipeline/.orchestrator/pipelines/triage.yaml` | **New.** Linear `classify → plan → implement` demo pipeline. |
| `tests/fixtures/fake_harness/fake_harness.py` | **Modify.** `$ORCH_FAKE_SCRIPT_DIR` keyword routing + `$ORCH_FAKE_CALLS` invocation log. |
| `tests/fixtures/fake_harness/scripts/classify.ndjson` · `default.ndjson` | **New.** Canned scripts for task/default steps. |
| `tests/unit/test_template.py` · `tests/unit/test_validate.py` (modify) · `tests/unit/test_fake_harness.py` (modify) | Unit tests. |
| `tests/integration/test_scheduler.py` · `test_run_cli.py` (modify) · `tests/integration/test_agent_step.py` (modify) | Integration tests. |

---

## M3 design decisions (read before starting)

1. **Single shared `RunContext` threaded as one state key.** The executable graph's state is `GraphState = TypedDict("GraphState", {"ctx": RunContext})`. Each node reads `state["ctx"]`, runs its executor (which mutates `ctx.artifacts` + `ctx.total_cost_usd` via `ctx.record`), and returns `{"ctx": ctx}`. This is safe because the MVP pipeline is **linear** (no parallel fan-out). Parallel/best-of-n branches (deferred) would need per-key reducers — noted, not built. This keeps `run_agent_step`'s signature identical to M2.
2. **`task` steps reuse the harness adapter (MVP "cheap LLM glue").** Rather than introduce a separate LLM-client seam prematurely, a `task` step drives the same `ClaudeCodeCLIAdapter` with `ResolvedCaps.read_only()`, **no worktree** (cwd = repo), and parses the harness's final result into `output_data` validated against `output_schema`. A dedicated lightweight client can replace this later without changing the config model. (The `merge` task step — `merge_strategy` — is M5; `run_task_step` handles prompt+output_schema task steps only and rejects merge steps with a clear M5 message.)
3. **`success_criteria` is a shell gate with a bounded retry inner loop** (spec §6 step 6). After the harness runs, if `step.success_criteria` is set, run it as a shell command **in the worktree**. On non-zero exit with retries left (`attempt < step.max_retries`), re-prompt the same worktree with the failure output appended, and re-evaluate. Cost accumulates across attempts; the artifact records the summed cost. On final failure, `artifact.is_error = True`. The test-count gate (preventing "go green by deleting tests") is **M4**. Worktree cleanup stays always-on in M3 (retain-on-failure deferred).
4. **DRY graph wiring.** Extract `wire_edges(builder, ir, *, router=None)` into `compiler.py`; both `to_state_graph` (compile-time, placeholder nodes) and the scheduler (execution, real nodes) call it. M3 passes no router (forward-only, identical to M1's behavior); M4 will pass a verdict router for `on_reject`.
5. **Open question #13.** Task 8's scheduler integration test invokes a real compiled `StateGraph` with real worktree-creating nodes end-to-end. That resolves #13 for **linear DAG execution**. The **cyclic** `on_reject` execution path is validated in M4 (verdict routing). Note this explicitly in the M3 follow-ups.
6. **`{{ ... }}` everywhere.** One regex shape — `\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}` — shared in spirit by `validate.py` (compile-time) and `template.py` (runtime). Inner whitespace allowed.

---

## Task 1: Adapter — drain subprocess stderr (M2 follow-up)

**Files:**
- Modify: `orchestrator/harness/claude_code.py`
- Test: `tests/integration/test_adapter_contract.py` (add one test)

A real `claude` binary can emit enough stderr to fill the OS pipe buffer and deadlock at `await proc.wait()`. M2 left `stderr=PIPE` undrained. Fix: discard stderr.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_adapter_contract.py`:

```python
async def test_adapter_does_not_deadlock_on_large_stderr(monkeypatch, tmp_path):
    import sys

    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_STDERR_BYTES", "200000")  # ~200 KB of stderr
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    session = await adapter.start_session(cwd=tmp_path, caps=ResolvedCaps.read_only(), mcp_servers=[])
    events = []
    stream = await adapter.prompt(session, "x")
    async for ev in stream:
        events.append(ev)
    # If stderr weren't drained, a 200 KB write would block the child and this would hang.
    assert isinstance(events[-1], Done)
```

You must also teach the fake harness to emit stderr on demand. In `tests/fixtures/fake_harness/fake_harness.py`, near the top of `main()` (before streaming), add:

```python
    stderr_bytes = int(os.environ.get("ORCH_FAKE_STDERR_BYTES", "0"))
    if stderr_bytes:
        sys.stderr.write("x" * stderr_bytes)
        sys.stderr.flush()
```

- [ ] **Step 2: Run it to verify it fails (hangs/deadlocks)**

Run: `uv run --extra dev python -m pytest tests/integration/test_adapter_contract.py::test_adapter_does_not_deadlock_on_large_stderr -v --timeout=20` (if `pytest-timeout` is unavailable, run normally; a hang for >~10s confirms the bug — Ctrl-C and proceed).
Expected: FAIL/hang — undrained stderr pipe deadlocks.

- [ ] **Step 3: Drain stderr**

In `orchestrator/harness/claude_code.py`, in `_stream`, change the subprocess spawn so stderr is discarded rather than piped:

```python
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sess.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
```

(Replace the existing `stderr=asyncio.subprocess.PIPE`.)

- [ ] **Step 4: Run the test + full suite**

Run: `uv run --extra dev python -m pytest tests/integration/test_adapter_contract.py -v`
Expected: PASS (no hang).

Run: `uv run --extra dev python -m pytest`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/harness/claude_code.py tests/fixtures/fake_harness/fake_harness.py tests/integration/test_adapter_contract.py
git commit -m "fix(m3): drain harness subprocess stderr (avoid pipe deadlock)"
```

---

## Task 2: Fake harness — script-dir routing + invocation log + new scripts

**Files:**
- Modify: `tests/fixtures/fake_harness/fake_harness.py`
- Create: `tests/fixtures/fake_harness/scripts/classify.ndjson`
- Create: `tests/fixtures/fake_harness/scripts/default.ndjson`
- Test: `tests/unit/test_fake_harness.py` (add tests)

A multi-step run spawns the fake harness once per step with the **same** environment, but different steps need different canned output (classify must return JSON; plan/implement return text). Solution: `$ORCH_FAKE_SCRIPT_DIR` selects a script by a keyword in the prompt (the arg after `-p`). `$ORCH_FAKE_CALLS` appends one line per invocation so tests can assert re-prompt counts.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_fake_harness.py`:

```python
SCRIPTS_DIR = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"


def test_script_dir_routes_classify_by_prompt_keyword(tmp_path):
    env = {
        **os.environ,
        "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR),
    }
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "Classify this task as ...", "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    assert '"kind"' in last  # classify.ndjson result carries a kind field


def test_script_dir_falls_back_to_default(tmp_path):
    env = {**os.environ, "ORCH_FAKE_SCRIPT_DIR": str(SCRIPTS_DIR)}
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "Write a plan", "--output-format", "stream-json"],
        env=env, capture_output=True, text=True,
    )
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    assert '"type": "result"' in last or '"type":"result"' in last
    assert '"kind"' not in last  # default.ndjson is plain text


def test_calls_log_appends_per_invocation(tmp_path):
    calls = tmp_path / "calls.log"
    env = {**os.environ, "ORCH_FAKE_SCRIPT": str(PLAN), "ORCH_FAKE_CALLS": str(calls)}
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(FAKE), "-p", "hi", "--output-format", "stream-json"],
            env=env, capture_output=True, text=True,
        )
    assert len(calls.read_text().splitlines()) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/unit/test_fake_harness.py -v`
Expected: FAIL — routing/log/scripts not present.

- [ ] **Step 3: Create the new scripts**

Create `tests/fixtures/fake_harness/scripts/classify.ndjson`:

```
{"type":"system","subtype":"init","session_id":"fake-classify-1","tools":[],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Classifying."}]}}
{"type":"result","subtype":"success","is_error":false,"result":"{\"kind\": \"feature\"}","total_cost_usd":0.001,"usage":{"input_tokens":20,"output_tokens":5},"session_id":"fake-classify-1"}
```

Create `tests/fixtures/fake_harness/scripts/default.ndjson`:

```
{"type":"system","subtype":"init","session_id":"fake-default-1","tools":["Read"],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Step output: "}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"d1","name":"Read","input":{"file_path":"README.md"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"d1","content":"contents"}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"done step body"}]}}
{"type":"result","subtype":"success","is_error":false,"result":"step complete","total_cost_usd":0.01,"usage":{"input_tokens":50,"output_tokens":25},"session_id":"fake-default-1"}
```

- [ ] **Step 4: Add routing + calls-log to the fake harness**

In `tests/fixtures/fake_harness/fake_harness.py`, replace the script-selection logic so it supports a directory with keyword routing, and add the calls log. The relevant part of `main()` becomes:

```python
    # Record the prompt (arg after -p) for routing + logging.
    prompt = ""
    args = sys.argv[1:]
    if "-p" in args:
        i = args.index("-p")
        if i + 1 < len(args):
            prompt = args[i + 1]

    calls_log = os.environ.get("ORCH_FAKE_CALLS")
    if calls_log:
        with open(calls_log, "a") as fh:
            fh.write(prompt[:60] + "\n")

    # Script selection: explicit file wins; else route within a dir by prompt keyword.
    script_env = os.environ.get("ORCH_FAKE_SCRIPT")
    script_dir = os.environ.get("ORCH_FAKE_SCRIPT_DIR")
    if script_env:
        script = Path(script_env)
    elif script_dir:
        name = "classify.ndjson" if "classify" in prompt.lower() else "default.ndjson"
        script = Path(script_dir) / name
    else:
        script = DEFAULT_SCRIPT
```

Keep the existing `$ORCH_FAKE_TOUCH`, `$ORCH_FAKE_STDERR_BYTES` (Task 1), `$ORCH_FAKE_ARGV`, `$ORCH_FAKE_EXIT` behavior. Ensure `import os` and `from pathlib import Path` are present (they are).

- [ ] **Step 5: Run the tests + full suite**

Run: `uv run --extra dev python -m pytest tests/unit/test_fake_harness.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest`
Expected: full suite green (existing M2 tests using `$ORCH_FAKE_SCRIPT` still pass — explicit file still wins).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/fake_harness/
git commit -m "test(m3): fake harness script-dir routing + invocation log + classify/default scripts"
```

---

## Task 3: State — `Artifact.output_data` + `GraphState`

**Files:**
- Modify: `orchestrator/runtime/state.py`
- Test: `tests/unit/test_state.py` (add tests)

`task` steps produce structured output (e.g. `{kind: feature}`); store it on the artifact. The executable graph threads a single `RunContext` under one state key.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_state.py`:

```python
def test_artifact_carries_structured_output_data():
    from orchestrator.runtime.state import Artifact

    a = Artifact(
        step_id="classify", output='{"kind": "feature"}', diff="", branch="",
        cost_usd=0.001, tokens=25, is_error=False, output_data={"kind": "feature"},
    )
    assert a.output_data == {"kind": "feature"}


def test_artifact_output_data_defaults_none():
    from orchestrator.runtime.state import Artifact

    a = Artifact("s", "o", "", "b", 0.0, 0, False)
    assert a.output_data is None


def test_graph_state_holds_run_context():
    from orchestrator.runtime.state import GraphState, RunContext

    ctx = RunContext(run_id="r1", inputs={"task": "t"})
    state: GraphState = {"ctx": ctx}
    assert state["ctx"].run_id == "r1"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/unit/test_state.py -v`
Expected: FAIL — `output_data` / `GraphState` missing.

- [ ] **Step 3: Extend state**

In `orchestrator/runtime/state.py`, add the field and the TypedDict. The file becomes:

```python
"""Typed run state threaded through execution (spec §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass
class Artifact:
    step_id: str
    output: str
    diff: str
    branch: str
    cost_usd: float
    tokens: int
    is_error: bool
    output_data: dict | None = None


@dataclass
class RunContext:
    run_id: str
    inputs: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    total_cost_usd: float = 0.0

    def record(self, artifact: Artifact) -> None:
        self.artifacts[artifact.step_id] = artifact
        self.total_cost_usd += artifact.cost_usd


class GraphState(TypedDict, total=False):
    """Executable-graph state: a single shared RunContext threaded through nodes.

    MVP pipelines are linear, so one mutable RunContext under one key is safe.
    Parallel/best-of-n branches (deferred) would need per-key reducers.
    """

    ctx: RunContext
```

- [ ] **Step 4: Run the test + full suite**

Run: `uv run --extra dev python -m pytest tests/unit/test_state.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/runtime/state.py tests/unit/test_state.py
git commit -m "feat(m3): Artifact.output_data + GraphState (shared RunContext)"
```

---

## Task 4: Runtime templating (`{{ ... }}`)

**Files:**
- Create: `orchestrator/runtime/template.py`
- Test: `tests/unit/test_template.py`

Resolve `{{name}}` (pipeline input), `{{step.output}}` (a prior step's text output), and `{{step.output.field}}` (a field of a prior step's structured `output_data`). Whitespace inside braces allowed. Unknown refs raise `TemplateError`. Prose angle brackets are untouched.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_template.py`:

```python
import pytest

from orchestrator.runtime.state import Artifact
from orchestrator.runtime.template import TemplateError, render_template


def _arts():
    return {
        "plan": Artifact("plan", "THE PLAN", "", "b", 0.0, 0, False),
        "classify": Artifact(
            "classify", '{"kind":"feature"}', "", "b", 0.0, 0, False,
            output_data={"kind": "feature"},
        ),
    }


def test_input_substitution():
    assert render_template("Do {{task}} now", {"task": "X"}, {}) == "Do X now"


def test_whitespace_inside_braces():
    assert render_template("Do {{ task }} now", {"task": "X"}, {}) == "Do X now"


def test_step_output_substitution():
    out = render_template("Plan:\n{{plan.output}}", {}, _arts())
    assert out == "Plan:\nTHE PLAN"


def test_step_output_field_substitution():
    out = render_template("Kind={{classify.output.kind}}", {}, _arts())
    assert out == "Kind=feature"


def test_prose_angle_brackets_untouched():
    s = "refactor the List<T> wrapper"
    assert render_template(s, {"task": "x"}, {}) == s


def test_unknown_input_raises():
    with pytest.raises(TemplateError):
        render_template("{{nope}}", {"task": "x"}, {})


def test_unknown_step_raises():
    with pytest.raises(TemplateError):
        render_template("{{ghost.output}}", {}, _arts())


def test_non_output_segment_raises():
    with pytest.raises(TemplateError):
        render_template("{{plan.diff}}", {}, _arts())


def test_missing_field_raises():
    with pytest.raises(TemplateError):
        render_template("{{classify.output.missing}}", {}, _arts())


def test_deep_field_ref_raises():
    with pytest.raises(TemplateError):
        render_template("{{classify.output.a.b}}", {}, _arts())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/unit/test_template.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the template engine**

Create `orchestrator/runtime/template.py`:

```python
"""Runtime prompt templating (spec §4 typed I/O). Syntax: {{ ... }}.

Resolves {{name}} (pipeline input), {{step.output}} (prior step text), and
{{step.output.field}} (field of a prior step's structured output_data).
Prose containing angle brackets (List<T>) is never a reference.
"""

from __future__ import annotations

import re

from orchestrator.runtime.state import Artifact

_REF = re.compile(r"\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}")


class TemplateError(Exception):
    """Raised when a {{ ... }} reference cannot be resolved."""


def render_template(
    template: str, inputs: dict[str, str], artifacts: dict[str, Artifact]
) -> str:
    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        parts = token.split(".")
        head = parts[0]

        if len(parts) == 1:
            if head not in inputs:
                raise TemplateError(f"reference {{{{{token}}}}} matches no pipeline input")
            return inputs[head]

        if head not in artifacts:
            raise TemplateError(f"reference {{{{{token}}}}} targets unknown step '{head}'")
        if parts[1] != "output":
            raise TemplateError(
                f"reference {{{{{token}}}}} must use '.output' (got '.{parts[1]}')"
            )
        artifact = artifacts[head]
        if len(parts) == 2:
            return artifact.output
        if len(parts) == 3:
            data = artifact.output_data or {}
            if parts[2] not in data:
                raise TemplateError(
                    f"reference {{{{{token}}}}} field '{parts[2]}' not in output of '{head}'"
                )
            return str(data[parts[2]])
        raise TemplateError(f"reference {{{{{token}}}}} is too deeply nested (max 3 segments)")

    return _REF.sub(_sub, template)
```

- [ ] **Step 4: Run the test + full suite**

Run: `uv run --extra dev python -m pytest tests/unit/test_template.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/runtime/template.py tests/unit/test_template.py
git commit -m "feat(m3): runtime {{...}} prompt templating engine"
```

---

## Task 5: Compile-time validation — `{{ ... }}` + hardening

**Files:**
- Modify: `orchestrator/compile/validate.py`
- Modify: `examples/feature-pipeline/.orchestrator/pipelines/feature.yaml`
- Test: `tests/unit/test_validate.py` (modify existing reference tests + add hardening tests)

Migrate compile-time reference validation to `{{ ... }}`, add the deferred M1 hardening: step-output refs must point to a transitive ancestor; reject deep field refs (>3 segments); drop the cycle-masking dangling guard so both dangling-need and cycle errors surface.

- [ ] **Step 1: Update the example pipeline prompt**

In `examples/feature-pipeline/.orchestrator/pipelines/feature.yaml`, change the classify prompt:

```yaml
  - id: classify
    type: task
    prompt: "Classify {{task}} as: bugfix | feature | refactor"
    output_schema: { kind: "enum[bugfix,feature,refactor]" }
```

- [ ] **Step 2: Write/adjust the failing tests**

In `tests/unit/test_validate.py`, the existing typed-I/O tests use `<...>` syntax — update them to `{{...}}` and add the new hardening tests. Add these tests (adjust existing ones similarly so the suite reflects the new syntax):

```python
from orchestrator.compile.validate import validate_dag, validate_typed_io
from orchestrator.config.schemas import Pipeline


def _pipe(steps, inputs=None):
    return Pipeline.model_validate({"inputs": inputs or {}, "steps": steps})


def test_typed_io_accepts_brace_input_ref():
    p = _pipe(
        [{"id": "a", "type": "task", "prompt": "do {{task}}"}],
        inputs={"task": "string"},
    )
    assert validate_typed_io(p) == []


def test_typed_io_rejects_unknown_input_ref():
    p = _pipe([{"id": "a", "type": "task", "prompt": "do {{nope}}"}], inputs={"task": "string"})
    errs = validate_typed_io(p)
    assert any("nope" in e for e in errs)


def test_typed_io_prose_angle_brackets_ignored():
    p = _pipe([{"id": "a", "type": "task", "prompt": "use List<T> generics"}])
    assert validate_typed_io(p) == []


def test_typed_io_step_output_ref_must_be_ancestor():
    # 'b' references 'a.output' but does NOT depend on 'a' -> error.
    p = _pipe([
        {"id": "a", "type": "task", "prompt": "x", "output_schema": {"k": "string"}},
        {"id": "b", "type": "task", "prompt": "use {{a.output}}"},
    ])
    errs = validate_typed_io(p)
    assert any("a.output" in e and "ancestor" in e.lower() for e in errs)


def test_typed_io_step_output_ref_ok_when_ancestor():
    p = _pipe([
        {"id": "a", "type": "task", "prompt": "x"},
        {"id": "b", "type": "task", "prompt": "use {{a.output}}", "needs": ["a"]},
    ])
    assert validate_typed_io(p) == []


def test_typed_io_rejects_deep_field_ref():
    p = _pipe([
        {"id": "a", "type": "task", "prompt": "x", "output_schema": {"k": "string"}},
        {"id": "b", "type": "task", "prompt": "{{a.output.k.deep}}", "needs": ["a"]},
    ])
    errs = validate_typed_io(p)
    assert any("a.output.k.deep" in e for e in errs)


def test_dag_reports_both_dangling_and_cycle():
    # a needs [b, ghost]; b needs [a] -> BOTH a dangling-need error AND a cycle error.
    p = _pipe([
        {"id": "a", "type": "task", "prompt": "x", "needs": ["b", "ghost"]},
        {"id": "b", "type": "task", "prompt": "y", "needs": ["a"]},
    ])
    errs = validate_dag(p)
    assert any("ghost" in e for e in errs)
    assert any("cycle" in e.lower() for e in errs)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/unit/test_validate.py -v`
Expected: FAIL — old `<...>` regex, no ancestor check, cycle masked by dangling guard.

- [ ] **Step 4: Update `validate.py`**

In `orchestrator/compile/validate.py`:

(a) Change the reference regex:

```python
_REF = re.compile(r"\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}")
```

(b) Drop the cycle-masking guard in `validate_dag` — replace:

```python
    # Cycles in the forward (needs-only) graph are undeclared cycles.
    if all(d in id_set for s in pipeline.steps for d in s.needs):
        if _has_cycle(ids, deps):
            errors.append("pipeline has an undeclared cycle in `needs` edges")
```

with:

```python
    # `_has_cycle` is robust to dangling deps (deps keyed by all step ids), so we
    # always run it — dangling-need and cycle errors can both surface.
    if _has_cycle(ids, deps):
        errors.append("pipeline has an undeclared cycle in `needs` edges")
```

(c) Rewrite `validate_typed_io` to use ancestors and reject deep refs:

```python
def validate_typed_io(pipeline: Pipeline) -> list[str]:
    errors: list[str] = []
    by_id = {s.id: s for s in pipeline.steps}
    deps = {s.id: list(s.needs) for s in pipeline.steps}
    inputs = set(pipeline.inputs)

    for step in pipeline.steps:
        if not step.prompt:
            continue
        ancestors = _ancestors(step.id, deps)
        for token in _REF.findall(step.prompt):
            parts = token.split(".")
            head = parts[0]

            # {{name}} -> pipeline input.
            if len(parts) == 1:
                if head not in inputs:
                    errors.append(
                        f"step '{step.id}': reference {{{{{token}}}}} matches no pipeline input"
                    )
                continue

            # {{stepid.output[.field]}} -> a prior (ancestor) step's output.
            if head not in by_id:
                errors.append(
                    f"step '{step.id}': reference {{{{{token}}}}} targets unknown step '{head}'"
                )
                continue
            if head not in ancestors:
                errors.append(
                    f"step '{step.id}': reference {{{{{token}}}}} must point to an ancestor "
                    f"step (add '{head}' to needs)"
                )
                continue
            if parts[1] != "output":
                errors.append(
                    f"step '{step.id}': reference {{{{{token}}}}} must use '.output' "
                    f"(got '.{parts[1]}')"
                )
                continue
            if len(parts) > 3:
                errors.append(
                    f"step '{step.id}': reference {{{{{token}}}}} is too deeply nested "
                    f"(max 3 segments)"
                )
                continue
            if len(parts) == 3:
                schema = by_id[head].output_schema or {}
                if parts[2] not in schema:
                    errors.append(
                        f"step '{step.id}': reference {{{{{token}}}}} field '{parts[2]}' not in "
                        f"output_schema of '{head}'"
                    )

    return errors
```

- [ ] **Step 5: Run the tests + example compile + full suite**

Run: `uv run --extra dev python -m pytest tests/unit/test_validate.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest tests/integration/test_example_compiles.py -v`
Expected: PASS — the example's `{{task}}` classify prompt validates.

Run: `uv run --extra dev python -m pytest`
Expected: full suite green. (If any other test referenced the old `<...>` syntax or the old single-error cycle behavior, update it to match.)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/compile/validate.py examples/feature-pipeline/.orchestrator/pipelines/feature.yaml tests/unit/test_validate.py
git commit -m "feat(m3): {{...}} compile-time validation + ancestor/deep-ref/cycle hardening"
```

---

## Task 6: Executors — shared drive core + templating + success_criteria/retry

**Files:**
- Modify: `orchestrator/runtime/executors.py`
- Test: `tests/integration/test_agent_step.py` (modify + add retry test)

Refactor the harness-driving loop into a shared `_drive_harness` (used by agent + task executors). Switch prompt rendering to `render_template` (inputs + prior artifacts). Add the `success_criteria` shell gate with a bounded retry inner loop to `run_agent_step`. `run_agent_step`'s public signature is unchanged.

- [ ] **Step 1: Write the failing retry test + adjust existing**

The existing `tests/integration/test_agent_step.py` tests should still pass (the plan/edit steps have no `success_criteria`). Add a retry test. Note the `implement` step in the example feature pipeline has `success_criteria: "pytest -q"` and `max_retries: 2`; for a controlled test, construct a step inline.

Add to `tests/integration/test_agent_step.py`:

```python
async def test_success_criteria_retries_then_passes(tmp_path, monkeypatch):
    import sys

    from orchestrator.config.schemas import Step
    from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
    from orchestrator.runtime.executors import run_agent_step
    from orchestrator.runtime.state import RunContext

    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("ORCH_FAKE_CALLS", str(calls))

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    # success_criteria fails on attempt 1 (counter=1), passes on attempt 2 (counter>=2).
    step = Step.model_validate({
        "id": "impl_retry",
        "role": "implementer",
        "prompt": "do the work",
        "success_criteria": "c=$(cat .c 2>/dev/null || echo 0); c=$((c+1)); echo $c > .c; test $c -ge 2",
        "max_retries": 2,
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="rtry", inputs={"task": "t"})

    artifact = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)

    assert artifact.is_error is False           # passed within retry budget
    assert len(calls.read_text().splitlines()) == 2  # harness re-prompted once
    assert artifact.cost_usd > 0.01             # cost summed across 2 attempts


async def test_success_criteria_fails_after_exhausting_retries(tmp_path, monkeypatch):
    import sys

    from orchestrator.config.schemas import Step
    from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
    from orchestrator.runtime.executors import run_agent_step
    from orchestrator.runtime.state import RunContext

    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "impl_fail",
        "role": "implementer",
        "prompt": "do the work",
        "success_criteria": "false",
        "max_retries": 1,
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="fail", inputs={"task": "t"})

    artifact = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)
    assert artifact.is_error is True
```

Also update `test_plan_step_runs_end_to_end` if it asserts on `_render_prompt` internals; it should still pass since the plan step has a default prompt path. Confirm the `SCRIPTS` constant is defined in the file (it is, from M2).

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: the two new retry tests FAIL (no success_criteria loop yet).

- [ ] **Step 3: Refactor executors + add the retry loop**

Rewrite `orchestrator/runtime/executors.py`. Keep `_capture_diff`. Replace `_render_prompt` to use `render_template`, extract `_drive_harness`, add `_run_success_criteria`, and add the retry loop to `run_agent_step`:

```python
"""Step executors (spec §6). M3 adds task steps + the success_criteria/retry loop."""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.harness.events import Cost, Done, FileEdit, MessageChunk, ToolCall
from orchestrator.isolation.worktree import create_worktree, remove_worktree
from orchestrator.observability.spans import (
    SPAN_FILE_EDIT,
    SPAN_SESSION,
    SPAN_STEP,
    SPAN_TOOL_CALL,
    get_tracer,
)
from orchestrator.runtime.state import Artifact, RunContext
from orchestrator.runtime.template import render_template
from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities

# Default prompts when a step declares no `prompt`.
_DEFAULT_PROMPTS = {
    "planner": "Create a concise implementation plan for this task:\n\n{task}",
}


def _render_prompt(step: Step, role_name: str | None, ctx: RunContext) -> str:
    """Render a step's prompt with {{...}} templating over inputs + prior outputs."""
    if step.prompt is None:
        default = _DEFAULT_PROMPTS.get(role_name or "", "Work on this task:\n\n{task}")
        return default.format(task=ctx.inputs.get("task", ""))
    return render_template(step.prompt, ctx.inputs, ctx.artifacts)


def _capture_diff(cwd: Path) -> str:
    tracked = subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd, capture_output=True, text=True,
    ).stdout
    if untracked.strip():
        names = "\n".join(f"+++ untracked: {n}" for n in untracked.splitlines())
        tracked = f"{tracked}\n{names}" if tracked else names
    return tracked


def _run_success_criteria(criteria: str, cwd: Path) -> tuple[bool, str]:
    """Run the success_criteria shell command in `cwd`. Returns (ok, combined output)."""
    proc = subprocess.run(
        criteria, cwd=cwd, shell=True, capture_output=True, text=True
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


class _Aggregate:
    """Mutable accumulator for one harness drive."""

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.result_text = ""
        self.cost_usd = 0.0
        self.tokens = 0
        self.is_error = False

    @property
    def output(self) -> str:
        return "".join(self.text_parts) or self.result_text


async def _drive_harness(
    adapter: HarnessAdapter, caps: ResolvedCaps, cwd: Path, prompt: str,
    output_schema: dict | None, tracer,
) -> _Aggregate:
    """Start a session, stream events into session/tool/file spans, aggregate."""
    agg = _Aggregate()
    session = await adapter.start_session(cwd=cwd, caps=caps, mcp_servers=[])
    with tracer.start_as_current_span(SPAN_SESSION) as sess_span:
        stream = await adapter.prompt(session, prompt, output_schema=output_schema)
        async for ev in stream:
            if isinstance(ev, MessageChunk):
                agg.text_parts.append(ev.text)
            elif isinstance(ev, ToolCall):
                with tracer.start_as_current_span(SPAN_TOOL_CALL) as tc:
                    tc.set_attribute("tool.name", ev.name)
                    tc.set_attribute("tool.status", ev.status)
            elif isinstance(ev, FileEdit):
                with tracer.start_as_current_span(SPAN_FILE_EDIT) as fe:
                    fe.set_attribute("file.path", ev.path)
                    fe.set_attribute("file.kind", ev.kind)
            elif isinstance(ev, Cost):
                agg.cost_usd += ev.usd
                agg.tokens += ev.tokens
                sess_span.set_attribute("cost.usd", ev.usd)
                sess_span.set_attribute("cost.tokens", ev.tokens)
            elif isinstance(ev, Done):
                agg.result_text = ev.result
                agg.is_error = ev.is_error
                sess_span.set_attribute("done.is_error", ev.is_error)
        sess_span.set_attribute("session.handle", session)
    return agg


async def run_agent_step(
    workspace: Workspace, pipeline: Pipeline, step: Step, ctx: RunContext,
    *, repo: Path, adapter: HarnessAdapter,
) -> Artifact:
    """Run one agent step end-to-end: worktree → harness drive → success_criteria/retry."""
    if step.role is None:
        raise ValueError(f"step '{step.id}' is not an agent step (no role)")
    role = workspace.roles[step.role]
    caps = resolve_capabilities(role, workspace)
    branch = f"orch/{ctx.run_id}/{step.id}"
    worktree = create_worktree(Path(repo), branch=branch)

    tracer = get_tracer()
    total_cost = 0.0
    total_tokens = 0
    output = ""
    is_error = False

    try:
        with tracer.start_as_current_span(SPAN_STEP) as step_span:
            step_span.set_attribute("step.id", step.id)
            step_span.set_attribute("step.role", step.role)
            step_span.set_attribute("step.harness", role.harness.value)

            base_prompt = _render_prompt(step, step.role, ctx)
            feedback = ""
            for attempt in range(step.max_retries + 1):
                prompt = base_prompt if not feedback else (
                    f"{base_prompt}\n\nThe previous attempt failed `success_criteria`:\n{feedback}\n"
                    "Fix the issues and try again."
                )
                agg = await _drive_harness(
                    adapter, caps, worktree.path, prompt, step.output_schema, tracer
                )
                total_cost += agg.cost_usd
                total_tokens += agg.tokens
                output = agg.output
                is_error = agg.is_error

                if not step.success_criteria:
                    break
                ok, crit_out = _run_success_criteria(step.success_criteria, worktree.path)
                step_span.set_attribute(f"success_criteria.attempt_{attempt}", ok)
                if ok:
                    is_error = False
                    break
                if attempt >= step.max_retries:
                    is_error = True
                    output = f"{output}\n[success_criteria failed after {attempt + 1} attempt(s)]"
                    break
                feedback = crit_out

            diff = _capture_diff(worktree.path)
            step_span.set_attribute("step.is_error", is_error)

        artifact = Artifact(
            step_id=step.id, output=output, diff=diff, branch=branch,
            cost_usd=total_cost, tokens=total_tokens, is_error=is_error,
        )
        ctx.record(artifact)
        return artifact
    finally:
        remove_worktree(Path(repo), worktree)
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: PASS (retry-then-pass, fail-after-retries, plus the existing plan/edit tests).

Run: `uv run --extra dev python -m pytest`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/runtime/executors.py tests/integration/test_agent_step.py
git commit -m "feat(m3): shared harness-drive core + {{...}} prompts + success_criteria/retry loop"
```

---

## Task 7: Task-step executor (`run_task_step`)

**Files:**
- Modify: `orchestrator/runtime/executors.py`
- Modify: `orchestrator/runtime/__init__.py`
- Test: `tests/integration/test_task_step.py`

A `task` step (e.g. `classify`) is cheap LLM glue: read-only caps, **no worktree**, drive the harness in the repo cwd, and parse the result into `output_data` validated against `output_schema` (MVP: a single `enum[...]` field).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_task_step.py`:

```python
import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Step
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.executors import run_task_step
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


async def test_classify_task_parses_enum_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "classify", "type": "task",
        "prompt": "Classify {{task}} as: bugfix | feature | refactor",
        "output_schema": {"kind": "enum[bugfix,feature,refactor]"},
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", inputs={"task": "add a widget"})

    artifact = await run_task_step(ws, ws.pipelines["feature"], step, ctx, repo=tmp_path, adapter=adapter)

    assert artifact.is_error is False
    assert artifact.output_data == {"kind": "feature"}
    assert ctx.artifacts["classify"].output_data["kind"] == "feature"


async def test_task_invalid_enum_value_is_error(tmp_path, monkeypatch):
    # classify.ndjson returns "feature"; constrain the enum so it's NOT allowed.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "classify", "type": "task",
        "prompt": "x", "output_schema": {"kind": "enum[bugfix,refactor]"},
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r2", inputs={"task": "t"})
    artifact = await run_task_step(ws, ws.pipelines["feature"], step, ctx, repo=tmp_path, adapter=adapter)
    assert artifact.is_error is True


async def test_merge_task_step_rejected_until_m5(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({"id": "merge", "type": "task", "merge_strategy": "sequential-rebase"})
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r3", inputs={})
    with pytest.raises(NotImplementedError):
        await run_task_step(ws, ws.pipelines["feature"], step, ctx, repo=tmp_path, adapter=adapter)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_task_step.py -v`
Expected: FAIL — `run_task_step` missing.

- [ ] **Step 3: Implement `run_task_step` + output parsing**

Append to `orchestrator/runtime/executors.py`:

```python
import json
import re

_ENUM_RE = re.compile(r"enum\[([^\]]*)\]")


def _parse_task_output(output: str, output_schema: dict | None) -> tuple[dict | None, bool]:
    """Parse a task step's textual output into structured output_data.

    MVP: if output_schema declares a single enum field, accept either a JSON object
    {field: value} or a bare value, and validate enum membership. Returns
    (output_data, is_error). With no output_schema, output_data is None (ok).
    """
    if not output_schema:
        return None, False

    # Try JSON first.
    data: dict | None = None
    try:
        loaded = json.loads(output)
        if isinstance(loaded, dict):
            data = loaded
    except (json.JSONDecodeError, TypeError):
        data = None

    # Validate each enum-typed field.
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
            value = output.strip()  # bare value for a single-field schema
        if value not in allowed:
            return None, True
        data = {**(data or {}), field_name: value}

    return data, False


async def run_task_step(
    workspace: Workspace, pipeline: Pipeline, step: Step, ctx: RunContext,
    *, repo: Path, adapter: HarnessAdapter,
) -> Artifact:
    """Run a `task` step (cheap LLM glue): read-only, no worktree, parse output."""
    if step.merge_strategy is not None:
        raise NotImplementedError(f"merge task step '{step.id}' runs in M5")

    caps = ResolvedCaps.read_only()
    tracer = get_tracer()
    prompt = _render_prompt(step, None, ctx)

    with tracer.start_as_current_span(SPAN_STEP) as step_span:
        step_span.set_attribute("step.id", step.id)
        step_span.set_attribute("step.type", "task")
        agg = await _drive_harness(
            adapter, caps, Path(repo), prompt, step.output_schema, tracer
        )
        output = agg.result_text or agg.output  # task output is the final result text
        output_data, parse_error = _parse_task_output(output, step.output_schema)
        is_error = agg.is_error or parse_error
        step_span.set_attribute("step.is_error", is_error)

    artifact = Artifact(
        step_id=step.id, output=output, diff="", branch="",
        cost_usd=agg.cost_usd, tokens=agg.tokens, is_error=is_error,
        output_data=output_data,
    )
    ctx.record(artifact)
    return artifact
```

> Note: `import json` / `import re` go at the top of the module with the other imports — move them up rather than mid-file to keep ruff's import rules happy.

Update `orchestrator/runtime/__init__.py` to re-export `run_task_step`:

```python
"""Runtime layer: run state + step executors (spec §6)."""

from orchestrator.runtime.executors import run_agent_step, run_task_step
from orchestrator.runtime.state import Artifact, GraphState, RunContext

__all__ = ["Artifact", "GraphState", "RunContext", "run_agent_step", "run_task_step"]
```

- [ ] **Step 4: Run the tests + full suite + lint**

Run: `uv run --extra dev python -m pytest tests/integration/test_task_step.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green, lint clean.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/runtime/executors.py orchestrator/runtime/__init__.py tests/integration/test_task_step.py
git commit -m "feat(m3): task-step executor (read-only LLM glue + enum output parsing)"
```

---

## Task 8: DeterministicScheduler + Controller seam + shared `wire_edges`

**Files:**
- Modify: `orchestrator/compile/compiler.py` (extract `wire_edges`)
- Create: `orchestrator/runtime/scheduler.py`
- Create: `orchestrator/runtime/controller.py`
- Modify: `orchestrator/runtime/__init__.py` (re-export)
- Test: `tests/unit/test_compiler.py` (confirm still green after refactor) + `tests/integration/test_scheduler.py`

Build the executable graph and run it. This is the milestone's core and the open-question-#13 resolution: a real compiled `StateGraph` with worktree-creating nodes runs end-to-end.

- [ ] **Step 1: Extract `wire_edges` in the compiler (refactor; keep behavior)**

In `orchestrator/compile/compiler.py`, extract the START/END + outgoing-edge-grouping logic into a reusable helper and have `to_state_graph` call it. Add:

```python
def wire_edges(builder, ir: GraphIR, *, router=None) -> None:
    """Wire START/END + step edges onto `builder` from the IR.

    Conditional sources get a single router over their targets. `router` is a
    callable (source, targets) -> routing-fn; if None, a forward-only router
    (always the first target) is used. M4 supplies a verdict-aware router.
    """
    for entry in ir.entrypoints:
        builder.add_edge(START, entry)
    for terminal in ir.terminals:
        builder.add_edge(terminal, END)

    outgoing: dict[str, list] = {}
    for edge in ir.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    for source, edges in outgoing.items():
        if any(e.conditional for e in edges):
            targets = [e.target for e in edges]
            if router is not None:
                route_fn = router(source, targets)
            else:
                def route_fn(state, _targets=targets):
                    return _targets[0]
            builder.add_conditional_edges(source, route_fn, targets)
        else:
            for edge in edges:
                builder.add_edge(edge.source, edge.target)
```

Then simplify `to_state_graph` to:

```python
def to_state_graph(pipeline: Pipeline, ir: GraphIR):
    builder = StateGraph(RunState)
    for node in ir.nodes:
        builder.add_node(node, _placeholder_node)
    wire_edges(builder, ir)
    return builder.compile()
```

- [ ] **Step 2: Confirm the compiler refactor is behavior-preserving**

Run: `uv run --extra dev python -m pytest tests/unit/test_compiler.py tests/integration/test_example_compiles.py -v`
Expected: PASS unchanged (the golden-graph test still sees the same nodes/edges).

- [ ] **Step 3: Write the failing scheduler integration test**

Create `tests/integration/test_scheduler.py`:

```python
import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import SPAN_STEP, configure_tracing
from orchestrator.runtime.scheduler import DeterministicScheduler
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


async def test_linear_pipeline_runs_end_to_end(tmp_path, monkeypatch):
    # Route classify -> classify.ndjson (JSON kind), other steps -> default.ndjson.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    configure_tracing(exporter=InMemorySpanExporter())

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    pipeline = ws.pipelines["triage"]  # added in Task 9
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])

    scheduler = DeterministicScheduler(ws, adapter, repo)
    ctx = await scheduler.run(pipeline, {"task": "add a widget"}, run_id="run1")

    # all three steps produced artifacts
    assert set(ctx.artifacts) == {"classify", "plan", "implement"}
    assert ctx.artifacts["classify"].output_data == {"kind": "feature"}
    assert ctx.artifacts["implement"].is_error is False
    # cost rolled up across steps
    assert ctx.total_cost_usd > 0
```

> This test depends on Task 9 adding the `triage` pipeline. If executing strictly in order, write this test now (red) and bring it green after Task 9; the dependency-correct execution is captured in the Execution Handoff. To keep this task self-green, **do Task 9's `triage.yaml` creation before finishing this task** (just the file; the CLI part stays in Task 9).

- [ ] **Step 4: Implement the scheduler + controller**

Create `orchestrator/runtime/scheduler.py`:

```python
"""DeterministicScheduler: the declarative Controller (spec §6).

Builds an executable LangGraph StateGraph from the pipeline IR with real node
closures and invokes it. A single shared RunContext is threaded through nodes.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import StateGraph

from orchestrator.compile.compiler import wire_edges
from orchestrator.compile.ir import build_ir
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.observability.spans import SPAN_RUN, get_tracer
from orchestrator.runtime.executors import run_agent_step, run_task_step
from orchestrator.runtime.state import GraphState, RunContext


class DeterministicScheduler:
    def __init__(self, workspace: Workspace, adapter: HarnessAdapter, repo: Path) -> None:
        self.workspace = workspace
        self.adapter = adapter
        self.repo = Path(repo)

    def _make_node(self, pipeline: Pipeline, step: Step):
        async def node(state: GraphState) -> dict:
            ctx = state["ctx"]
            if step.type == StepType.task:
                await run_task_step(
                    self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self.adapter
                )
            elif step.type == StepType.agent:
                await run_agent_step(
                    self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self.adapter
                )
            else:  # gate
                raise NotImplementedError(f"gate step '{step.id}' runs in M5")
            return {"ctx": ctx}

        return node

    def _build(self, pipeline: Pipeline):
        ir = build_ir(pipeline)
        by_id = {s.id: s for s in pipeline.steps}
        builder = StateGraph(GraphState)
        for node_id in ir.nodes:
            builder.add_node(node_id, self._make_node(pipeline, by_id[node_id]))
        wire_edges(builder, ir)  # M3: forward-only router for conditional edges
        return builder.compile()

    async def run(
        self, pipeline: Pipeline, inputs: dict[str, str], run_id: str
    ) -> RunContext:
        ctx = RunContext(run_id=run_id, inputs=dict(inputs))
        graph = self._build(pipeline)
        tracer = get_tracer()
        with tracer.start_as_current_span(SPAN_RUN) as run_span:
            run_span.set_attribute("run.id", run_id)
            run_span.set_attribute("pipeline", pipeline.name)
            await graph.ainvoke({"ctx": ctx})
        return ctx
```

Create `orchestrator/runtime/controller.py`:

```python
"""The mode seam (spec §6): declarative now, agentic specced-not-built."""

from __future__ import annotations

from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Mode
from orchestrator.harness.adapter import HarnessAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler


def make_controller(
    mode: Mode, workspace: Workspace, adapter: HarnessAdapter, repo: Path
) -> DeterministicScheduler:
    if mode == Mode.agentic:
        raise NotImplementedError("agentic mode (AgenticSupervisor) is specced, not built")
    return DeterministicScheduler(workspace, adapter, repo)
```

Update `orchestrator/runtime/__init__.py`:

```python
"""Runtime layer: run state + step executors + scheduler (spec §6)."""

from orchestrator.runtime.controller import make_controller
from orchestrator.runtime.executors import run_agent_step, run_task_step
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import Artifact, GraphState, RunContext

__all__ = [
    "Artifact", "GraphState", "RunContext",
    "run_agent_step", "run_task_step",
    "DeterministicScheduler", "make_controller",
]
```

- [ ] **Step 5: Run the tests + full suite** (after Task 9's `triage.yaml` exists)

Run: `uv run --extra dev python -m pytest tests/integration/test_scheduler.py -v`
Expected: PASS — the linear pipeline runs through the real compiled StateGraph end-to-end.

Run: `uv run --extra dev python -m pytest && uv run --extra dev ruff check .`
Expected: full suite green, lint clean.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/compile/compiler.py orchestrator/runtime/scheduler.py orchestrator/runtime/controller.py orchestrator/runtime/__init__.py tests/integration/test_scheduler.py
git commit -m "feat(m3): DeterministicScheduler executes the compiled StateGraph end-to-end"
```

---

## Task 9: Demo pipeline + CLI full-pipeline run + verification

**Files:**
- Create: `examples/feature-pipeline/.orchestrator/pipelines/triage.yaml`
- Modify: `orchestrator/cli.py`
- Test: `tests/integration/test_run_cli.py` (modify/add)
- Test: `tests/unit/test_cli.py` (adjust if needed)

Add the linear demo pipeline and make `orch run <pipeline> --task <t>` (no `--only`) execute the whole thing via the controller. Keep `--only` for single-step runs.

- [ ] **Step 1: Create the demo pipeline**

Create `examples/feature-pipeline/.orchestrator/pipelines/triage.yaml`:

```yaml
# Linear M3 demo: classify (task) -> plan (agent) -> implement (agent).
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
```

Confirm it compiles:

Run: `uv run --extra dev python -c "from orchestrator.config.loader import load_workspace; from orchestrator.compile.compiler import compile_pipeline; ws=load_workspace('examples/feature-pipeline/.orchestrator'); r=compile_pipeline(ws,'triage'); print(r.ok, r.errors)"`
Expected: `True []`

- [ ] **Step 2: Write the failing CLI test**

In `tests/integration/test_run_cli.py`, add a full-pipeline run test (keep the existing `--only` and `--only` -required tests, but the "required in M2" test must change — see Step 4):

```python
def test_run_full_pipeline(tmp_path, monkeypatch):
    import shutil

    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))

    result = runner.invoke(
        app,
        ["run", "triage", "--task", "add a widget", "--root", str(dest), "--repo", str(repo)],
    )
    assert result.exit_code == 0, result.output
    assert "classify" in result.output
    assert "plan" in result.output
    assert "implement" in result.output
    assert "feature" in result.output  # classify output_data surfaced
```

Ensure `SCRIPTS` is defined in the test module (mirror the other integration tests).

- [ ] **Step 3: Run to verify failure**

Run: `uv run --extra dev python -m pytest tests/integration/test_run_cli.py -v`
Expected: the full-pipeline test FAILS (run still requires `--only`).

- [ ] **Step 4: Implement full-pipeline run in the CLI**

In `orchestrator/cli.py`, update the `run` command so that without `--only` it runs the whole pipeline via the controller. Replace the early `if not only: ... Exit(2)` guard and the single-step tail. Add imports at the top:

```python
from orchestrator.config.schemas import Mode
from orchestrator.runtime.controller import make_controller
```

Replace the body of `run` after workspace/pipeline lookup with:

```python
    configure_tracing(exporter=None)
    adapter = ClaudeCodeCLIAdapter()  # honors $ORCH_CLAUDE_BIN
    run_id = uuid.uuid4().hex[:8]

    # Single-step mode (M2 behavior, still supported).
    if only:
        step = next((s for s in pipe.steps if s.id == only), None)
        if step is None:
            typer.echo(f"error: pipeline '{pipeline}' has no step '{only}'.")
            raise typer.Exit(1)
        if step.type is not StepType.agent:
            typer.echo(
                f"error: step '{only}' is type '{step.type.value}'; --only runs agent steps."
            )
            raise typer.Exit(2)
        ctx = RunContext(run_id=run_id, inputs={"task": task})

        async def _one():
            tracer = get_tracer()
            with tracer.start_as_current_span(SPAN_RUN) as run_span:
                run_span.set_attribute("run.id", run_id)
                run_span.set_attribute("pipeline", pipeline)
                return await run_agent_step(workspace, pipe, step, ctx, repo=repo, adapter=adapter)

        artifact = asyncio.run(_one())
        _print_artifact(artifact, run_id)
        if artifact.is_error:
            raise typer.Exit(1)
        return

    # Full-pipeline mode (M3).
    try:
        controller = make_controller(pipe.mode, workspace, adapter, repo)
    except NotImplementedError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(2) from exc

    ctx = asyncio.run(controller.run(pipe, {"task": task}, run_id))

    typer.echo(f"run {run_id}: pipeline '{pipeline}' ({len(ctx.artifacts)} steps)")
    any_error = False
    for step in pipe.steps:
        art = ctx.artifacts.get(step.id)
        if art is None:
            continue  # not reached on this path (e.g. conditional branch)
        any_error = any_error or art.is_error
        _print_artifact(art, run_id, brief=True)
    typer.echo(f"total cost: ${ctx.total_cost_usd:.4f}")
    if any_error:
        raise typer.Exit(1)
```

Add a small shared printer helper near the top of the module (after `app = ...`):

```python
def _print_artifact(artifact, run_id, *, brief: bool = False) -> None:
    status_word = "ERROR" if artifact.is_error else "OK"
    typer.echo(f"{status_word}: step '{artifact.step_id}' (run {run_id})")
    if artifact.branch:
        typer.echo(f"  branch: {artifact.branch}")
    typer.echo(f"  cost: ${artifact.cost_usd:.4f} ({artifact.tokens} tokens)")
    if artifact.output_data:
        typer.echo(f"  output_data: {artifact.output_data}")
    if artifact.diff:
        typer.echo(f"  diff: {len(artifact.diff.splitlines())} line(s) changed")
    if not brief:
        typer.echo("---- output ----")
        typer.echo(artifact.output)
```

Keep the `--only` option definition; just drop the "required" guard. Ensure `RunContext`, `get_tracer`, `SPAN_RUN`, `run_agent_step`, `StepType` imports remain.

- [ ] **Step 5: Adjust the M2 "requires --only" test**

In `tests/integration/test_run_cli.py` (or wherever it lives), the M2 test `test_run_requires_only_in_m2` asserted exit code 2 when `--only` was omitted. That behavior is gone. Replace it with the full-pipeline test from Step 2 (or delete the obsolete assertion). Likewise check `tests/unit/test_cli.py` for a stale assertion and update it to reflect that `run` without `--only` now runs the full pipeline (you can point it at a pipeline + assert it requires a valid pipeline / errors cleanly on a bad one, rather than asserting "only" is required).

- [ ] **Step 6: Full verification**

Run: `uv run --extra dev python -m pytest`
Expected: ALL tests green (M1 + M2 + M3).

Run: `uv run --extra dev ruff check .`
Expected: clean.

Manual smoke (the headline M3 capability — a full pipeline against the fake harness):

```bash
PY=$(uv run python -c 'import sys; print(sys.executable)')
ORCH_CLAUDE_BIN="$PY tests/fixtures/fake_harness/fake_harness.py" \
ORCH_FAKE_SCRIPT_DIR="tests/fixtures/fake_harness/scripts" \
uv run orch run triage --task "add a widget" --root examples/feature-pipeline/.orchestrator --repo .
```

Expected: prints `run <id>: pipeline 'triage' (3 steps)`, an `OK` line per step (classify shows `output_data: {'kind': 'feature'}`), and a total cost line. Then confirm `git status` shows nothing stray (worktrees auto-removed; `.worktrees/` is gitignored).

- [ ] **Step 7: Commit**

```bash
git add examples/feature-pipeline/.orchestrator/pipelines/triage.yaml orchestrator/cli.py tests/integration/test_run_cli.py tests/unit/test_cli.py
git commit -m "feat(m3): orch run executes a full pipeline via the controller + triage demo"
```

---

## Self-review (against spec §6, §12 M3 + the deferred follow-ups)

**Spec coverage check:**

- **M3 = "full DAG executor + task step: `classify → plan → implement` with `success_criteria`/retry."** → Task 8 (scheduler executes the compiled StateGraph), Task 7 (task step), Task 6 (success_criteria/retry), Task 9 (the `classify → plan → implement` demo + CLI). ✅
- **Compile → executable StateGraph (spec §6).** `wire_edges` shared by `to_state_graph` (compile) + scheduler (execute); scheduler `ainvoke`s real nodes. ✅
- **One typed `RunContext` threaded through the graph (spec §6).** `GraphState = {"ctx": RunContext}`; nodes mutate + return it; cost rolls up. ✅ (linear-only; parallel reducers deferred, noted)
- **AgentStep lifecycle step 6 — success_criteria + inner retry loop (spec §6).** Implemented in `run_agent_step`; re-prompts with failure output; bounded by `max_retries`; cost summed. ✅ (test-count gate is M4)
- **task executor = cheap LLM glue (spec §3/§4).** `run_task_step`: read-only, no worktree, output parsed vs `output_schema`. ✅
- **Controller seam (spec §6).** `make_controller(mode, ...)` returns `DeterministicScheduler`; agentic raises. ✅
- **Typed I/O references + dataflow (spec §4).** `{{ ... }}` runtime templating + compile-time validation with the ancestor requirement. ✅
- **Folded-in deferred items:** M2 follow-up — drain stderr (Task 1); M1 follow-ups — `{{...}}` syntax decision (resolved by user), ancestor requirement on typed-I/O, deep-field rejection, drop cycle-masking guard (Task 5). ✅
- **Open question #13.** Real compiled StateGraph executes worktree steps end-to-end (Task 8) → resolved for linear DAG; cyclic on_reject execution validated in M4. ✅ (note in follow-ups)

**Deliberately deferred (noted in-task):** verdict-driven `on_reject` routing + test-count gate (M4); `gate`/HITL + SQLite checkpointer + merge→PR (M5); knowledge injection + MCP + OpenCode + `orch status` (M6); parallel/best-of-n + state reducers + `AgenticSupervisor` (later); retain-worktree-on-failure; real `--resume` re-prompt across retries (the inner loop re-prompts the same worktree, which is what matters for MVP correctness).

**Type consistency check:** `Artifact` (now with `output_data`) used identically in `template.py`, `executors.py`, `scheduler.py`, `cli.py`. `RunContext` signature unchanged; `run_agent_step` signature unchanged from M2 (only internals). `GraphState` used in `scheduler.py` + `state.py`. `wire_edges` signature shared by `compiler.py` + `scheduler.py`. `make_controller` returns the scheduler used by `cli.py`. `render_template(template, inputs, artifacts)` called consistently from `executors.py`. ✅

**Placeholder scan:** every code step contains complete code; no TBD/TODO. ✅

---

## Execution handoff

**Dependency-correct execution order:**

```
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
```

Two cross-task notes:
- **Task 8's** scheduler integration test needs the **`triage.yaml`** that **Task 9 Step 1** creates. Either create `triage.yaml` during Task 8 (then the rest of Task 9 is just the CLI), or write Task 8's test red and green it after Task 9's Step 1. Recommended: create `triage.yaml` as the first action of Task 8.
- **Task 2's** fake-harness changes are backward-compatible (new env vars only), so M2 tests keep passing; **Task 5** changes the reference syntax repo-wide, so re-run the full suite after it and fix any straggler `<...>` assertions.

This plan is intended for **superpowers:subagent-driven-development**: one fresh implementer subagent per task, spec-compliance then code-quality review between tasks (with dedicated review on Tasks 6 and 8 — the retry loop and the StateGraph execution), in an isolated worktree, finishing by merging to `orchestrator-design` (the established M-series workflow).
