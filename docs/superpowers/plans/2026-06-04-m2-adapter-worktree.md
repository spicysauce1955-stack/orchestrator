# M2 — Harness Adapter + Worktree + Single Agent Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single `plan` agent step runs end-to-end — capabilities resolved → worktree created → Claude Code harness driven (tested against a fake harness binary) → events streamed to OTel spans → diff captured → typed artifact emitted, all reachable via `orch run <pipeline> --task <t> --only plan`.

**Architecture:** Build the swappability seam (`HarnessAdapter` Protocol + normalized event model) and its first impl (`ClaudeCodeCLIAdapter`, native CLI via `claude -p --output-format stream-json`). The adapter owns NDJSON parsing, capability translation (`ResolvedCaps` → CLI flags), and diff capture. Capabilities resolve from a role (preset → 7 dimensions, deny-wins, knowledge-write gating). An `AgentStep` executor wires capability resolution → worktree isolation → adapter drive → OTel spans → artifact. Adapter contract + executor integration are tested against a **fake harness stub binary** emitting canned NDJSON (zero API cost), per spec §9.

**Tech Stack:** Python 3.11, Pydantic v2, asyncio (`asyncio.subprocess`), `opentelemetry-sdk` (OTel spans + `InMemorySpanExporter` for tests), pytest + `pytest-asyncio`, git worktrees. Builds on M1 (`orchestrator/config`, `orchestrator/compile`).

---

## Context for the implementer

You are extending an existing, working M1 codebase. M1 ships config schemas, a workspace loader, and a compiler that lowers a pipeline to a LangGraph `StateGraph` (`orch compile`). **No execution exists yet.** M2 adds the execution primitives needed to run *one* agent step.

Key existing facts you must respect:

- **Package manager is `uv`. There is no system pip.** Run everything via `uv run` (e.g. `uv run python -m pytest`). Dev deps require `uv run --extra dev ...`. After editing `pyproject.toml` dependencies, run `uv sync --extra dev` (or `uv lock`) so `.venv` picks them up.
- Existing modules: `orchestrator/config/schemas.py` (Pydantic models), `orchestrator/config/loader.py` (`load_workspace`, `Workspace`, `ConfigError`), `orchestrator/compile/{ir,validate,compiler}.py`, `orchestrator/cli.py` (Typer `app` with `compile` + stub `run/status/resume`).
- The compiler defines a placeholder `RunState(TypedDict)` used only for graph lowering. **Do not reuse it for execution.** M2's runtime state is a new `orchestrator/runtime/state.py`.
- Ruff config selects `E,F,I,UP,B`, ignores `UP042`, and has `flake8-bugbear.extend-immutable-calls = ["typer.Option","typer.Argument"]`. Keep it clean: `uv run --extra dev ruff check .`.
- The example workspace at `examples/feature-pipeline/.orchestrator/` is the integration target. The `plan` step uses role `planner` (`harness: claude-code`, `permissions: read-only`, `knowledge: [repo-conventions]`).

**Scope boundary for M2 (do NOT build these — they are later milestones):**
- Full DAG executor / `task` step / `success_criteria` retry loop → **M3**.
- Review loop / agent-as-judge / test-count gate → **M4**.
- HITL gate / resume / merge→PR → **M5**.
- Orchestrator agent / message bus / knowledge provider (core injection + lexical MCP + gated write) / OpenCode adapter / `orch status` → **M6**.
- Prompt dataflow templating beyond literal top-level input substitution → **M3**.

M2 runs exactly one agent step, synchronously invoked from the CLI, against the fake harness in tests (and against the real `claude` binary when configured). `success_criteria`, retries, and the cyclic review edge are out of scope — the step drives the harness once and emits an artifact.

---

## File structure

| File | Responsibility |
|------|----------------|
| `orchestrator/harness/__init__.py` | Re-export event types, `HarnessAdapter`, `ClaudeCodeCLIAdapter`. |
| `orchestrator/harness/events.py` | Normalized event model (`SessionStarted`, `MessageChunk`, `ToolCall`, `FileEdit`, `Cost`, `Done`) + `Event` union. |
| `orchestrator/harness/adapter.py` | `SessionId`, `McpServer`, `HarnessAdapter` Protocol. |
| `orchestrator/harness/claude_code.py` | `ClaudeCodeCLIAdapter`: NDJSON parsing (`parse_line`), `ResolvedCaps`→flags translation, async subprocess streaming, diff capture, resume/cancel. |
| `orchestrator/safety/__init__.py` | Re-export `ResolvedCaps`, `resolve_capabilities`, deny-list. |
| `orchestrator/safety/denylist.py` | Global shell deny-list constant + merge helper. |
| `orchestrator/safety/capabilities.py` | `ResolvedCaps` dataclass + `resolve_capabilities(role, workspace)` (preset → 7 dims, deny-wins, knowledge-write gating). |
| `orchestrator/isolation/__init__.py` | Re-export worktree API. |
| `orchestrator/isolation/worktree.py` | `Worktree` dataclass + `create_worktree` / `remove_worktree`. |
| `orchestrator/runtime/__init__.py` | Re-export `RunContext`, `Artifact`, `run_agent_step`. |
| `orchestrator/runtime/state.py` | `Artifact` + `RunContext` dataclasses. |
| `orchestrator/runtime/executors.py` | `run_agent_step(...)` — the AgentStep lifecycle. |
| `orchestrator/observability/__init__.py` | Re-export tracing helpers. |
| `orchestrator/observability/spans.py` | `configure_tracing(exporter)`, `get_tracer()`, span-name constants. |
| `orchestrator/config/schemas.py` | **Modify:** add `Mode` enum; use it for `Pipeline.mode` / `Defaults.mode`. |
| `orchestrator/config/loader.py` | **Modify:** cross-validate `role.access.knowledge.read/write` against known sources. |
| `orchestrator/cli.py` | **Modify:** implement `run --task --only <step>`; keep `status`/`resume` stubbed. |
| `tests/fixtures/fake_harness/__init__.py` | Marks the fixtures package. |
| `tests/fixtures/fake_harness/fake_harness.py` | Standalone stub binary: echoes argv to a file, emits canned NDJSON. |
| `tests/fixtures/fake_harness/scripts/*.ndjson` | Canned event scripts for the fake binary. |
| `tests/fixtures/repo.py` | `make_repo(tmp_path)` helper: throwaway git repo for worktree/executor tests. |
| `tests/unit/test_events.py` · `test_adapter_protocol.py` · `test_claude_parse.py` · `test_capabilities.py` · `test_denylist.py` · `test_translate.py` · `test_worktree.py` · `test_state.py` · `test_spans.py` · `test_loader_knowledge.py` | Unit tests. |
| `tests/integration/test_adapter_contract.py` · `test_agent_step.py` · `test_run_cli.py` | Integration tests against the fake harness. |
| `examples/feature-pipeline/.orchestrator/knowledge/lessons.yaml` | **Add:** declares the `lessons` write-target source (auditor references it). |

---

## M2 design decisions (read before starting)

1. **Async adapter, sync parser core.** The `HarnessAdapter` Protocol is async (spec §5) — honor it now so M3+ concurrency doesn't require a retrofit. But NDJSON parsing is a **pure synchronous function** (`parse_line`) that the async streamer calls. Most tests stay synchronous; only the subprocess-streaming and executor tests are async (handled by `pytest-asyncio` with `asyncio_mode = "auto"`).
2. **`SessionId` is an orchestrator-local handle**, not the harness's id. The Claude Code session id only arrives in the `system/init` event after the process starts, so `start_session` returns a generated handle and stores per-session state; the real id is captured from the `SessionStarted` event and used for `--resume`.
3. **The adapter owns capability translation and diff capture** (spec §5) — harnesses don't expose these cleanly. `translate(caps)` builds CLI flags; `capture_diff(cwd)` runs `git diff`.
4. **Credential/config protection lives in `ResolvedCaps.deny_read`, not the worktree.** The worktree is just an isolated branch checkout. Credential-path exclusion (`~/.ssh`, `~/.aws`, …) and harness-config read-only (`.git`, `.claude`) are translated to the harness's deny-read controls. `worktree.py` only does `git worktree add/remove`.
5. **Prompt rendering is minimal in M2.** `run_agent_step` renders a prompt by literally substituting `<name>` for each **declared top-level pipeline input** name (so `<task>` → the task text). Steps with no `prompt` (like `plan`) get a role-appropriate default. Full dataflow templating + `<step.output>` substitution is M3. This deliberately sidesteps the unresolved `<...>`-vs-prose syntax question (M1 follow-up) — we only substitute known input names, never arbitrary `<word>` tokens.
6. **OTel via `opentelemetry-sdk`.** `configure_tracing` installs a `TracerProvider`; tests pass an `InMemorySpanExporter`. Span hierarchy for a single step: `run` → `step` → `harness.session` → (`tool_call` | `file_edit`) children; `Cost`/`Done` set attributes on the session span.
7. **Fake harness is the test oracle.** A standalone Python script (`fake_harness.py`) writes its received argv to `$ORCH_FAKE_ARGV` and streams the NDJSON file named by `$ORCH_FAKE_SCRIPT` (default: a built-in plan script). The adapter is constructed with a configurable binary (constructor arg / `ORCH_CLAUDE_BIN` env), so tests point it at the fake.

---

## Task 1: Dependencies + `Mode` enum

**Files:**
- Modify: `pyproject.toml`
- Modify: `orchestrator/config/schemas.py`
- Modify: `tests/unit/test_schemas.py` (add the enum test)

- [ ] **Step 1: Add the failing test for the `Mode` enum**

Add to `tests/unit/test_schemas.py`:

