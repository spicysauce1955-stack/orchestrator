# M6c — Orchestrator Agent + Span-Emitting Message Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the first-class **orchestrator agent** as run-owner doing the shared coordination (spec §7 MVP scope: **classify**, **relay the review verdict to the implementer on loop-back**, and **answer worker questions**), all over a **message bus where every message is an OTel span** (hub-and-spoke; the coordination board is the in-memory derived view).

**Architecture:** A coordination-layer design (not a new control-flow paradigm): the existing `DeterministicScheduler` stays the executor and calls into an injected `OrchestratorAgent` at the seams it already has. (1) Non-merge `task` steps run *through* the agent (`agent.run_task`), which delegates to the unchanged `run_task_step` using the orchestrator's own Role and emits a `classify` message span. (2) On an `on_reject` loop-back, the `_router` calls `agent.relay_verdict`, which emits a `verdict` message span and stashes the reviewer's feedback in `RunContext` so the re-run implementer sees it in its prompt. (3) After an agent step's harness result, if it carries a structured `question` (the worker is *asking*, not failing), `run_agent_step` calls the (duck-typed) `agent.answer`, emits `question`/`answer` spans, and re-prompts the **same worktree** with the answer appended — bounded by a new per-step `max_questions` cap. The agent and bus auto-construct with safe defaults inside the scheduler, so every existing call site and all 224 prior tests keep working unchanged.

**Tech Stack:** Python 3.11, async subprocess, Pydantic v2, LangGraph 1.x, OpenTelemetry, Typer, pytest-asyncio. Package manager: **uv** (`uv run --extra dev python -m pytest`, `uv run --extra dev ruff check .`). NEVER system pip.

**This is M6c — the third M6 sub-milestone.** M6a = OpenCode adapter + registry; M6b = knowledge provider. M6c is the orchestrator agent + message bus ONLY. **Explicitly NOT in M6c:** agentic routing (the specced `AgenticSupervisor`), the user *conversing* with the agent, direct worker↔worker (A2A) messaging, `orch status`'s rendered view, and safety-baseline polish (those are M6d+).

## Locked design decisions (from the M6c brainstorm, 2026-06-07)

- **Agent shape = coordination layer.** `OrchestratorAgent` is a plain object owning the run goal + pipeline; it delegates LLM calls to a harness via its own Role. The `DeterministicScheduler` remains the executor.
- **Worker Q&A = structured question via `output_schema`.** A worker step opts in with `max_questions > 0` and an `output_schema` carrying a `question` field. The agent answers (LLM via its Role); the worker is re-prompted in the **same worktree** (partial progress preserved, mirroring the `success_criteria` retry), bounded by `max_questions`.
- **Verdict relay feeds the implementer.** On loop-back the relayed reviewer output is injected into the implementer's next prompt (closing the loop the spec describes), in addition to emitting a span.

## Grounding facts (verified against the current tree before writing this plan)

- `orchestrator/runtime/scheduler.py`: `_make_node` dispatches task→`run_task_step` (or `run_merge_step` when `step.merge_strategy`), agent→`run_agent_step`, gate→`run_gate_step`. `_router` reads the review artifact's `output_data["verdict"]` and returns `reject_target` when `verdict == Verdict.REJECT` and attempts remain. `run()` builds the graph and `ainvoke`s it under a `SPAN_RUN` span.
- `orchestrator/runtime/executors.py`: `run_agent_step` resolves `role`/`caps`, creates a worktree, runs an inner retry loop calling `_drive_harness(adapter, caps, worktree.path, prompt, step.output_schema, tracer, mcp_servers=...)`, then `parse_output(agg.result_text, step.output_schema)`. `run_task_step` is read-only, no worktree, calls `_drive_harness(adapter, caps, Path(repo), prompt, schema, tracer)`. `_render_prompt(step, role_name, ctx)` renders `{{...}}`. `_drive_harness` is module-private but importable.
- `orchestrator/runtime/state.py`: `RunContext` is a dataclass (fields incl. `attempts`, `gate_decisions`); it is allowlisted in `CHECKPOINT_SERDE_MODULES`. `Artifact` has `output_data: dict | None`.
- `orchestrator/observability/spans.py`: module-level provider; `SPAN_RUN/STEP/SESSION/TOOL_CALL/FILE_EDIT` constants; `get_tracer()`; tests inject an `InMemorySpanExporter` via `configure_tracing(exporter)`.
- `orchestrator/eval/verdict.py`: `Verdict.APPROVE/REJECT`; `parse_output(output, schema)` returns `(data, is_error)` — it only *validates* enum fields; a non-enum field like `question` declared `"string"` is passed through from a JSON object untouched.
- `orchestrator/config/schemas.py`: `Step` is a strict (extra-forbid) model with `max_retries: int = 0`, `output_schema: dict | None`, etc. Adding `max_questions: int = 0` is additive and safe. `Role` has `harness`, `permissions`, etc.
- `orchestrator/runtime/controller.py`: `make_controller(mode, workspace, adapter, repo, *, checkpoint_db=...)` → `DeterministicScheduler(...)`. `orchestrator/cli.py` builds `HarnessRegistry.from_env()` and calls `make_controller(...)`.
- Fake harness (`tests/fixtures/fake_harness/fake_harness.py`): records argv to `$ORCH_FAKE_ARGV`; streams the NDJSON at `$ORCH_FAKE_SCRIPT` (or `$ORCH_FAKE_SCRIPT_DIR`/`<keyword>`); supports `$ORCH_FAKE_STATE` numbered variants (e.g. `review.1`/`review.2`) for "first call vs second call" behavior. The prompt is passed in argv (after `-p`), so a test can assert prompt content by reading the argv file.