```python
def test_pipeline_mode_rejects_typo():
    import pytest
    from pydantic import ValidationError

    from orchestrator.config.schemas import Mode, Pipeline

    p = Pipeline.model_validate(
        {"mode": "declarative", "steps": [{"id": "a", "type": "task", "prompt": "x"}]}
    )
    assert p.mode is Mode.declarative

    with pytest.raises(ValidationError):
        Pipeline.model_validate(
            {"mode": "declaritive", "steps": [{"id": "a", "type": "task", "prompt": "x"}]}
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_schemas.py::test_pipeline_mode_rejects_typo -v`
Expected: FAIL — `Mode` does not exist / `mode` accepts the typo.

- [ ] **Step 3: Add the `Mode` enum and use it**

In `orchestrator/config/schemas.py`, add the enum next to the other enums:

```python
class Mode(str, Enum):
    declarative = "declarative"
    agentic = "agentic"
```

Change `Pipeline.mode` and `Defaults.mode`:

```python
# in class Pipeline:
    mode: Mode = Mode.declarative

# in class Defaults:
    mode: Mode = Mode.declarative
```

- [ ] **Step 4: Add the dependencies to `pyproject.toml`**

Under `[project] dependencies`, add:

```toml
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
```

Under `[project.optional-dependencies] dev`, add `pytest-asyncio>=0.23`:

```toml
dev = ["pytest>=8.0", "ruff>=0.4", "pytest-asyncio>=0.23"]
```

In `[tool.pytest.ini_options]`, enable auto async mode:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
asyncio_mode = "auto"
```

- [ ] **Step 5: Sync the environment**

Run: `uv sync --extra dev`
Expected: resolves and installs opentelemetry + pytest-asyncio into `.venv`.

- [ ] **Step 6: Run the test + full suite to verify green and no regressions**

Run: `uv run --extra dev python -m pytest tests/unit/test_schemas.py::test_pipeline_mode_rejects_typo -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest`
Expected: all existing tests still pass (the M1 example uses `mode: declarative`, which is a valid enum value).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock orchestrator/config/schemas.py tests/unit/test_schemas.py
git commit -m "feat(m2): add Mode enum + opentelemetry/pytest-asyncio deps"
```

---

## Task 2: Normalized event model

**Files:**
- Create: `orchestrator/harness/__init__.py`
- Create: `orchestrator/harness/events.py`
- Test: `tests/unit/test_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_events.py`:

```python
from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)


def test_event_types_are_frozen_dataclasses():
    s = SessionStarted(session_id="sess-1")
    assert s.session_id == "sess-1"
    import dataclasses

    assert dataclasses.is_dataclass(s)
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        s.session_id = "other"  # type: ignore[misc]


def test_event_fields():
    assert MessageChunk(text="hi").text == "hi"
    tc = ToolCall(name="Read", status="completed")
    assert (tc.name, tc.status) == ("Read", "completed")
    fe = FileEdit(path="src/a.py", kind="modify")
    assert (fe.path, fe.kind) == ("src/a.py", "modify")
    c = Cost(usd=0.01, tokens=150)
    assert (c.usd, c.tokens) == (0.01, 150)
    d = Done(result="ok", is_error=False)
    assert (d.result, d.is_error) == ("ok", False)


def test_event_union_membership():
    events: list[Event] = [
        SessionStarted("s"),
        MessageChunk("t"),
        ToolCall("Read", "completed"),
        FileEdit("a", "create"),
        Cost(0.0, 0),
        Done("", False),
    ]
    assert len(events) == 6
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_events.py -v`
Expected: FAIL — module `orchestrator.harness.events` not found.

- [ ] **Step 3: Implement the event model**

Create `orchestrator/harness/__init__.py`:

```python
"""Harness adapter layer: the swappability seam (spec §5)."""
```

Create `orchestrator/harness/events.py`:

```python
"""Normalized harness event model (spec §5).

Every adapter emits this set, deliberately shaped like ACP `session/update`
so the future ACPAdapter is a near-literal mapping.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionStarted:
    session_id: str


@dataclass(frozen=True)
class MessageChunk:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    status: str  # pending | in_progress | completed | failed


@dataclass(frozen=True)
class FileEdit:
    path: str
    kind: str  # create | modify | delete


@dataclass(frozen=True)
class Cost:
    usd: float
    tokens: int


@dataclass(frozen=True)
class Done:
    result: str
    is_error: bool


Event = SessionStarted | MessageChunk | ToolCall | FileEdit | Cost | Done
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/harness/__init__.py orchestrator/harness/events.py tests/unit/test_events.py
git commit -m "feat(m2): normalized harness event model"
```

---

## Task 3: Harness adapter Protocol + types

**Files:**
- Create: `orchestrator/harness/adapter.py`
- Test: `tests/unit/test_adapter_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_adapter_protocol.py`:

```python
from collections.abc import AsyncIterator
from pathlib import Path

from orchestrator.harness.adapter import HarnessAdapter, McpServer, SessionId
from orchestrator.harness.events import Done, Event, SessionStarted


def test_mcp_server_fields():
    m = McpServer(name="repo-index", command="node", args=["s.js"], env={"K": "v"})
    assert m.name == "repo-index"
    assert m.args == ["s.js"]
    assert m.env == {"K": "v"}


def test_protocol_is_runtime_checkable():
    class Dummy:
        async def start_session(self, *, cwd, caps, mcp_servers) -> SessionId:
            return "h1"

        async def prompt(self, session, text, *, output_schema=None) -> AsyncIterator[Event]:
            async def _gen():
                yield SessionStarted("s")
                yield Done("ok", False)

            return _gen()

        async def resume(self, session) -> SessionId:
            return session

        async def cancel(self, session) -> None:
            return None

    assert isinstance(Dummy(), HarnessAdapter)


def test_non_adapter_fails_isinstance():
    class NotAdapter:
        pass

    assert not isinstance(NotAdapter(), HarnessAdapter)
    # silence unused-import lint for Path in this focused test module
    assert Path(".").exists()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_adapter_protocol.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the Protocol + types**

Create `orchestrator/harness/adapter.py`:

```python
"""The harness swappability seam: a uniform adapter Protocol (spec §5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from orchestrator.harness.events import Event

if TYPE_CHECKING:
    from orchestrator.safety.capabilities import ResolvedCaps

SessionId = str


@dataclass(frozen=True)
class McpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class HarnessAdapter(Protocol):
    """Drives a coding-agent harness uniformly. Implementations own diff
    capture and capability translation (harnesses don't expose them cleanly)."""

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: ResolvedCaps,
        mcp_servers: list[McpServer],
    ) -> SessionId: ...

    async def prompt(
        self,
        session: SessionId,
        text: str,
        *,
        output_schema: dict | None = None,
    ) -> AsyncIterator[Event]: ...

    async def resume(self, session: SessionId) -> SessionId: ...

    async def cancel(self, session: SessionId) -> None: ...
```

> Note: `prompt` is declared `async def ... -> AsyncIterator[Event]` (a coroutine returning an async iterator) to match the spec signature and keep `runtime_checkable` structural checks simple. The Claude Code impl returns an async generator from this coroutine.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_adapter_protocol.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/harness/adapter.py tests/unit/test_adapter_protocol.py
git commit -m "feat(m2): HarnessAdapter Protocol + McpServer/SessionId types"
```

---

## Task 4: Fake harness stub binary

**Files:**
- Create: `tests/fixtures/__init__.py` (if missing)
- Create: `tests/fixtures/fake_harness/__init__.py`
- Create: `tests/fixtures/fake_harness/fake_harness.py`
- Create: `tests/fixtures/fake_harness/scripts/plan.ndjson`
- Create: `tests/fixtures/fake_harness/scripts/edit.ndjson`
- Test: `tests/unit/test_fake_harness.py`

The fake harness lets adapter/executor tests run with zero API cost. It writes the argv it received to `$ORCH_FAKE_ARGV` (one arg per line) and streams the NDJSON file named by `$ORCH_FAKE_SCRIPT` to stdout. The NDJSON shape mirrors real `claude -p --output-format stream-json`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_fake_harness.py`:

```python
import os
import subprocess
import sys
from pathlib import Path

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
PLAN = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts" / "plan.ndjson"