> **Circular-import rule (critical):** `executors.py` must NOT import `orchestrator.agents.*`. `run_agent_step` receives the agent as an optional **duck-typed** parameter and calls `await agent.answer(...)` on it. The dependency edge is one-directional: `agents/ → executors` (for `_drive_harness`) and `scheduler → {executors, agents}`.

---

## File Structure

- `orchestrator/agents/__init__.py` (NEW) — empty package marker.
- `orchestrator/agents/message_bus.py` (NEW) — `Message` dataclass + `MessageBus` (emits one `SPAN_MESSAGE` span per `send`, appends to an in-memory `log`).
- `orchestrator/agents/orchestrator_agent.py` (NEW) — `OrchestratorAgent` (`run_task`, `relay_verdict`, `answer`; default Role; resolves its adapter via the registry).
- `orchestrator/observability/spans.py` (MODIFY) — add `SPAN_MESSAGE = "message"`.
- `orchestrator/runtime/state.py` (MODIFY) — add `RunContext.relayed_feedback: dict[str, str]`.
- `orchestrator/config/schemas.py` (MODIFY) — add `Step.max_questions: int = 0`.
- `orchestrator/runtime/executors.py` (MODIFY) — `run_agent_step` gains an optional `agent` param + the bounded question loop + relayed-feedback prompt injection.
- `orchestrator/runtime/scheduler.py` (MODIFY) — construct/accept `MessageBus` + `OrchestratorAgent`; route non-merge task steps through `agent.run_task`; pass `agent` to `run_agent_step`; call `agent.relay_verdict` in `_router` on reject.
- `orchestrator/runtime/controller.py` + `orchestrator/cli.py` (MODIFY) — no behavior change required (scheduler auto-constructs defaults); confirm pass-through.
- `examples/feature-pipeline/.orchestrator/roles/orchestrator.yaml` (NEW) — the reserved orchestrator role.
- `examples/feature-pipeline/.orchestrator/pipelines/qa-demo.yaml` (NEW) — a pipeline whose implementer asks one question.
- `tests/fixtures/fake_harness/scripts/question.1.ndjson`, `question.2.ndjson` (NEW) — ask-then-answer fake scripts.
- Tests (NEW): `tests/unit/test_message_bus.py`, `tests/integration/test_orchestrator_agent.py`, `tests/unit/test_relayed_feedback.py`, `tests/integration/test_worker_questions.py`, `tests/integration/test_agent_in_scheduler.py`.
- `docs/superpowers/notes/m6c-orchestrator-agent-followups.md` (NEW).

---

## Task 1: Message bus (span per message)

**Files:**
- Create: `orchestrator/agents/__init__.py` (empty)
- Create: `orchestrator/agents/message_bus.py`
- Modify: `orchestrator/observability/spans.py` (add `SPAN_MESSAGE`)
- Test: `tests/unit/test_message_bus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_message_bus.py
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.agents.message_bus import Message, MessageBus
from orchestrator.observability.spans import configure_tracing


def _exporter():
    exp = InMemorySpanExporter()
    configure_tracing(exp)
    return exp


def test_send_returns_message_and_appends_to_log():
    bus = MessageBus()
    msg = bus.send("orchestrator", "implement", "verdict", "reject: fix the bug")
    assert msg == Message("orchestrator", "implement", "verdict", "reject: fix the bug")
    assert bus.log == [msg]


def test_send_emits_one_message_span_with_attributes():
    exp = _exporter()
    bus = MessageBus()
    bus.send("implement", "orchestrator", "question", "which db?")
    spans = [s for s in exp.get_finished_spans() if s.name == "message"]
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert attrs["msg.from"] == "implement"
    assert attrs["msg.to"] == "orchestrator"
    assert attrs["msg.kind"] == "question"


def test_log_preserves_order():
    bus = MessageBus()
    bus.send("orchestrator", "run", "classify", "feature")
    bus.send("implement", "orchestrator", "question", "q")
    bus.send("orchestrator", "implement", "answer", "a")
    assert [m.kind for m in bus.log] == ["classify", "question", "answer"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_message_bus.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.agents.message_bus`).

- [ ] **Step 3: Implement**

Add to `orchestrator/observability/spans.py` (next to the other constants):

```python
SPAN_MESSAGE = "message"
```

Create `orchestrator/agents/__init__.py` (empty). Create `orchestrator/agents/message_bus.py`:

```python
"""The orchestrator's message bus (spec §7): hub-and-spoke, every message a span.

Communication between the orchestrator agent and workers (and worker↔worker,
mediated through the orchestrator in the MVP) flows through `MessageBus.send`,
which emits one OTel `message` span per message and appends to an in-memory log
(the "coordination board" derived view). The bus holds no transport — workers
are driven by the scheduler; this records and traces the coordination.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.observability.spans import SPAN_MESSAGE, get_tracer


@dataclass(frozen=True)
class Message:
    frm: str
    to: str
    kind: str  # "classify" | "verdict" | "question" | "answer"
    body: str


class MessageBus:
    def __init__(self) -> None:
        self.log: list[Message] = []

    def send(self, frm: str, to: str, kind: str, body: str) -> Message:
        msg = Message(frm, to, kind, body)
        with get_tracer().start_as_current_span(SPAN_MESSAGE) as span:
            span.set_attribute("msg.from", frm)
            span.set_attribute("msg.to", to)
            span.set_attribute("msg.kind", kind)
        self.log.append(msg)
        return msg
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_message_bus.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/agents/__init__.py orchestrator/agents/message_bus.py orchestrator/observability/spans.py tests/unit/test_message_bus.py
git commit -m "feat(m6c): message bus — one OTel span per orchestrator message + in-memory board"
```

---

## Task 2: OrchestratorAgent (run_task, relay_verdict, answer)