def test_fake_harness_streams_script_and_records_argv(tmp_path):
    argv_file = tmp_path / "argv.txt"
    env = {
        **os.environ,
        "ORCH_FAKE_ARGV": str(argv_file),
        "ORCH_FAKE_SCRIPT": str(PLAN),
    }
    proc = subprocess.run(
        [sys.executable, str(FAKE), "-p", "hello", "--output-format", "stream-json"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    # argv recorded
    recorded = argv_file.read_text().splitlines()
    assert "-p" in recorded
    assert "--output-format" in recorded
    # NDJSON streamed: first line is system/init, last is result
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert '"type": "system"' in lines[0] or '"type":"system"' in lines[0]
    assert '"type": "result"' in lines[-1] or '"type":"result"' in lines[-1]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_fake_harness.py -v`
Expected: FAIL — fake_harness.py / plan.ndjson missing.

- [ ] **Step 3: Create the fixtures package + canned scripts**

Create `tests/fixtures/__init__.py` (empty) if it does not already exist, and `tests/fixtures/fake_harness/__init__.py` (empty).

Create `tests/fixtures/fake_harness/scripts/plan.ndjson` (a read-only planner run — text + a Read tool call, no edits):

```
{"type":"system","subtype":"init","session_id":"fake-plan-1","tools":["Read","Grep","Glob"],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Here is the plan: "}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"README.md"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t1","content":"file contents"}]}}
{"type":"assistant","message":{"content":[{"type":"text","text":"1. do X 2. do Y"}]}}
{"type":"result","subtype":"success","is_error":false,"result":"Plan complete","total_cost_usd":0.012,"usage":{"input_tokens":100,"output_tokens":50},"session_id":"fake-plan-1"}
```

Create `tests/fixtures/fake_harness/scripts/edit.ndjson` (a run that edits a file — exercises the `FileEdit` path; the executor test will create this file in the worktree):

```
{"type":"system","subtype":"init","session_id":"fake-edit-1","tools":["Read","Edit","Write"],"cwd":"."}
{"type":"assistant","message":{"content":[{"type":"text","text":"Editing now."}]}}
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"e1","name":"Write","input":{"file_path":"note.txt"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"e1","content":"ok"}]}}
{"type":"result","subtype":"success","is_error":false,"result":"Edit complete","total_cost_usd":0.02,"usage":{"input_tokens":120,"output_tokens":80},"session_id":"fake-edit-1"}
```

- [ ] **Step 4: Create the fake harness binary**

Create `tests/fixtures/fake_harness/fake_harness.py`:

```python
#!/usr/bin/env python3
"""Fake coding-agent harness for tests. Zero API cost.

Behavior:
- Records the argv it received (one arg per line) to $ORCH_FAKE_ARGV (if set).
- Streams the NDJSON file at $ORCH_FAKE_SCRIPT to stdout (default: plan.ndjson).
- If $ORCH_FAKE_TOUCH is set, creates that file in the CWD before emitting the
  result (simulates a harness writing a file, so diff capture has something to see).
- Exits 0 unless $ORCH_FAKE_EXIT is set to a non-zero integer.
"""

import os
import sys
import time
from pathlib import Path

DEFAULT_SCRIPT = Path(__file__).parent / "scripts" / "plan.ndjson"


def main() -> int:
    argv_file = os.environ.get("ORCH_FAKE_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(sys.argv[1:]))

    touch = os.environ.get("ORCH_FAKE_TOUCH")
    if touch:
        Path(touch).write_text("created by fake harness\n")

    script = Path(os.environ.get("ORCH_FAKE_SCRIPT", str(DEFAULT_SCRIPT)))
    for line in script.read_text().splitlines():
        if not line.strip():
            continue
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        time.sleep(0)  # yield, keep streaming semantics

    return int(os.environ.get("ORCH_FAKE_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_fake_harness.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/
git commit -m "test(m2): fake harness stub binary + canned NDJSON scripts"
```

---

## Task 5: Claude Code NDJSON parser (pure function)

**Files:**
- Create: `orchestrator/harness/claude_code.py` (parser portion only)
- Test: `tests/unit/test_claude_parse.py`

This is the pure, synchronous core of the adapter: map one decoded NDJSON object to a list of normalized events. Statefulness (tool-call id → name) is passed in via a mutable dict so the streamer can correlate `tool_use` with `tool_result`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_claude_parse.py`:

```python
from orchestrator.harness.claude_code import parse_line
from orchestrator.harness.events import (
    Cost,
    Done,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)


def test_parse_system_init():
    state: dict[str, str] = {}
    events = parse_line(
        {"type": "system", "subtype": "init", "session_id": "s1"}, state
    )
    assert events == [SessionStarted("s1")]


def test_parse_assistant_text():
    state: dict[str, str] = {}
    events = parse_line(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        state,
    )
    assert events == [MessageChunk("hi")]


def test_parse_tool_use_emits_in_progress_and_records_name():
    state: dict[str, str] = {}
    events = parse_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {}}
                ]
            },
        },
        state,
    )
    assert events == [ToolCall("Read", "in_progress")]
    assert state["t1"] == "Read"


def test_parse_tool_use_write_also_emits_file_edit():
    state: dict[str, str] = {}
    events = parse_line(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "w1",
                        "name": "Write",
                        "input": {"file_path": "src/a.py"},
                    }
                ]
            },
        },
        state,
    )
    assert ToolCall("Write", "in_progress") in events
    assert FileEdit("src/a.py", "create") in events


def test_parse_tool_result_completes_known_call():
    state = {"t1": "Read"}
    events = parse_line(
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]
            },
        },
        state,
    )
    assert events == [ToolCall("Read", "completed")]


def test_parse_result_emits_cost_then_done():
    state: dict[str, str] = {}
    events = parse_line(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "done",
            "total_cost_usd": 0.03,
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
        state,
    )
    assert events == [Cost(usd=0.03, tokens=30), Done(result="done", is_error=True if False else False)]


def test_parse_unknown_type_is_ignored():
    assert parse_line({"type": "stream_event", "x": 1}, {}) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_claude_parse.py -v`
Expected: FAIL — `parse_line` not defined.

- [ ] **Step 3: Implement the parser**

Create `orchestrator/harness/claude_code.py` with the parser (the adapter class is added in Task 6 and Task 10 — leave room):

```python
"""ClaudeCodeCLIAdapter: drive `claude -p --output-format stream-json` (spec §5).

Split into three concerns:
- `parse_line`        : pure NDJSON-object → normalized events (this task)
- `ClaudeCodeCLIAdapter.translate` : ResolvedCaps → CLI flags (Task 10)
- `ClaudeCodeCLIAdapter` async streaming + diff capture (Task 6)
"""

from __future__ import annotations

from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)

# tool_use names that mutate files → also emit a FileEdit
_EDIT_TOOLS = {
    "Write": "create",
    "Edit": "modify",
    "MultiEdit": "modify",
    "NotebookEdit": "modify",
}


def parse_line(obj: dict, tool_names: dict[str, str]) -> list[Event]:
    """Map one decoded stream-json object to normalized events.

    `tool_names` is mutated: tool_use id → tool name, so a later tool_result
    can be reported as a completed call for the right tool.
    """
    kind = obj.get("type")

    if kind == "system" and obj.get("subtype") == "init":
        return [SessionStarted(obj.get("session_id", ""))]

    if kind == "assistant":
        events: list[Event] = []
        for block in obj.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text":
                events.append(MessageChunk(block.get("text", "")))
            elif btype == "tool_use":
                name = block.get("name", "")
                tool_id = block.get("id", "")
                if tool_id:
                    tool_names[tool_id] = name
                events.append(ToolCall(name, "in_progress"))
                if name in _EDIT_TOOLS:
                    path = block.get("input", {}).get("file_path", "")
                    if path:
                        events.append(FileEdit(path, _EDIT_TOOLS[name]))
        return events

    if kind == "user":
        events = []
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "")
                name = tool_names.get(tool_id, "")
                if name:
                    events.append(ToolCall(name, "completed"))
        return events

    if kind == "result":
        usage = obj.get("usage", {}) or {}
        tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return [
            Cost(usd=float(obj.get("total_cost_usd", 0.0)), tokens=tokens),
            Done(result=obj.get("result", ""), is_error=bool(obj.get("is_error", False))),
        ]

    return []
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_claude_parse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/harness/claude_code.py tests/unit/test_claude_parse.py
git commit -m "feat(m2): claude-code stream-json parser (pure)"
```

---

## Task 6: ClaudeCodeCLIAdapter async streaming + diff capture

**Files:**
- Modify: `orchestrator/harness/claude_code.py` (add the adapter class)
- Modify: `orchestrator/harness/__init__.py` (re-export)
- Test: `tests/integration/test_adapter_contract.py`

This wires the parser to a real subprocess. It is the **adapter contract test** (spec §9): drive the fake harness binary, assert the normalized event stream. Capability translation flags are added in Task 10 — for now `start_session` stores cwd/caps and `prompt` spawns the process with the base flags.

- [ ] **Step 1: Write the failing contract test**

Create `tests/integration/test_adapter_contract.py`:

```python
import os
from pathlib import Path

import pytest

from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.events import Cost, Done, SessionStarted, ToolCall
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"


def _caps() -> ResolvedCaps:
    return ResolvedCaps.read_only()


async def _drive(adapter, cwd, text):
    session = await adapter.start_session(cwd=cwd, caps=_caps(), mcp_servers=[])
    events = []
    stream = await adapter.prompt(session, text)
    async for ev in stream:
        events.append(ev)
    return session, events


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    return tmp_path


async def test_adapter_streams_normalized_events(fake_env, tmp_path):
    import sys

    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "make a plan")

    assert isinstance(events[0], SessionStarted)
    assert events[0].session_id == "fake-plan-1"
    assert any(isinstance(e, ToolCall) and e.name == "Read" for e in events)
    assert isinstance(events[-1], Done)
    assert events[-1].is_error is False
    assert any(isinstance(e, Cost) and e.usd == 0.012 for e in events)


async def test_adapter_passes_prompt_and_stream_flag(fake_env, tmp_path):
    import sys

    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, "hello prompt")

    argv = (fake_env / "argv.txt").read_text().splitlines()
    assert "-p" in argv
    assert "--output-format" in argv
    assert "stream-json" in argv
    assert "hello prompt" in argv


async def test_adapter_nonzero_exit_yields_error_done(monkeypatch, tmp_path):
    import sys

    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_EXIT", "3")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "x")
    # A non-zero harness exit must surface as an error Done even though the
    # canned script's own result said success.
    assert isinstance(events[-1], Done)
    assert events[-1].is_error is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_adapter_contract.py -v`
Expected: FAIL — `ClaudeCodeCLIAdapter` not defined (and `ResolvedCaps` not yet built — Task 8). If `ResolvedCaps` import blocks collection, that is expected; this task depends on Task 8 being done first. **Reorder note:** implement Task 7 + Task 8 (capabilities) before running this test green. The plan orders capabilities at 7–8; if executing strictly in order, write this test now (red) and return to green it after Task 8. To keep each task independently green, the implementer should implement Tasks 7–8 *before* finishing Task 6. **Therefore: do Task 7 and Task 8 first, then return here.**

> Controller guidance: dispatch order is 1, 2, 3, 4, 5, **7, 8**, 6, 9, 10, 11, 12, 13, 14, 15. Task 6's test needs `ResolvedCaps`. The task numbering is by component; the dependency-correct execution order is given in "Execution handoff" at the end.

- [ ] **Step 3: Implement the adapter streaming**

Append to `orchestrator/harness/claude_code.py`:

```python
import asyncio
import json
import subprocess
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.harness.adapter import McpServer, SessionId
from orchestrator.safety.capabilities import ResolvedCaps


@dataclass
class _Session:
    cwd: Path
    caps: ResolvedCaps
    mcp_servers: list[McpServer]
    harness_session_id: str | None = None


class ClaudeCodeCLIAdapter:
    """Drives Claude Code via `claude -p --output-format stream-json`.

    `binary` is the command prefix (default `["claude"]`); tests inject the
    fake harness. Honors $ORCH_CLAUDE_BIN when no binary is passed.
    """

    def __init__(self, binary: list[str] | None = None) -> None:
        if binary is None:
            import os

            env_bin = os.environ.get("ORCH_CLAUDE_BIN")
            binary = env_bin.split() if env_bin else ["claude"]
        self._binary = binary
        self._sessions: dict[SessionId, _Session] = {}

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: ResolvedCaps,
        mcp_servers: list[McpServer],
    ) -> SessionId:
        handle = uuid.uuid4().hex
        self._sessions[handle] = _Session(cwd=Path(cwd), caps=caps, mcp_servers=list(mcp_servers))
        return handle

    async def prompt(
        self,
        session: SessionId,
        text: str,
        *,
        output_schema: dict | None = None,
    ) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        flags = self.translate(sess.caps, cwd=sess.cwd)
        cmd = [
            *self._binary,
            "-p",
            text,
            "--output-format",
            "stream-json",
            *flags,
        ]
        return self._stream(session, cmd)

    async def _stream(self, session: SessionId, cmd: list[str]) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sess.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        tool_names: dict[str, str] = {}
        saw_done = False
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for ev in parse_line(obj, tool_names):
                if isinstance(ev, SessionStarted):
                    sess.harness_session_id = ev.session_id
                if isinstance(ev, Done):
                    saw_done = True
                yield ev
        returncode = await proc.wait()
        if returncode != 0:
            # A non-zero harness exit is a failure regardless of streamed result.
            yield Done(result=f"harness exited {returncode}", is_error=True)
        elif not saw_done:
            yield Done(result="", is_error=True)

    async def resume(self, session: SessionId) -> SessionId:
        # Re-prompting a resumed session would pass `--resume <harness_session_id>`;
        # full re-prompt wiring lands with the DAG executor (M3). M2 only needs
        # the handle to remain valid.
        return session

    async def cancel(self, session: SessionId) -> None:
        self._sessions.pop(session, None)

    def translate(self, caps: ResolvedCaps, *, cwd: Path | None = None) -> list[str]:
        # Implemented in Task 10.
        return []
```

> The `translate` stub returns `[]` here; Task 10 fills it in and adds its own test. Keeping it as a method now lets `prompt` call it.

- [ ] **Step 4: Re-export from the package**

Replace `orchestrator/harness/__init__.py` with:

```python
"""Harness adapter layer: the swappability seam (spec §5)."""

from orchestrator.harness.adapter import HarnessAdapter, McpServer, SessionId
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter, parse_line
from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)

__all__ = [
    "HarnessAdapter",
    "McpServer",
    "SessionId",
    "ClaudeCodeCLIAdapter",
    "parse_line",
    "Event",
    "SessionStarted",
    "MessageChunk",
    "ToolCall",
    "FileEdit",
    "Cost",
    "Done",
]
```

- [ ] **Step 5: Run the contract test to verify it passes** (after Tasks 7–8 exist)

Run: `uv run --extra dev python -m pytest tests/integration/test_adapter_contract.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/harness/claude_code.py orchestrator/harness/__init__.py tests/integration/test_adapter_contract.py
git commit -m "feat(m2): ClaudeCodeCLIAdapter async streaming + contract test"
```

---

## Task 7: Global shell deny-list

**Files:**
- Create: `orchestrator/safety/__init__.py`
- Create: `orchestrator/safety/denylist.py`
- Test: `tests/unit/test_denylist.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_denylist.py`:

```python
from orchestrator.safety.denylist import GLOBAL_SHELL_DENY, merge_shell_deny


def test_global_deny_includes_destructive_commands():
    for pattern in ("rm -rf /", "git push --force", "git reset --hard", "DROP TABLE"):
        assert pattern in GLOBAL_SHELL_DENY


def test_merge_is_union_without_duplicates():
    merged = merge_shell_deny(["rm -rf /", "custom-cmd"])
    assert "custom-cmd" in merged
    assert merged.count("rm -rf /") == 1
    # global entries are preserved
    assert "git push --force" in merged
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_denylist.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the deny-list**

Create `orchestrator/safety/__init__.py`:

```python
"""Safety layer: capability resolution + deny-lists (spec §4.1, §9)."""
```

Create `orchestrator/safety/denylist.py`:

```python
"""Global shell command deny-list (spec §4.1 dim 3). Deny always wins."""

from __future__ import annotations

# Hard-blocked command fragments, merged with any per-role shell deny.
GLOBAL_SHELL_DENY: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf",
    "git push --force",
    "git reset --hard",
    "curl|bash",
    "curl | bash",
    "DROP TABLE",
    "npm publish",
)


def merge_shell_deny(role_deny: list[str]) -> tuple[str, ...]:
    """Union the global deny-list with a role's deny-list, order-stable, no dups."""
    seen: dict[str, None] = {}
    for item in (*GLOBAL_SHELL_DENY, *role_deny):
        seen.setdefault(item, None)
    return tuple(seen)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_denylist.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/safety/__init__.py orchestrator/safety/denylist.py tests/unit/test_denylist.py
git commit -m "feat(m2): global shell deny-list + merge helper"
```

---

## Task 8: Capability resolution

**Files:**
- Create: `orchestrator/safety/capabilities.py`
- Modify: `orchestrator/safety/__init__.py` (re-export)
- Test: `tests/unit/test_capabilities.py`

Resolve a role to a concrete `ResolvedCaps`: expand the `permissions` preset into the 7 dimensions, layer per-dimension `access` overrides, merge skill tool grants (clamped by the profile), apply deny-wins, and **gate knowledge write** (never granted unless explicitly listed per source). This is the harness-agnostic capability set; the adapter translates it to flags (Task 10).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_capabilities.py`:

```python
import pytest

from orchestrator.config.loader import ConfigError, load_workspace
from orchestrator.config.schemas import (
    Access,
    KnowledgeAccess,
    PermissionProfile,
    Role,
    Skill,
)
from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities

EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _ws():
    return load_workspace(EXAMPLE)


def test_read_only_profile_disallows_edit_tools():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["planner"], ws)
    assert "Edit" in caps.disallowed_tools
    assert "Write" in caps.disallowed_tools
    assert caps.permission_mode in ("default", "plan")
    # credential + harness-config paths are always denied for reads
    assert any(".ssh" in p for p in caps.deny_read)
    assert any(".git" in p for p in caps.deny_read)


def test_edit_profile_grants_write_scope():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["implementer"], ws)
    assert "src/**" in caps.write_scope
    assert "tests/**" in caps.write_scope
    assert caps.permission_mode == "acceptEdits"
    # global deny merged with role deny
    assert "rm -rf /" in caps.shell_deny
    assert "git push --force" in caps.shell_deny


def test_skill_tools_are_merged_for_edit_role():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["implementer"], ws)
    # test-runner skill grants Bash(pytest), Read, Edit
    assert "Bash(pytest)" in caps.allowed_tools


def test_skill_edit_tool_clamped_by_read_only_profile():
    # A read-only role must not gain Edit even if a skill grants it (deny-wins).
    role = Role(name="r", harness="claude-code", permissions=PermissionProfile.read_only,
                skills=["test-runner"])
    skill = Skill(name="test-runner", instructions="x", tools=["Edit", "Read"])
    ws = _ws()
    ws.roles["r"] = role
    ws.skills["test-runner"] = skill
    caps = resolve_capabilities(role, ws)
    assert "Edit" not in caps.allowed_tools
    assert "Edit" in caps.disallowed_tools


def test_knowledge_write_only_when_explicitly_granted():
    ws = _ws()
    auditor = resolve_capabilities(ws.roles["auditor"], ws)
    planner = resolve_capabilities(ws.roles["planner"], ws)
    assert "lessons" in auditor.knowledge_write
    assert planner.knowledge_write == ()


def test_never_push_to_main():
    ws = _ws()
    caps = resolve_capabilities(ws.roles["implementer"], ws)
    assert caps.push_to_main is False


def test_resolved_caps_read_only_constructor():
    caps = ResolvedCaps.read_only()
    assert caps.permission_mode in ("default", "plan")
    assert "Edit" in caps.disallowed_tools
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_capabilities.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement capability resolution**

Create `orchestrator/safety/capabilities.py`:

```python
"""Capability resolution: role → ResolvedCaps (spec §4.1).

effective = (role grants ∪ skill grants) ∩ permission profile; deny always wins.
Translation to harness flags lives in the adapter (spec §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import PermissionProfile, Role
from orchestrator.safety.denylist import merge_shell_deny

# Credential paths never readable by a harness (spec §4.1 dim 1 + 6).
CREDENTIAL_DENY_READ: tuple[str, ...] = (
    "~/.ssh",
    "~/.aws",
    "~/.kube",
    "~/.config/gh",
    ".env",
    ".env.*",
)
# Harness/VCS config is read-only (not writable) but still excluded from reads
# of secrets-bearing internals; we deny reads of these dirs by default.
CONFIG_DENY_READ: tuple[str, ...] = (".git", ".claude")

# Read-only tool floor and the edit tools a read-only profile must refuse.
_READ_TOOLS: tuple[str, ...] = ("Read", "Grep", "Glob")
_EDIT_TOOLS: tuple[str, ...] = ("Edit", "Write", "MultiEdit", "NotebookEdit")


@dataclass(frozen=True)
class ResolvedCaps:
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: str = "default"
    deny_read: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    network_egress: tuple[str, ...] = ()
    shell_deny: tuple[str, ...] = ()
    knowledge_read: tuple[str, ...] = ()
    knowledge_write: tuple[str, ...] = ()
    push_to_main: bool = False
    open_pr: bool = True

    @classmethod
    def read_only(cls) -> ResolvedCaps:
        """A minimal read-only capability set (used by tests + the planner)."""
        return cls(
            allowed_tools=_READ_TOOLS,
            disallowed_tools=_EDIT_TOOLS,
            permission_mode="default",
            deny_read=(*(_expand(p) for p in CREDENTIAL_DENY_READ), *CONFIG_DENY_READ),
            shell_deny=merge_shell_deny([]),
        )


def _expand(path: str) -> str:
    import os

    return os.path.expanduser(path) if path.startswith("~") else path


def _dedup(items: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for i in items:
        seen.setdefault(i, None)
    return tuple(seen)


def resolve_capabilities(role: Role, workspace: Workspace) -> ResolvedCaps:
    profile = role.permissions
    read_only = profile == PermissionProfile.read_only

    # --- Tools: read floor + skill grants, clamped by profile ---
    allowed: list[str] = list(_READ_TOOLS)
    for skill_name in role.skills:
        skill = workspace.skills.get(skill_name)
        if skill is None:
            continue
        for tool in skill.tools:
            allowed.append(tool)

    disallowed: list[str] = []
    if read_only:
        # deny-wins: edit tools removed from allow and added to deny
        allowed = [t for t in allowed if _base_tool(t) not in _EDIT_TOOLS]
        disallowed.extend(_EDIT_TOOLS)

    # --- Filesystem write scope (only meaningful for edit/full) ---
    write_scope: list[str] = []
    network: list[str] = []
    role_shell_deny: list[str] = []
    knowledge_read: list[str] = []
    knowledge_write: list[str] = []
    push_to_main = False
    open_pr = True

    access = role.access
    if access is not None:
        if access.filesystem is not None and not read_only:
            write_scope.extend(access.filesystem.write)
        if access.network is not None:
            network.extend(access.network.egress)
        if access.shell is not None:
            role_shell_deny.extend(access.shell.deny)
        if access.git is not None:
            push_to_main = bool(access.git.push_to_main)
            open_pr = bool(access.git.open_pr)
        if access.knowledge is not None:
            knowledge_read.extend(access.knowledge.read)
            # Knowledge write is NEVER in a preset — only explicit per-source.
            knowledge_write.extend(access.knowledge.write)

    # role.knowledge (top-level read grants) folds into knowledge_read
    knowledge_read.extend(role.knowledge)

    permission_mode = "default" if read_only else "acceptEdits"

    deny_read = (*tuple(_expand(p) for p in CREDENTIAL_DENY_READ), *CONFIG_DENY_READ)

    return ResolvedCaps(
        allowed_tools=_dedup(allowed),
        disallowed_tools=_dedup(disallowed),
        permission_mode=permission_mode,
        deny_read=deny_read,
        write_scope=_dedup(write_scope),
        network_egress=_dedup(network),
        shell_deny=merge_shell_deny(role_shell_deny),
        knowledge_read=_dedup(knowledge_read),
        knowledge_write=_dedup(knowledge_write),
        push_to_main=push_to_main,
        open_pr=open_pr,
    )


def _base_tool(tool: str) -> str:
    """`Bash(pytest)` → `Bash`; `Edit` → `Edit`."""
    return tool.split("(", 1)[0]
```

- [ ] **Step 4: Re-export from the package**

Replace `orchestrator/safety/__init__.py` with:

```python
"""Safety layer: capability resolution + deny-lists (spec §4.1, §9)."""

from orchestrator.safety.capabilities import ResolvedCaps, resolve_capabilities
from orchestrator.safety.denylist import GLOBAL_SHELL_DENY, merge_shell_deny

__all__ = [
    "ResolvedCaps",
    "resolve_capabilities",
    "GLOBAL_SHELL_DENY",
    "merge_shell_deny",
]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_capabilities.py -v`
Expected: PASS

(If `test_knowledge_write_only_when_explicitly_granted` fails because the loader now rejects the auditor's `lessons` write target, complete Task 9 first — Task 9 adds the `lessons` source so the example loads.)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/safety/capabilities.py orchestrator/safety/__init__.py tests/unit/test_capabilities.py
git commit -m "feat(m2): capability resolution (preset→7 dims, deny-wins, knowledge gating)"
```

---

## Task 9: Loader knowledge cross-validation + example `lessons` source

**Files:**
- Modify: `orchestrator/config/loader.py`
- Create: `examples/feature-pipeline/.orchestrator/knowledge/lessons.yaml`
- Test: `tests/unit/test_loader_knowledge.py`

Folds in M1 follow-up: `role.access.knowledge.read/write` referenced undeclared sources silently. Cross-validate them against known knowledge names; add the legitimate `lessons` source the auditor writes to (spec §8).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_loader_knowledge.py`:

```python
import textwrap

import pytest

from orchestrator.config.loader import ConfigError, load_workspace


def _write(base, rel, content):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content))


def test_access_knowledge_write_must_reference_known_source(tmp_path):
    base = tmp_path / ".orchestrator"
    _write(base, "config.yaml", "defaults: {}\n")
    _write(base, "knowledge/repo-conventions.yaml", "sources: [docs/**]\nbackend: lexical\n")
    _write(
        base,
        "roles/auditor.yaml",
        """
        harness: claude-code
        permissions: read-only
        access:
          knowledge: { read: [repo-conventions], write: [ghost-source] }
        knowledge: [repo-conventions]
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "ghost-source" in str(exc.value)


def test_access_knowledge_read_must_reference_known_source(tmp_path):
    base = tmp_path / ".orchestrator"
    _write(base, "config.yaml", "defaults: {}\n")
    _write(base, "knowledge/repo-conventions.yaml", "sources: [docs/**]\n")
    _write(
        base,
        "roles/r.yaml",
        """
        harness: claude-code
        permissions: read-only
        access:
          knowledge: { read: [nope], write: [] }
        """,
    )
    with pytest.raises(ConfigError) as exc:
        load_workspace(base)
    assert "nope" in str(exc.value)


def test_example_workspace_loads_clean():
    # The example declares a `lessons` source, so the auditor's write resolves.
    ws = load_workspace("examples/feature-pipeline/.orchestrator")
    assert "lessons" in ws.knowledge_sources
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_loader_knowledge.py -v`
Expected: FAIL — no cross-validation yet; `lessons` source missing.

- [ ] **Step 3: Add the `lessons` knowledge source to the example**

Create `examples/feature-pipeline/.orchestrator/knowledge/lessons.yaml`:

```yaml
# Durable lessons the auditor appends after a run (spec §8). On-demand source.
sources: [.orchestrator/knowledge/lessons.md]
backend: lexical
```

- [ ] **Step 4: Add cross-validation in the loader**

In `orchestrator/config/loader.py`, inside `_resolve_references`, extend the per-role loop to also validate `access.knowledge`:

```python
    for role in ws.roles.values():
        for skill in role.skills:
            if skill not in ws.skills:
                errors.append(f"role '{role.name}' references unknown skill '{skill}'")
        for source in role.knowledge:
            if source not in known_knowledge:
                errors.append(f"role '{role.name}' references unknown knowledge '{source}'")
        if role.access is not None and role.access.knowledge is not None:
            ka = role.access.knowledge
            for source in (*ka.read, *ka.write):
                if source not in known_knowledge:
                    errors.append(
                        f"role '{role.name}' access.knowledge references unknown "
                        f"source '{source}'"
                    )
```

- [ ] **Step 5: Run the test + full suite to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_loader_knowledge.py -v`
Expected: PASS

Run: `uv run --extra dev python -m pytest tests/integration/test_example_compiles.py -v`
Expected: PASS — the example still compiles (now with the `lessons` source).

- [ ] **Step 6: Commit**

```bash
git add orchestrator/config/loader.py examples/feature-pipeline/.orchestrator/knowledge/lessons.yaml tests/unit/test_loader_knowledge.py
git commit -m "feat(m2): cross-validate access.knowledge refs + example lessons source"
```

---

## Task 10: Adapter capability translation (`ResolvedCaps` → CLI flags)

**Files:**
- Modify: `orchestrator/harness/claude_code.py` (fill in `translate`)
- Test: `tests/unit/test_translate.py`

The adapter owns translation (spec §5): map the harness-agnostic `ResolvedCaps` to Claude Code CLI flags (`--add-dir`, `--allowedTools`, `--disallowedTools`, `--permission-mode`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_translate.py`:

```python
from pathlib import Path

from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps


def _adapter():
    return ClaudeCodeCLIAdapter(binary=["claude"])


def test_translate_permission_mode_and_add_dir():
    caps = ResolvedCaps(permission_mode="acceptEdits")
    flags = _adapter().translate(caps, cwd=Path("/tmp/wt"))
    assert "--permission-mode" in flags
    assert "acceptEdits" in flags
    assert "--add-dir" in flags
    assert "/tmp/wt" in flags


def test_translate_allowed_and_disallowed_tools():
    caps = ResolvedCaps(
        allowed_tools=("Read", "Grep"),
        disallowed_tools=("Edit", "Write"),
        permission_mode="default",
    )
    flags = _adapter().translate(caps)
    i = flags.index("--allowedTools")
    assert flags[i + 1] == "Read,Grep"
    j = flags.index("--disallowedTools")
    assert flags[j + 1] == "Edit,Write"


def test_translate_omits_empty_tool_flags():
    caps = ResolvedCaps(permission_mode="default")
    flags = _adapter().translate(caps)
    assert "--allowedTools" not in flags
    assert "--disallowedTools" not in flags


def test_translate_no_cwd_omits_add_dir():
    caps = ResolvedCaps(permission_mode="default")
    flags = _adapter().translate(caps, cwd=None)
    assert "--add-dir" not in flags
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_translate.py -v`
Expected: FAIL — `translate` returns `[]`.

- [ ] **Step 3: Implement `translate`**

Replace the `translate` stub in `orchestrator/harness/claude_code.py`:

```python
    def translate(self, caps: ResolvedCaps, *, cwd: Path | None = None) -> list[str]:
        """ResolvedCaps → Claude Code CLI flags (spec §4.1, §5)."""
        flags: list[str] = []
        if cwd is not None:
            flags += ["--add-dir", str(cwd)]
        flags += ["--permission-mode", caps.permission_mode]
        if caps.allowed_tools:
            flags += ["--allowedTools", ",".join(caps.allowed_tools)]
        if caps.disallowed_tools:
            flags += ["--disallowedTools", ",".join(caps.disallowed_tools)]
        return flags
```

- [ ] **Step 4: Run the test + adapter contract test to verify**

Run: `uv run --extra dev python -m pytest tests/unit/test_translate.py tests/integration/test_adapter_contract.py -v`
Expected: PASS (the contract test's argv now also carries `--permission-mode` etc.; assertions on `-p`/`--output-format` still hold).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/harness/claude_code.py tests/unit/test_translate.py
git commit -m "feat(m2): ResolvedCaps → Claude Code CLI flag translation"
```

---

## Task 11: Worktree manager

**Files:**
- Create: `orchestrator/isolation/__init__.py`
- Create: `orchestrator/isolation/worktree.py`
- Create: `tests/fixtures/repo.py`
- Test: `tests/unit/test_worktree.py`

Isolated branch checkout via `git worktree`. Credential/config protection is a capabilities concern (Task 8), not here — this module only creates and removes worktrees.

- [ ] **Step 1: Write the shared throwaway-repo fixture**

Create `tests/fixtures/repo.py`:

```python
"""Throwaway git repo helper for worktree/executor integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_repo(path: Path) -> Path:
    """Init a git repo at `path` with one commit. Returns the repo path."""
    path.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (path / "README.md").write_text("# test repo\n")
    git("add", "README.md")
    git("commit", "-q", "-m", "initial")
    return path
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_worktree.py`:

```python
import subprocess
from pathlib import Path

from orchestrator.isolation.worktree import Worktree, create_worktree, remove_worktree
from tests.fixtures.repo import make_repo


def _branches(repo: Path) -> str:
    return subprocess.run(
        ["git", "worktree", "list"], cwd=repo, capture_output=True, text=True
    ).stdout


def test_create_worktree_makes_isolated_checkout(tmp_path):
    repo = make_repo(tmp_path / "repo")
    wt = create_worktree(repo, branch="orch/run1/plan")
    assert isinstance(wt, Worktree)
    assert wt.path.is_dir()
    assert (wt.path / "README.md").exists()
    assert wt.branch == "orch/run1/plan"
    assert str(wt.path) in _branches(repo)


def test_remove_worktree_cleans_up(tmp_path):
    repo = make_repo(tmp_path / "repo")
    wt = create_worktree(repo, branch="orch/run1/plan")
    remove_worktree(repo, wt)
    assert not wt.path.exists()
    assert str(wt.path) not in _branches(repo)


def test_worktree_edits_do_not_touch_base(tmp_path):
    repo = make_repo(tmp_path / "repo")
    wt = create_worktree(repo, branch="orch/run1/plan")
    (wt.path / "new.txt").write_text("hello")
    assert not (repo / "new.txt").exists()
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_worktree.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the worktree manager**

Create `orchestrator/isolation/__init__.py`:

```python
"""Isolation layer: git worktrees per agent step (spec §6)."""

from orchestrator.isolation.worktree import Worktree, create_worktree, remove_worktree

__all__ = ["Worktree", "create_worktree", "remove_worktree"]
```

Create `orchestrator/isolation/worktree.py`:

```python
"""Per-agent-step git worktree isolation (spec §6).

Each agent step runs in its own worktree on its own branch so edits never
touch the base checkout. Credential exclusion / config read-only are enforced
via ResolvedCaps (safety layer), not here.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str


class WorktreeError(RuntimeError):
    """Raised when a git worktree operation fails."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def create_worktree(repo: Path, branch: str, base: str = "HEAD") -> Worktree:
    """Create a worktree for `branch` (new branch off `base`) under `repo/.worktrees/`."""
    repo = Path(repo)
    safe = branch.replace("/", "-")
    path = repo / ".worktrees" / safe
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, str(path), base)
    return Worktree(path=path, branch=branch)


def remove_worktree(repo: Path, worktree: Worktree) -> None:
    """Remove the worktree and delete its branch. Best-effort, idempotent."""
    repo = Path(repo)
    _git(repo, "worktree", "remove", "--force", str(worktree.path))
    # Branch deletion is best-effort: it may already be gone.
    proc = subprocess.run(
        ["git", "branch", "-D", worktree.branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    _ = proc  # ignore failure (branch may not exist)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_worktree.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/isolation/ tests/fixtures/repo.py tests/unit/test_worktree.py
git commit -m "feat(m2): git worktree isolation manager"
```

---

## Task 12: Run state + artifacts

**Files:**
- Create: `orchestrator/runtime/__init__.py`
- Create: `orchestrator/runtime/state.py`
- Test: `tests/unit/test_state.py`

The typed run state threaded through execution: per-step `Artifact` (output + diff + branch + cost) and a `RunContext` that rolls up cost.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_state.py`:

```python
from orchestrator.runtime.state import Artifact, RunContext


def test_artifact_fields():
    a = Artifact(
        step_id="plan",
        output="the plan",
        diff="",
        branch="orch/run1/plan",
        cost_usd=0.012,
        tokens=150,
        is_error=False,
    )
    assert a.step_id == "plan"
    assert a.cost_usd == 0.012


def test_run_context_records_artifacts_and_rolls_up_cost():
    ctx = RunContext(run_id="run1", inputs={"task": "do it"})
    assert ctx.total_cost_usd == 0.0
    ctx.record(
        Artifact("plan", "p", "", "b1", 0.01, 10, False)
    )
    ctx.record(
        Artifact("impl", "i", "diff", "b2", 0.02, 20, False)
    )
    assert set(ctx.artifacts) == {"plan", "impl"}
    assert round(ctx.total_cost_usd, 4) == 0.03
    assert ctx.artifacts["impl"].diff == "diff"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_state.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement run state**

Create `orchestrator/runtime/__init__.py`:

```python
"""Runtime layer: run state + step executors (spec §6)."""

from orchestrator.runtime.state import Artifact, RunContext

__all__ = ["Artifact", "RunContext"]
```

Create `orchestrator/runtime/state.py`:

```python
"""Typed run state threaded through execution (spec §6)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Artifact:
    step_id: str
    output: str
    diff: str
    branch: str
    cost_usd: float
    tokens: int
    is_error: bool


@dataclass
class RunContext:
    run_id: str
    inputs: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    total_cost_usd: float = 0.0

    def record(self, artifact: Artifact) -> None:
        self.artifacts[artifact.step_id] = artifact
        self.total_cost_usd += artifact.cost_usd
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/runtime/__init__.py orchestrator/runtime/state.py tests/unit/test_state.py
git commit -m "feat(m2): RunContext + Artifact run state"
```

---

## Task 13: Observability spans

**Files:**
- Create: `orchestrator/observability/__init__.py`
- Create: `orchestrator/observability/spans.py`
- Test: `tests/unit/test_spans.py`

A thin OTel wrapper: configure a `TracerProvider` (tests inject an `InMemorySpanExporter`), expose `get_tracer()`, and define span-name constants. Spans are created by the executor (Task 14).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_spans.py`:

```python
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.observability.spans import (
    SPAN_SESSION,
    SPAN_STEP,
    configure_tracing,
    get_tracer,
)


def test_configure_tracing_records_spans():
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)
    tracer = get_tracer()
    with tracer.start_as_current_span(SPAN_STEP) as step:
        step.set_attribute("step.id", "plan")
        with tracer.start_as_current_span(SPAN_SESSION) as sess:
            sess.set_attribute("session.id", "s1")

    spans = exporter.get_finished_spans()
    names = {s.name for s in spans}
    assert SPAN_STEP in names
    assert SPAN_SESSION in names
    step_span = next(s for s in spans if s.name == SPAN_STEP)
    assert step_span.attributes["step.id"] == "plan"


def test_span_name_constants_exist():
    from orchestrator.observability.spans import (
        SPAN_FILE_EDIT,
        SPAN_RUN,
        SPAN_TOOL_CALL,
    )

    assert {SPAN_RUN, SPAN_TOOL_CALL, SPAN_FILE_EDIT}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_spans.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the span helpers**

Create `orchestrator/observability/__init__.py`:

```python
"""Observability layer: OTel spans (spec §9)."""

from orchestrator.observability.spans import configure_tracing, get_tracer

__all__ = ["configure_tracing", "get_tracer"]
```

Create `orchestrator/observability/spans.py`:

```python
"""OTel GenAI-style spans for runs/steps/sessions/tools (spec §9).

MVP sink: tests inject InMemorySpanExporter; runtime uses a console/file
exporter. Span hierarchy for one agent step:
    run → step → harness.session → (tool_call | file_edit)
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter

SPAN_RUN = "run"
SPAN_STEP = "step"
SPAN_SESSION = "harness.session"
SPAN_TOOL_CALL = "tool_call"
SPAN_FILE_EDIT = "file_edit"

_TRACER_NAME = "orchestrator"


def configure_tracing(exporter: SpanExporter | None = None) -> None:
    """Install a TracerProvider. Idempotent per process for a given exporter.

    If `exporter` is None, a no-op provider is installed (spans are created but
    not exported) — callers that want output pass a concrete exporter.
    """
    provider = TracerProvider()
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_spans.py -v`
Expected: PASS

> Note on idempotency: OpenTelemetry warns if `set_tracer_provider` is called twice in a process. That is fine for tests (the warning is harmless and each test sets a fresh provider+exporter). Do not add global guards that would prevent tests from installing their own exporter.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/observability/ tests/unit/test_spans.py
git commit -m "feat(m2): OTel span scaffolding (provider, tracer, span names)"
```

---

## Task 14: AgentStep executor

**Files:**
- Create: `orchestrator/runtime/executors.py`
- Modify: `orchestrator/runtime/__init__.py` (re-export `run_agent_step`)
- Test: `tests/integration/test_agent_step.py`

The heart of M2: run one agent step end-to-end. Lifecycle (subset of spec §6 for M2 — no `success_criteria`/retry, no knowledge injection):
1. resolve capabilities from the step's role
2. create a worktree
3. start a harness session + prompt (render prompt from declared inputs)
4. stream events → OTel spans (step → session → tool_call/file_edit); accumulate text + cost
5. capture diff via `git diff` in the worktree
6. emit a typed `Artifact` and record it in the `RunContext`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_agent_step.py`:

```python
import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import (
    SPAN_SESSION,
    SPAN_STEP,
    SPAN_TOOL_CALL,
    configure_tracing,
)
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


async def test_plan_step_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    pipeline = ws.pipelines["feature"]
    step = next(s for s in pipeline.steps if s.id == "plan")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="run1", inputs={"task": "add a feature"})

    artifact = await run_agent_step(
        ws, pipeline, step, ctx, repo=repo, adapter=adapter
    )

    # artifact captured
    assert artifact.step_id == "plan"
    assert "1. do X" in artifact.output
    assert artifact.is_error is False
    assert artifact.cost_usd == 0.012
    assert artifact.diff == ""  # read-only planner makes no edits
    assert ctx.artifacts["plan"] is artifact
    assert ctx.total_cost_usd == 0.012

    # spans emitted
    names = [s.name for s in exporter.get_finished_spans()]
    assert SPAN_STEP in names
    assert SPAN_SESSION in names
    assert SPAN_TOOL_CALL in names  # the Read tool call


async def test_agent_step_captures_diff_when_harness_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    pipeline = ws.pipelines["feature"]
    step = next(s for s in pipeline.steps if s.id == "implement")
    # Make the fake harness write a file inside whatever worktree it runs in.
    # ORCH_FAKE_TOUCH is resolved relative to the harness CWD (the worktree).
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "note.txt")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="run2", inputs={"task": "edit something"})

    artifact = await run_agent_step(
        ws, pipeline, step, ctx, repo=repo, adapter=adapter
    )

    assert "note.txt" in artifact.diff
    assert artifact.branch.endswith("implement")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: FAIL — `run_agent_step` not defined.

- [ ] **Step 3: Implement the executor**

Create `orchestrator/runtime/executors.py`:

```python
"""Step executors. M2 implements the AgentStep lifecycle for a single step.

Out of M2 scope (later milestones): success_criteria + retry (M3), the review
loop (M4), knowledge injection (M6), the full DAG controller (M3).
"""

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
from orchestrator.safety.capabilities import resolve_capabilities

# Default prompts when a step declares no `prompt` (M2 minimal rendering).
_DEFAULT_PROMPTS = {
    "planner": "Create a concise implementation plan for this task:\n\n{task}",
}


def _render_prompt(step: Step, role_name: str, inputs: dict[str, str]) -> str:
    """Render the step prompt. M2: literal substitution of declared top-level
    input names only (`<task>` → value). Full dataflow templating is M3."""
    template = step.prompt
    if template is None:
        default = _DEFAULT_PROMPTS.get(role_name, "Work on this task:\n\n{task}")
        return default.format(task=inputs.get("task", ""))
    rendered = template
    for name, value in inputs.items():
        rendered = rendered.replace(f"<{name}>", value)
    return rendered


def _capture_diff(cwd: Path) -> str:
    """Diff of tracked changes + names of untracked files in the worktree."""
    tracked = subprocess.run(
        ["git", "diff"], cwd=cwd, capture_output=True, text=True
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout
    if untracked.strip():
        names = "\n".join(f"+++ untracked: {n}" for n in untracked.splitlines())
        tracked = f"{tracked}\n{names}" if tracked else names
    return tracked


async def run_agent_step(
    workspace: Workspace,
    pipeline: Pipeline,
    step: Step,
    ctx: RunContext,
    *,
    repo: Path,
    adapter: HarnessAdapter,
) -> Artifact:
    """Run a single agent step end-to-end (spec §6 AgentStep, M2 subset)."""
    if step.role is None:
        raise ValueError(f"step '{step.id}' is not an agent step (no role)")
    role = workspace.roles[step.role]
    caps = resolve_capabilities(role, workspace)

    branch = f"orch/{ctx.run_id}/{step.id}"
    worktree = create_worktree(Path(repo), branch=branch)

    tracer = get_tracer()
    text_parts: list[str] = []
    result_text = ""
    cost_usd = 0.0
    tokens = 0
    is_error = False

    try:
        with tracer.start_as_current_span(SPAN_STEP) as step_span:
            step_span.set_attribute("step.id", step.id)
            step_span.set_attribute("step.role", step.role)
            step_span.set_attribute("step.harness", role.harness.value)

            prompt = _render_prompt(step, step.role, ctx.inputs)
            session = await adapter.start_session(
                cwd=worktree.path, caps=caps, mcp_servers=[]
            )

            with tracer.start_as_current_span(SPAN_SESSION) as sess_span:
                stream = await adapter.prompt(session, prompt, output_schema=step.output_schema)
                async for ev in stream:
                    if isinstance(ev, MessageChunk):
                        text_parts.append(ev.text)
                    elif isinstance(ev, ToolCall):
                        with tracer.start_as_current_span(SPAN_TOOL_CALL) as tc:
                            tc.set_attribute("tool.name", ev.name)
                            tc.set_attribute("tool.status", ev.status)
                    elif isinstance(ev, FileEdit):
                        with tracer.start_as_current_span(SPAN_FILE_EDIT) as fe:
                            fe.set_attribute("file.path", ev.path)
                            fe.set_attribute("file.kind", ev.kind)
                    elif isinstance(ev, Cost):
                        cost_usd = ev.usd
                        tokens = ev.tokens
                        sess_span.set_attribute("cost.usd", ev.usd)
                        sess_span.set_attribute("cost.tokens", ev.tokens)
                    elif isinstance(ev, Done):
                        result_text = ev.result
                        is_error = ev.is_error
                        sess_span.set_attribute("done.is_error", ev.is_error)
                sess_span.set_attribute("session.handle", session)

            diff = _capture_diff(worktree.path)
            step_span.set_attribute("step.is_error", is_error)

        output = result_text or "".join(text_parts)
        artifact = Artifact(
            step_id=step.id,
            output=output,
            diff=diff,
            branch=branch,
            cost_usd=cost_usd,
            tokens=tokens,
            is_error=is_error,
        )
        ctx.record(artifact)
        return artifact
    finally:
        # M2: worktrees are cleaned up after a step. (Retain-on-failure is M3.)
        remove_worktree(Path(repo), worktree)
```

> Diff-capture caveat: `remove_worktree` runs in `finally` **after** the diff is captured, so the diff is available in the artifact even though the worktree is then removed. Do not move `_capture_diff` after cleanup.

- [ ] **Step 4: Re-export from the runtime package**

Update `orchestrator/runtime/__init__.py`:

```python
"""Runtime layer: run state + step executors (spec §6)."""

from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import Artifact, RunContext

__all__ = ["Artifact", "RunContext", "run_agent_step"]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_agent_step.py -v`
Expected: PASS — both the read-only plan step (empty diff, spans present) and the editing step (diff captures `note.txt`).

- [ ] **Step 6: Commit**

```bash
git add orchestrator/runtime/executors.py orchestrator/runtime/__init__.py tests/integration/test_agent_step.py
git commit -m "feat(m2): AgentStep executor — single step end-to-end with spans"
```

---

## Task 15: CLI `orch run --only <step>` + verification

**Files:**
- Modify: `orchestrator/cli.py`
- Test: `tests/integration/test_run_cli.py`

Wire the executor to the CLI. M2 runs exactly one agent step via `--only`. The default harness binary is the real `claude`, overridable with `ORCH_CLAUDE_BIN` (tests point it at the fake harness).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_run_cli.py`:

```python
import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

from orchestrator.cli import app
from tests.fixtures.repo import make_repo

runner = CliRunner()

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = Path("examples/feature-pipeline/.orchestrator")


def test_run_only_plan_step(tmp_path, monkeypatch):
    # Copy the example workspace into a throwaway git repo so the worktree
    # is created in an isolated place.
    repo = make_repo(tmp_path / "repo")
    dest = repo / ".orchestrator"
    shutil.copytree(EXAMPLE, dest)

    monkeypatch.setenv("ORCH_CLAUDE_BIN", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))

    result = runner.invoke(
        app,
        [
            "run",
            "feature",
            "--task",
            "add a feature",
            "--only",
            "plan",
            "--root",
            str(dest),
            "--repo",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "plan" in result.output
    assert "cost" in result.output.lower()


def test_run_requires_only_in_m2(tmp_path):
    result = runner.invoke(app, ["run", "feature"])
    # Without --only, M2 cannot run the full DAG yet.
    assert result.exit_code == 2
    assert "only" in result.output.lower()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_run_cli.py -v`
Expected: FAIL — `run` is still the M1 stub.

- [ ] **Step 3: Implement the `run` command**

In `orchestrator/cli.py`, replace the `run` stub. Keep `status`/`resume` stubbed (update their message to say M5/M6). Add imports at the top:

```python
import asyncio
import os
import uuid

from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import SPAN_RUN, configure_tracing, get_tracer
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext
from orchestrator.config.schemas import StepType
```

Replace the `run` function:

```python
@app.command()
def run(
    pipeline: str = typer.Argument(..., help="Pipeline name (file stem under pipelines/)."),
    task: str = typer.Option("", "--task", help="Value for the pipeline's `task` input."),
    only: str = typer.Option(
        "", "--only", help="Run exactly one agent step by id (required in M2)."
    ),
    root: Path = typer.Option(
        Path(".orchestrator"), "--root", help="Path to the .orchestrator/ workspace."
    ),
    repo: Path = typer.Option(
        Path("."), "--repo", help="Git repo to create the step's worktree in."
    ),
) -> None:
    """Run a pipeline. M2 runs a single agent step via --only; the full DAG is M3."""
    if not only:
        typer.echo("error: M2 can only run one agent step — pass --only <step_id>.")
        raise typer.Exit(2)

    try:
        workspace = load_workspace(root)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}")
        raise typer.Exit(1) from exc

    pipe = workspace.pipelines.get(pipeline)
    if pipe is None:
        available = ", ".join(sorted(workspace.pipelines)) or "(none)"
        typer.echo(f"error: unknown pipeline '{pipeline}'; available: {available}")
        raise typer.Exit(1)

    step = next((s for s in pipe.steps if s.id == only), None)
    if step is None:
        typer.echo(f"error: pipeline '{pipeline}' has no step '{only}'.")
        raise typer.Exit(1)
    if step.type is not StepType.agent:
        typer.echo(f"error: step '{only}' is type '{step.type.value}'; M2 runs agent steps only.")
        raise typer.Exit(2)

    configure_tracing(exporter=None)
    adapter = ClaudeCodeCLIAdapter()  # honors $ORCH_CLAUDE_BIN
    ctx = RunContext(run_id=uuid.uuid4().hex[:8], inputs={"task": task})

    async def _go():
        tracer = get_tracer()
        with tracer.start_as_current_span(SPAN_RUN) as run_span:
            run_span.set_attribute("run.id", ctx.run_id)
            run_span.set_attribute("pipeline", pipeline)
            return await run_agent_step(workspace, pipe, step, ctx, repo=repo, adapter=adapter)

    artifact = asyncio.run(_go())

    status_word = "ERROR" if artifact.is_error else "OK"
    typer.echo(f"{status_word}: step '{artifact.step_id}' (run {ctx.run_id})")
    typer.echo(f"  branch: {artifact.branch}")
    typer.echo(f"  cost: ${artifact.cost_usd:.4f} ({artifact.tokens} tokens)")
    if artifact.diff:
        typer.echo(f"  diff: {len(artifact.diff.splitlines())} line(s) changed")
    typer.echo("---- output ----")
    typer.echo(artifact.output)
    if artifact.is_error:
        raise typer.Exit(1)
```

Update the `status`/`resume` stub message (optional cosmetic): change `_not_implemented` text from "M1" to "a later milestone" so it is not misleading.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_run_cli.py -v`
Expected: PASS

- [ ] **Step 5: Full suite + lint + manual smoke**

Run: `uv run --extra dev python -m pytest`
Expected: all tests pass (M1 + M2).

Run: `uv run --extra dev ruff check .`
Expected: no errors. Fix any (e.g., unused imports, import ordering). If a `(str, Enum)` UP042 appears it is already globally ignored.

Manual smoke (proves M2's headline capability end-to-end against the fake harness):

```bash
ORCH_CLAUDE_BIN="$(uv run python -c 'import sys; print(sys.executable)') tests/fixtures/fake_harness/fake_harness.py" \
ORCH_FAKE_SCRIPT="tests/fixtures/fake_harness/scripts/plan.ndjson" \
uv run orch run feature --task "add a widget" --only plan --root examples/feature-pipeline/.orchestrator --repo .
```

Expected: prints `OK: step 'plan' ...`, a cost line, and the plan output. (Note: this creates a worktree under `.worktrees/`; it is auto-removed by the executor's cleanup. `.worktrees/` is already gitignored from M1 — verify with `git status` that nothing stray is staged.)

- [ ] **Step 6: Commit**

```bash
git add orchestrator/cli.py tests/integration/test_run_cli.py
git commit -m "feat(m2): orch run --only runs a single agent step end-to-end"
```

---

## Self-review (against spec §5, §6, §9, §12 M2)

**Spec coverage check:**

- **M2 = "adapter interface + ClaudeCode adapter + worktree: a single `plan` agent step runs end-to-end with spans."** → Tasks 2–3 (interface), 5–6+10 (ClaudeCode adapter), 11 (worktree), 14 (single step end-to-end), 13+14 (spans). ✅
- **HarnessAdapter Protocol (§5)** — `start_session/prompt/resume/cancel`. ✅ (Task 3)
- **Normalized event model (§5)** — all six event types. ✅ (Task 2)
- **ClaudeCodeCLIAdapter (§5)** — `claude -p --output-format stream-json`, NDJSON parse (`system/init`→SessionStarted, deltas→MessageChunk, tool events→ToolCall, final→Done+Cost), `--resume` handle, `--allowedTools/--disallowedTools/--permission-mode/--add-dir`. ✅ (Tasks 5,6,10) — `--mcp-config` / `--json-schema` wiring deferred (no MCP servers / output schema enforcement in M2; noted).
- **Adapter owns diff capture + capability translation (§5)** — `_capture_diff` (executor calls git diff in worktree; the adapter exposes the worktree cwd) + `translate`. ✅ Note: diff capture is invoked by the executor using the worktree path (the adapter provides cwd context); spec assigns "diff capture" to the adapter layer — kept pragmatically in the executor for M2 since it owns the worktree. Acceptable; revisit if the adapter needs to own it in M3.
- **7-dimension capability model + resolution + translation (§4.1)** — preset→dims, deny-wins, knowledge-write gating, global deny-list merge, translation to flags. ✅ (Tasks 7,8,10). Network egress + secrets enforcement are represented in `ResolvedCaps` but not yet enforced by the harness (documented; OS-level enforcement is M6/deferred).
- **Worktree isolation (§6)** — create/remove. ✅ (Task 11). Credential exclusion/config read-only represented in `ResolvedCaps.deny_read` (Task 8); `--add-dir`/denyRead enforcement is partially translated (add-dir) — full denyRead flag wiring deferred with a note.
- **OTel spans (§9)** — run/step/session/tool_call/file_edit + cost attributes. ✅ (Tasks 13,14).
- **Fake-harness adapter contract test + integration (§9)** — zero-API tests. ✅ (Tasks 4,6,14,15).
- **`mode` enum + access.knowledge cross-validation (M1 follow-ups marked "early M2")** — folded in. ✅ (Tasks 1,9).

**Deliberately deferred (with notes in-task):** `--mcp-config` generation + knowledge MCP wiring (M6); `--json-schema` output enforcement (M3 typed I/O); OS-level network/secrets enforcement (deferred per spec §9); `success_criteria`/retry (M3); resume re-prompt (M3); the `<...>`-vs-prose prompt syntax decision (still open — M2 sidesteps it by substituting only declared input names).

**Type consistency check:** `ResolvedCaps` fields used identically across `resolve_capabilities` (Task 8), `translate` (Task 10), and the executor (Task 14). `Artifact`/`RunContext` signatures match between Task 12 and Task 14. `run_agent_step` signature matches between Task 14 and the CLI (Task 15). Event types from Task 2 used consistently in parser (Task 5), adapter (Task 6), executor (Task 14). ✅

**Placeholder scan:** No TBD/TODO-style placeholders; every code step contains complete code. ✅

---

## Execution handoff

**Dependency-correct execution order** (component numbering differs from dispatch order because Task 6's contract test needs `ResolvedCaps` from Task 8):

```
1 → 2 → 3 → 4 → 5 → 7 → 8 → 6 → 9 → 10 → 11 → 12 → 13 → 14 → 15
```

Rationale: events (2) and the Protocol (3) come first; the fake harness (4) and pure parser (5) need only events; capabilities (7→8) must exist before the adapter's streaming contract test (6) and before translation (10); the loader change (9) makes the example load under the new cross-validation (capabilities tests against the example depend on it — if Task 8's example-based tests fail on the `lessons` source, do 9 first). Worktree (11), state (12), spans (13) are independent leaves feeding the executor (14); the CLI (15) is last.

This plan is intended for **superpowers:subagent-driven-development**: one fresh implementer subagent per task, spec-compliance review then code-quality review between tasks, in an isolated worktree, finishing by merging to `orchestrator-design` (the established M-series workflow).