**Files:**
- Create: `orchestrator/agents/orchestrator_agent.py`
- Test: `tests/integration/test_orchestrator_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_orchestrator_agent.py
import sys
from pathlib import Path

from orchestrator.agents.message_bus import MessageBus
from orchestrator.agents.orchestrator_agent import OrchestratorAgent
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _agent(tmp_path):
    ws = Workspace(config=Config())
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    bus = MessageBus()
    return OrchestratorAgent(workspace=ws, registry=reg, bus=bus, repo=tmp_path), bus, ws


def test_default_role_is_read_only_claude(tmp_path):
    agent, _, _ = _agent(tmp_path)
    assert agent.role.harness == Harness.claude_code
    assert agent.role.permissions.value == "read-only"


async def test_run_task_records_artifact_and_emits_classify(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    agent, bus, ws = _agent(tmp_path)
    ctx = RunContext(run_id="r1", inputs={"task": "add a flag"}, pipeline_name="p")
    step = Step(id="classify", type=StepType.task,
                prompt='Classify {{task}}. Reply JSON {"kind":"feature"}.',
                output_schema={"kind": "enum[bugfix,feature,refactor]"})
    pipe = Pipeline(name="p", steps=[step])
    art = await agent.run_task(pipe, step, ctx)
    assert ctx.artifacts["classify"] is art
    assert [m.kind for m in bus.log] == ["classify"]
    assert bus.log[0].frm == "orchestrator" and bus.log[0].to == "run"


async def test_answer_drives_harness_and_emits_question_then_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    agent, bus, ws = _agent(tmp_path)
    answer = await agent.answer("Which database should I use?", from_step="implement")
    assert isinstance(answer, str) and answer  # non-empty answer text
    assert [m.kind for m in bus.log] == ["question", "answer"]
    assert bus.log[0].frm == "implement" and bus.log[0].to == "orchestrator"
    assert bus.log[1].frm == "orchestrator" and bus.log[1].to == "implement"


def test_relay_verdict_records_feedback_and_emits_span(tmp_path):
    agent, bus, ws = _agent(tmp_path)
    ctx = RunContext(run_id="r1", pipeline_name="p")
    agent.relay_verdict("reject: missing tests", to_step="implement", ctx=ctx)
    assert ctx.relayed_feedback["implement"] == "reject: missing tests"
    assert bus.log[0].kind == "verdict"
    assert bus.log[0].to == "implement"
```

> IMPLEMENTER NOTE: `RunContext.relayed_feedback` is added in Task 3. To keep Task 2 self-contained and green NOW, the `test_relay_verdict_*` test depends on that field — so add the `relayed_feedback: dict[str, str] = field(default_factory=dict)` field to `RunContext` as part of THIS task too (it's a one-line additive change; Task 3 then *consumes* it in `run_agent_step`). If you prefer strict task isolation, instead have `relay_verdict` write to `ctx.relayed_feedback` and add the field here; do NOT wire prompt injection yet (that's Task 3).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_orchestrator_agent.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.agents.orchestrator_agent`).

- [ ] **Step 3: Implement**

First add the field to `orchestrator/runtime/state.py` `RunContext` (additive; needed by `relay_verdict`):

```python
    relayed_feedback: dict[str, str] = field(default_factory=dict)
```
(Place it next to `gate_decisions`. `field` is already imported.)

Create `orchestrator/agents/orchestrator_agent.py`:

```python
"""The orchestrator agent (spec §7): first-class run-owner, coordination only.

MVP scope = shared coordination: run the cheap `classify`/task glue, relay the
review verdict to the implementer on loop-back, and answer worker questions.
It is a coordination LAYER, not a router: the DeterministicScheduler stays the
executor and calls into this agent at its existing seams. LLM calls go through
the orchestrator's own Role (default: read-only Claude Code). Every coordination
action is recorded on the MessageBus as an OTel span.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.agents.message_bus import MessageBus
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Harness, PermissionProfile, Pipeline, Role, Step
from orchestrator.eval.verdict import parse_output
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.executors import _drive_harness, run_task_step
from orchestrator.runtime.state import Artifact, RunContext
from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities

ORCHESTRATOR_ROLE = "orchestrator"


def _default_orchestrator_role() -> Role:
    """Read-only Claude Code role used when the workspace defines no orchestrator."""
    return Role(name=ORCHESTRATOR_ROLE, harness=Harness.claude_code,
                permissions=PermissionProfile.read_only)


class OrchestratorAgent:
    def __init__(self, *, workspace: Workspace, registry: HarnessRegistry,
                 bus: MessageBus, repo: Path) -> None:
        self.workspace = workspace
        self.registry = registry
        self.bus = bus
        self.repo = Path(repo)
        self.role = workspace.roles.get(ORCHESTRATOR_ROLE) or _default_orchestrator_role()

    def _adapter(self):
        return self.registry.adapter_for(self.role.harness)

    async def run_task(self, pipeline: Pipeline, step: Step, ctx: RunContext) -> Artifact:
        """Run a non-merge task step (the orchestrator's coordination glue, e.g.
        classify) via the unchanged run_task_step, then record a `classify` msg."""
        art = await run_task_step(
            self.workspace, pipeline, step, ctx, repo=self.repo, adapter=self._adapter()
        )
        self.bus.send("orchestrator", "run", "classify", art.output)
        return art

    def relay_verdict(self, verdict_body: str, *, to_step: str, ctx: RunContext) -> None:
        """On loop-back: record the reviewer's verdict for the implementer's next
        prompt and emit an orch→worker `verdict` message span."""
        ctx.relayed_feedback[to_step] = verdict_body
        self.bus.send("orchestrator", to_step, "verdict", verdict_body)

    async def answer(self, question: str, *, from_step: str) -> str:
        """Answer a worker's question (LLM via the orchestrator's Role). Emits a
        worker→orch `question` span then an orch→worker `answer` span."""
        self.bus.send(from_step, "orchestrator", "question", question)
        caps: ResolvedCaps = resolve_capabilities(self.role, self.workspace)
        prompt = (
            "A worker agent is blocked and asked the orchestrator a question.\n"
            f"Worker: {from_step}\nQuestion: {question}\n"
            "Answer concisely so the worker can proceed."
        )
        from orchestrator.observability.spans import get_tracer
        agg = await _drive_harness(self._adapter(), caps, self.repo, prompt, None, get_tracer())
        answer_text = agg.output or agg.result_text
        self.bus.send("orchestrator", from_step, "answer", answer_text)
        return answer_text
```

> IMPLEMENTER NOTE: confirm `PermissionProfile.read_only` is the correct enum member name in `orchestrator/config/schemas.py` (it is referenced by other roles as `read-only` in YAML; the Python member is likely `read_only`). Confirm `resolve_capabilities(role, workspace)` and `ResolvedCaps` import paths. `_drive_harness` returns an `_Aggregate` with `.output`, `.result_text`, `.cost_usd`, `.tokens`, `.is_error` — verify those attribute names in `executors.py` and adjust if different.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_orchestrator_agent.py -v`
Expected: PASS. (If `classify.ndjson`/`plan.ndjson` field names differ, inspect `tests/fixtures/fake_harness/scripts/` and adjust the test's script choice — both must yield a Done/result. `classify.ndjson` should emit a JSON result like `{"kind":"feature"}`.)

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/agents/orchestrator_agent.py orchestrator/runtime/state.py tests/integration/test_orchestrator_agent.py
git commit -m "feat(m6c): OrchestratorAgent — run_task/relay_verdict/answer over the message bus"
```

---

## Task 3: Relayed feedback reaches the implementer's prompt

**Files:**
- Modify: `orchestrator/runtime/executors.py` (`run_agent_step` prepends relayed feedback, then clears it)
- Test: `tests/unit/test_relayed_feedback.py`

- [ ] **Step 1: Write the failing test** (drives a real agent step via the fake harness; asserts the relayed text reached the harness prompt by reading the recorded argv)

```python
# tests/unit/test_relayed_feedback.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Role, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


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


def _ws():
    ws = Workspace(config=Config())
    ws.roles = {"implementer": Role(name="implementer", harness=Harness.claude_code)}
    return ws


async def test_relayed_feedback_is_injected_and_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    ws = _ws()
    repo = _repo(tmp_path)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", inputs={"task": "x"}, pipeline_name="p")
    ctx.relayed_feedback["implement"] = "reject: add a test for the new flag"
    step = Step(id="implement", role="implementer", type=StepType.agent, prompt="do {{task}}")
    await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx, repo=repo, adapter=adapter)
    argv = (tmp_path / "argv.txt").read_text()
    assert "add a test for the new flag" in argv      # relayed feedback reached the prompt
    assert "implement" not in ctx.relayed_feedback      # consumed (one-shot)


async def test_no_relayed_feedback_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    ws = _ws()
    repo = _repo(tmp_path)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", inputs={"task": "x"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent, prompt="do {{task}}")
    await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx, repo=repo, adapter=adapter)
    argv = (tmp_path / "argv.txt").read_text()
    assert "Reviewer feedback" not in argv
```

> IMPLEMENTER NOTE: `edit.ndjson` is the fake script that emits a file edit + a Done (used by M6b's Task 8 test). Confirm it exists under `tests/fixtures/fake_harness/scripts/`; if not, list the dir and choose a script that yields a Done without `success_criteria` needs.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_relayed_feedback.py -v`
Expected: FAIL (relayed text not in argv; field not consumed).

- [ ] **Step 3: Implement**

In `orchestrator/runtime/executors.py` `run_agent_step`, where `base_prompt` is computed (currently `base_prompt = _render_prompt(step, step.role, ctx)`), append the relayed feedback and consume it:

```python
            base_prompt = _render_prompt(step, step.role, ctx)
            relayed = ctx.relayed_feedback.pop(step.id, None)
            if relayed:
                base_prompt = (
                    f"{base_prompt}\n\n[Reviewer feedback relayed by the orchestrator]:\n"
                    f"{relayed}\nAddress it in this attempt."
                )
```

(Use `.pop(step.id, None)` so the feedback is one-shot — consumed for this loop-back and not re-applied on later steps. This runs once before the retry loop, so all `success_criteria` retries within this attempt see the feedback.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_relayed_feedback.py -v`
Then full suite (back-compat): `uv run --extra dev python -m pytest -q`.
Expected: PASS (baseline 224 + 2 new).

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/executors.py tests/unit/test_relayed_feedback.py
git commit -m "feat(m6c): inject relayed reviewer feedback into the implementer's next prompt"
```

---

## Task 4: Worker question loop (max_questions + agent answer)

**Files:**
- Modify: `orchestrator/config/schemas.py` (add `Step.max_questions`)
- Modify: `orchestrator/runtime/executors.py` (`run_agent_step` gains `agent=None` + the bounded question loop)
- Create: `tests/fixtures/fake_harness/scripts/question.1.ndjson`, `question.2.ndjson`
- Test: `tests/integration/test_worker_questions.py`

- [ ] **Step 1: Add the schema field**

In `orchestrator/config/schemas.py` `Step`, add next to `max_retries`:

```python
    max_questions: int = 0
```

- [ ] **Step 2: Create the fake scripts**

`tests/fixtures/fake_harness/scripts/question.1.ndjson` (first call: the worker ASKS — a result that is a JSON object with a `question`; no file edit):

```
{"type":"system","subtype":"init","session_id":"q-1"}
{"type":"assistant","message":{"content":[{"type":"text","text":"I need to know the target database."}]}}
{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.002,"result":"{\"question\": \"Which database should I use?\"}"}
```

`tests/fixtures/fake_harness/scripts/question.2.ndjson` (second call: the worker PROCEEDS — edits a file and returns a non-question result):

```
{"type":"system","subtype":"init","session_id":"q-2"}
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Write","input":{"file_path":"feature.py","content":"x=1\n"}}]}}
{"type":"result","subtype":"success","is_error":false,"total_cost_usd":0.003,"result":"Implemented using the answered database."}
```

> IMPLEMENTER NOTE: match the EXACT NDJSON shape the Claude parser expects — read `tests/fixtures/fake_harness/scripts/review.1.ndjson` and `edit.ndjson` and mirror their event field names (`type`/`subtype`/`message.content`/`result`/`total_cost_usd`/`is_error`). The two crucial properties: `question.1` yields `Done.result` = a JSON string containing a `question` key; `question.2` yields a normal result. Adjust the JSON above to whatever the real parser consumes.

- [ ] **Step 3: Write the failing test**

```python
# tests/integration/test_worker_questions.py
import subprocess
import sys
from pathlib import Path

from orchestrator.agents.message_bus import MessageBus
from orchestrator.agents.orchestrator_agent import OrchestratorAgent
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Role, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(c, cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _setup(tmp_path):
    ws = Workspace(config=Config())
    ws.roles = {"implementer": Role(name="implementer", harness=Harness.claude_code)}
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    bus = MessageBus()
    agent = OrchestratorAgent(workspace=ws, registry=reg, bus=bus, repo=tmp_path)
    return ws, reg, bus, agent


async def test_worker_question_is_answered_and_step_completes(tmp_path, monkeypatch):
    # Numbered-state fake: call 1 asks (question.1), call 2 proceeds (question.2).
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    ws, reg, bus, agent = _setup(tmp_path)
    repo = _repo(tmp_path)
    adapter = reg.adapter_for(Harness.claude_code)
    ctx = RunContext(run_id="r1", inputs={"task": "add widget"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent,
                prompt="question {{task}}", output_schema={"question": "string"},
                max_questions=1)
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter, agent=agent)
    assert not art.is_error
    # the orchestrator answered exactly one question
    kinds = [m.kind for m in bus.log]
    assert kinds.count("question") == 1 and kinds.count("answer") == 1
    # final result is the post-answer one (no lingering question in output_data)
    assert not (art.output_data or {}).get("question")


async def test_question_without_agent_does_not_loop(tmp_path, monkeypatch):
    # No agent passed → question handling is skipped (back-compat); step ends on the asking result.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "question.1.ndjson"))
    ws, reg, bus, agent = _setup(tmp_path)
    repo = _repo(tmp_path)
    adapter = reg.adapter_for(Harness.claude_code)
    ctx = RunContext(run_id="r2", inputs={"task": "x"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent,
                prompt="question {{task}}", output_schema={"question": "string"},
                max_questions=1)
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter)  # no agent=
    assert (art.output_data or {}).get("question")  # unanswered, surfaced as-is
    assert bus.log == []
```

> IMPLEMENTER NOTE on `$ORCH_FAKE_STATE`: read how `fake_harness.py` uses `ORCH_FAKE_STATE` + `ORCH_FAKE_SCRIPT_DIR` to pick `question.1`/`question.2` on successive calls (mirrors the M4 `review.1`/`review.2` pattern). The keyword that selects the `question.*` family is derived from the prompt (the test prompt starts with `question`). If the selection mechanism differs, adjust the prompt/env to trigger the numbered scripts and report how it actually works.

- [ ] **Step 4: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_worker_questions.py -v`
Expected: FAIL (no question loop; `run_agent_step` has no `agent` param).

- [ ] **Step 5: Implement the question loop**

In `orchestrator/runtime/executors.py`:

(a) Add `agent=None` to `run_agent_step`'s signature (keyword, after `adapter`):

```python
async def run_agent_step(
    workspace: Workspace,
    pipeline: Pipeline,
    step: Step,
    ctx: RunContext,
    *,
    repo: Path,
    adapter: HarnessAdapter,
    agent=None,  # duck-typed OrchestratorAgent; None disables worker Q&A (back-compat)
) -> Artifact:
```

(b) Inside the retry loop, the body currently does `agg = await _drive_harness(...)`. Replace that single call with a bounded **question sub-loop** that re-prompts the same worktree after the orchestrator answers. Keep everything else (success_criteria, retry, diff) unchanged:

```python
                q_prompt = prompt
                for _q in range(step.max_questions + 1):
                    agg = await _drive_harness(
                        adapter, caps, worktree.path, q_prompt, step.output_schema, tracer,
                        mcp_servers=mcp_servers,
                    )
                    od, _ = parse_output(agg.result_text, step.output_schema)
                    question = (od or {}).get("question") if not agg.is_error else None
                    if not question or agent is None or _q >= step.max_questions:
                        break
                    answer = await agent.answer(question, from_step=step.id)
                    q_prompt = (
                        f"{prompt}\n\n[You asked]: {question}\n"
                        f"[Orchestrator answer]: {answer}\nNow proceed."
                    )
```

(The existing code after the drive — `total_cost += agg.cost_usd`, `output = agg.output`, success_criteria handling, etc. — stays as-is and operates on the final `agg`.)

> IMPLEMENTER NOTE: `parse_output` is already imported in executors.py (used later for `output_data`). Reusing it inside the sub-loop is fine — the final `output_data, parse_error = parse_output(agg.result_text, step.output_schema)` after the loop re-parses the FINAL agg, which is correct. Ensure `mcp_servers` is in scope (it is — built earlier in the function for M6b). Confirm the `_Aggregate` attribute used for the question check is `agg.result_text` (the harness final result), matching how `parse_output` is called elsewhere.

- [ ] **Step 6: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_worker_questions.py -v`
Then full suite: `uv run --extra dev python -m pytest -q` (back-compat: steps with `max_questions=0` never enter the answer branch; the loop runs exactly once).
Expected: PASS.

- [ ] **Step 7: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/config/schemas.py orchestrator/runtime/executors.py tests/fixtures/fake_harness/scripts/question.1.ndjson tests/fixtures/fake_harness/scripts/question.2.ndjson tests/integration/test_worker_questions.py
git commit -m "feat(m6c): worker question loop — orchestrator answers, same-worktree re-prompt (max_questions)"
```

---

## Task 5: Wire the agent + bus into the scheduler

**Files:**
- Modify: `orchestrator/runtime/scheduler.py`
- Test: `tests/integration/test_agent_in_scheduler.py`

- [ ] **Step 1: Write the failing test** (a full reject-cycle pipeline: classify emits a `classify` msg; the reject loop-back emits a `verdict` msg and the relayed feedback reaches `implement`; the run completes; back-compat preserved)

```python
# tests/integration/test_agent_in_scheduler.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import (
    Config, Harness, Pipeline, Role, Step, StepType,
)
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(c, cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _ws():
    ws = Workspace(config=Config())
    ws.roles = {
        "implementer": Role(name="implementer", harness=Harness.claude_code),
        "reviewer": Role(name="reviewer", harness=Harness.claude_code),
    }
    return ws


async def test_classify_emits_message_and_run_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    ws = _ws()
    repo = _repo(tmp_path)
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    sched = DeterministicScheduler(ws, reg, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(name="p", steps=[
        Step(id="classify", type=StepType.task, prompt="classify {{task}}",
             output_schema={"kind": "enum[bugfix,feature,refactor]"}),
    ])
    ctx = await sched.run(pipe, {"task": "add a flag"}, "run-c1")
    assert ctx.status == RunStatus.COMPLETED
    assert any(m.kind == "classify" for m in sched.bus.log)


async def test_reject_cycle_relays_verdict_to_implement(tmp_path, monkeypatch):
    # review.1 rejects, review.2 approves (the M4 numbered-state fake).
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    ws = _ws()
    repo = _repo(tmp_path)
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    sched = DeterministicScheduler(ws, reg, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(name="p", steps=[
        Step(id="implement", role="implementer", needs=[], prompt="implement {{task}}",
             success_criteria="true", max_retries=2),
        Step(id="review", role="reviewer", needs=["implement"], prompt="review",
             output_schema={"verdict": "enum[approve,reject]"}, on_reject="implement"),
    ])
    ctx = await sched.run(pipe, {"task": "x"}, "run-r1")
    assert ctx.status == RunStatus.COMPLETED
    assert any(m.kind == "verdict" and m.to == "implement" for m in sched.bus.log)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_in_scheduler.py -v`
Expected: FAIL (`DeterministicScheduler` has no `.bus`; task steps don't route through the agent; no verdict message).

- [ ] **Step 3: Implement**

In `orchestrator/runtime/scheduler.py`:

(a) Imports:
```python
from orchestrator.agents.message_bus import MessageBus
from orchestrator.agents.orchestrator_agent import OrchestratorAgent
```

(b) `__init__` — accept optional `bus`/`agent`, else auto-construct (keeps every existing call site working):
```python
    def __init__(
        self,
        workspace: Workspace,
        adapter: HarnessAdapter | HarnessRegistry,
        repo: Path,
        *,
        checkpoint_db: Path | None = None,
        bus: MessageBus | None = None,
        agent: OrchestratorAgent | None = None,
    ) -> None:
        self.workspace = workspace
        self.registry = (
            adapter if isinstance(adapter, HarnessRegistry) else HarnessRegistry.single(adapter)
        )
        self.repo = Path(repo)
        self.checkpoint_db = (
            Path(checkpoint_db) if checkpoint_db is not None
            else self.repo / ".orch" / "checkpoints.sqlite"
        )
        self._pipeline_cache: dict[str, Pipeline] = {}
        self.bus = bus or MessageBus()
        self.agent = agent or OrchestratorAgent(
            workspace=workspace, registry=self.registry, bus=self.bus, repo=self.repo
        )
```

(c) `_make_node` — route non-merge task steps through the agent; pass the agent to agent steps:
```python
            if step.type == StepType.task:
                if step.merge_strategy is not None:
                    adapter = self.registry.default_adapter()
                    await run_merge_step(
                        self.workspace, pipeline, step, ctx, repo=self.repo, adapter=adapter
                    )
                else:
                    await self.agent.run_task(pipeline, step, ctx)
            elif step.type == StepType.agent:
                harness = self.workspace.roles[step.role].harness
                adapter = self.registry.adapter_for(harness)
                await run_agent_step(
                    self.workspace, pipeline, step, ctx,
                    repo=self.repo, adapter=adapter, agent=self.agent,
                )
            else:  # gate
                run_gate_step(step, ctx)
```

(d) `_router` — on a reject decision, relay the verdict before returning the reject target:
```python
            def route_fn(state: GraphState) -> str:
                ctx = state["ctx"]
                if src.type == StepType.gate:
                    if ctx.gate_decisions.get(source) == "reject":
                        return END
                    return forward[0] if forward else END
                art = ctx.artifacts.get(source)
                verdict = (art.output_data or {}).get("verdict") if art else None
                if (
                    verdict == Verdict.REJECT
                    and reject_target is not None
                    and ctx.attempts.get(reject_target, 0) <= by_id[reject_target].max_retries
                ):
                    self.agent.relay_verdict(
                        art.output if art else "reject", to_step=reject_target, ctx=ctx
                    )
                    return reject_target
                return forward[0] if forward else END
```

(The `self` reference is available because `_router`/`route_fn` are defined inside the class method; confirm `route_fn` closes over `self` — it does, since `_router` is a bound method.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_in_scheduler.py -v`
Then the FULL suite — back-compat is critical here (task steps now go through `agent.run_task`, which uses the orchestrator role's adapter; in a `.single()` registry that's the same adapter, so behavior is identical): `uv run --extra dev python -m pytest -q`.
Expected: PASS (baseline 224 + new; no prior test regressions).

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/scheduler.py tests/integration/test_agent_in_scheduler.py
git commit -m "feat(m6c): scheduler routes coordination through the orchestrator agent + bus"
```

---

## Task 6: Controller/CLI pass-through + reserved role + example assets

**Files:**
- Confirm/Modify: `orchestrator/runtime/controller.py`, `orchestrator/cli.py`
- Create: `examples/feature-pipeline/.orchestrator/roles/orchestrator.yaml`
- Create: `examples/feature-pipeline/.orchestrator/pipelines/qa-demo.yaml`
- Test: extend `tests/integration/test_example_compiles.py` coverage (a compile assertion for `qa-demo`)

- [ ] **Step 1: Confirm controller/CLI need no change**

Read `orchestrator/runtime/controller.py` and `orchestrator/cli.py`. Because `DeterministicScheduler` auto-constructs its `bus`/`agent`, `make_controller` and the CLI already work unchanged (they pass `workspace, registry, repo`). Verify by running `tests/integration/test_example_compiles.py`. If `make_controller` or the CLI explicitly need the bus exposed for a later milestone, do nothing here — M6c keeps them as-is. (No code change expected in this step; if you find one is required, make the minimal pass-through and note it.)

- [ ] **Step 2: Create the reserved orchestrator role**

`examples/feature-pipeline/.orchestrator/roles/orchestrator.yaml`:

```yaml
# The run-owner (spec §7). Read-only: it classifies, relays verdicts, and answers
# worker questions — it does not edit code. Reserved role name: `orchestrator`.
harness: claude-code
permissions: read-only
```

- [ ] **Step 3: Create the worker-Q&A demo pipeline**

`examples/feature-pipeline/.orchestrator/pipelines/qa-demo.yaml`:

```yaml
# M6c demo: the implementer may ask the orchestrator one question before proceeding.
mode: declarative
inputs: { task: string }
steps:
  - id: classify
    type: task
    prompt: 'Classify {{task}} as one of: bugfix | feature | refactor. Reply JSON {"kind":"<one>"}.'
    output_schema: { kind: "enum[bugfix,feature,refactor]" }
  - id: implement
    role: implementer
    needs: [classify]
    prompt: "Implement {{task}}. If blocked, reply JSON {\"question\": \"<your question>\"}."
    output_schema: { question: "string" }
    max_questions: 1
    success_criteria: "true"
```

- [ ] **Step 4: Add a compile assertion**

Confirm `qa-demo` compiles: `uv run orch compile qa-demo --root examples/feature-pipeline/.orchestrator`
Expected: `OK`, edge `classify --> implement`. If `tests/integration/test_example_compiles.py` enumerates pipelines explicitly, add `qa-demo`; if it iterates the directory, it's picked up automatically — just confirm it passes.

- [ ] **Step 5: Run the full suite + ruff + commit**

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev ruff check .
git add orchestrator/runtime/controller.py orchestrator/cli.py examples/feature-pipeline/.orchestrator/roles/orchestrator.yaml examples/feature-pipeline/.orchestrator/pipelines/qa-demo.yaml tests/integration/test_example_compiles.py
git commit -m "feat(m6c): reserved orchestrator role + qa-demo example; controller/CLI pass-through"
```

---

## Task 7: End-to-end Q&A run + manual smoke

**Files:**
- Test: `tests/integration/test_qa_demo_e2e.py`

- [ ] **Step 1: Write the e2e test** (run `qa-demo` from the loaded example workspace through the scheduler against the fake harness; the implementer asks, the orchestrator answers, the run completes, and the bus shows the full coordination)

```python
# tests/integration/test_qa_demo_e2e.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Harness
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(c, cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


async def test_qa_demo_completes_with_one_answered_question(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    ws = load_workspace(EXAMPLE)
    assert "orchestrator" in ws.roles  # reserved role loaded
    repo = _repo(tmp_path)
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    sched = DeterministicScheduler(ws, reg, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = ws.pipelines["qa-demo"]
    ctx = await sched.run(pipe, {"task": "add a widget"}, "run-qa-1")
    assert ctx.status == RunStatus.COMPLETED
    kinds = [m.kind for m in sched.bus.log]
    assert "classify" in kinds and "question" in kinds and "answer" in kinds
```

> IMPLEMENTER NOTE: the implementer step is keyword-driven by its prompt for the numbered fake. Confirm the `qa-demo` implement prompt triggers the `question.*` fake family (the fake selects scripts by a keyword in the prompt + `$ORCH_FAKE_STATE`). If the example's prompt doesn't naturally select `question.1`/`question.2`, either tune the example prompt to contain the selecting keyword or set the script via env in the test — and report which mechanism you used. The classify step must select a script that yields a valid `{"kind": ...}` result.

- [ ] **Step 2: Run to verify it fails, then passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_qa_demo_e2e.py -v`
(If it fails only due to fake-script selection, adjust per the note, then re-run.)
Expected: PASS.

- [ ] **Step 3: Manual CLI smoke (real `orch`, fake binary)**

In a throwaway git repo with `ORCH_CLAUDE_BIN`/`ORCH_FAKE_SCRIPT_DIR`/`ORCH_FAKE_STATE` set to the fakes:
`uv run orch run qa-demo --task "add a flag" --root examples/feature-pipeline/.orchestrator --repo <tmp-repo>`
Confirm the run completes and (if `orch run` prints cost/steps) the coordination happened. Capture output for the follow-ups note. (The bus log is in-process; the CLI doesn't render it yet — that's `orch status`, M6d.)

- [ ] **Step 4: Full suite + ruff + commit**

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev ruff check .
git add tests/integration/test_qa_demo_e2e.py
git commit -m "test(m6c): e2e qa-demo — implementer asks, orchestrator answers, run completes"
```

---

## Task 8: M6c follow-ups note

**Files:**
- Create: `docs/superpowers/notes/m6c-orchestrator-agent-followups.md`

- [ ] **Step 1: Write the note** (mirror `docs/superpowers/notes/m6b-knowledge-followups.md`)

Capture, with rationale and the verified final test count:
- **What M6c shipped:** the message bus (one OTel `message` span per send + in-memory `log` coordination board); the `OrchestratorAgent` coordination layer (`run_task`/`relay_verdict`/`answer`) using its own read-only Role; non-merge task steps routed through the agent (`classify` messages); verdict relay on loop-back that both emits a `verdict` span AND injects the reviewer's feedback into the implementer's next prompt; the bounded worker-question loop (`max_questions`, same-worktree re-prompt) where the orchestrator answers via an LLM; the reserved `orchestrator` role + `qa-demo` example. Built/tested against the fake harness (zero API cost).
- **Headline note — coordination layer, not a router:** M6c is deliberately the within-rails participant (spec §6 declarative mode). The agent does NOT choose structure; that's the specced `AgenticSupervisor`. The DeterministicScheduler remains the executor.
- **MVP fidelity / deferred (not bugs):** the bus `log` is in-memory/process-local (durable record = spans); the user does NOT yet converse with the agent; worker↔worker is mediated-only (no A2A); a question is detected via `output_schema`'s `question` field on the harness *result* (no mid-stream `Question` event); `max_questions` defaults to 0 (opt-in per step); after exhausting `max_questions` the step proceeds with the last result (which may still carry a question → surfaces as output_data, not an error); the orchestrator's `answer` is a fresh one-shot LLM call with no conversation memory; relayed feedback is one-shot (`pop`) per loop-back; classify routing labels every non-merge task step's message as `classify` kind.
- **`orch status` view of the coordination board is M6d** (the bus log + message spans are the data source).
- **Remaining M6 scope after M6c:** `orch status` (render checkpoints/spans incl. message + knowledge-write spans); safety baseline polish. Then M6 (the final MVP milestone) is complete.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/notes/m6c-orchestrator-agent-followups.md
git commit -m "docs(m6c): orchestrator agent + message bus follow-ups"
```

---

## Final Review (after all tasks)

Dispatch a final holistic reviewer (most capable model) over the whole M6c diff. Focus:
- **Back-compat**: every pre-M6c call site still works — `DeterministicScheduler(ws, adapter, repo, ...)` auto-constructs bus+agent; task steps route through `agent.run_task` but resolve the same adapter under a `.single()` registry; `run_agent_step(..., agent=None)` skips Q&A. Confirm the full prior suite (224) stays green.
- **No circular import**: `executors.py` does not import `orchestrator.agents.*` (agent is duck-typed); `agents/ → executors` only.
- **Coordination correctness**: classify emits a `classify` span; reject loop-back emits a `verdict` span AND the relayed feedback reaches the implementer's prompt and is consumed once; a worker question is answered and the step completes on the post-answer result; `max_questions` bounds the loop and `=0` is a true no-op.
- **Span hygiene**: `message` spans carry `msg.from/msg.to/msg.kind`; emitted within the run/step span tree.
- **Scope**: NO agentic routing, NO `orch status` rendering, NO safety polish, NO A2A.

Then use **superpowers:finishing-a-development-branch** to complete (merge to `orchestrator-design`, per the established milestone workflow).

## Self-Review (against spec §7 + the M6c decisions)

- **Spec §7 coverage:** first-class run-owner agent (Task 2) ✓ · message bus where every message is an OTel span, hub-and-spoke (Task 1) ✓ · orch→worker / worker→orch / worker↔worker-mediated (verdict relay Task 2/5, question+answer Task 2/4) ✓ · MVP scope = classify + verdict relay + answer worker questions (Tasks 2,4,5) ✓ · within-rails declarative participant, not the router (design) ✓ · agentic supervisor explicitly deferred ✓.
- **Placeholder scan:** every code step carries real code; the two looseness points (exact fake-harness NDJSON field names; the fake-script selection keyword) are covered by explicit IMPLEMENTER NOTES with a required-behavior contract + the existing M4 `review.1/2` precedent. ✓
- **Type consistency:** `MessageBus.send`/`Message(frm,to,kind,body)`, `OrchestratorAgent(workspace=,registry=,bus=,repo=)` + `.run_task/.relay_verdict/.answer`, `RunContext.relayed_feedback`, `Step.max_questions`, `run_agent_step(..., agent=)`, `SPAN_MESSAGE` used consistently across tasks. ✓
- **Circular-import discipline:** executors stays free of `agents` imports (duck-typed `agent`); agents imports `_drive_harness`/`run_task_step`/`parse_output` from executors — one-directional. ✓
- **Back-compat:** new params default to None/0; auto-constructed bus+agent; `.single()` registry makes `agent.run_task` use the same adapter as before; all prior call sites untouched. ✓
