# M6a — OpenCode Adapter + Harness Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second `HarnessAdapter` (`OpenCodeCLIAdapter`) and a per-role harness registry so a pipeline can run different steps on different harnesses — proving the project's swappability thesis (harness ≠ model).

**Architecture:** Today a single adapter is injected top-to-bottom and `run_agent_step` ignores `role.harness`. M6a introduces `HarnessRegistry` (maps `Harness` → adapter); the `DeterministicScheduler` resolves the adapter per `role.harness` in `_make_node` and passes the concrete adapter into the (unchanged) executors. `OpenCodeCLIAdapter` mirrors `ClaudeCodeCLIAdapter`: spawns `opencode run`, parses its NDJSON into the normalized event model, and translates `ResolvedCaps` into an OpenCode permission config injected via `OPENCODE_CONFIG` (a temp file, so the worktree diff stays clean — OpenCode has no OS sandbox, so the worktree is the hard boundary).

**Tech Stack:** Python 3.11, async subprocess, Pydantic v2, Typer, pytest-asyncio. Package manager: **uv** (`uv run --extra dev python -m pytest`, `uv run --extra dev ruff check .`). NEVER system pip.

**This is M6a — the first of the split M6 sub-milestones** (M6 = orchestrator agent + knowledge provider + OpenCode adapter + `orch status` + safety polish, built one subsystem at a time). M6a is the OpenCode adapter only. No orchestrator-agent / knowledge / status / safety work here.

## Verified external facts (OpenCode CLI, confirmed against source docs before writing this plan)

- `opencode run --format json` emits **newline-delimited JSON** events: `step_start`, `text`, `tool_use`, `step_finish`, each with `type`, `timestamp`, `sessionID`, + event data. Cost/tokens ride on `step_finish`.
- `run` flags: `--model`/`-m` (`provider/model`, e.g. `zhipu/glm-4.6`), `--dir <path>` (working dir), `--format json`, `--print-logs` (logs → stderr, keeps stdout clean for JSON), `--session`/`--continue` (resume). The prompt is a positional argument.
- **`OPENCODE_CONFIG=/path/to/config.json`** (env var) points OpenCode at a config file — used here to inject the permission map WITHOUT writing into the worktree.
- Permission schema (`permission` key): values are `"allow" | "ask" | "deny"`, or an object of `pattern → verdict` for `bash`/`edit`/`read`/`external_directory`. Example:
  ```json
  {"permission": {"edit": "deny", "bash": {"git *": "allow", "rm *": "deny", "*": "ask"},
                   "read": {"*": "allow", "*.env": "deny"}}}
  ```
- OpenCode has **no OS sandbox** (spec §4.1) → filesystem/network are NOT OS-enforced; the orchestrator's worktree is the real isolation boundary. Caps translation is therefore best-effort at the tool/permission level (user decision for M6a).

> **Real-vs-fake note:** like the Claude adapter in M2, M6a is built and tested against a **fake `opencode` binary** that defines the NDJSON contract (zero API cost). The exact field names inside each event (e.g. whether tool name is under `tool` vs `name`, cost under `cost` vs `usage`) are not 100% pinned from docs; the parser is written tolerantly and the fake binary is the contract. Reconciling field names against the real `opencode` binary is a documented follow-up (mirrors how the real `claude` binary was wired after M2).

---

## File Structure

- `orchestrator/harness/opencode.py` (NEW) — `parse_opencode_line` (pure NDJSON→events), `OpenCodeCLIAdapter` (spawn/stream/translate).
- `orchestrator/harness/registry.py` (NEW) — `HarnessRegistry` (per-`Harness` adapter resolution; `.single()` back-compat; `.from_env()` default).
- `orchestrator/runtime/scheduler.py` — accept adapter-or-registry; resolve per `role.harness` in `_make_node`.
- `orchestrator/runtime/controller.py` — pass adapter-or-registry through.
- `orchestrator/cli.py` — build `HarnessRegistry.from_env()`; `--only` resolves the step's harness adapter.
- `tests/fixtures/fake_opencode/fake_opencode.py` (+ `__init__.py`, `scripts/`) (NEW) — fake OpenCode binary.
- `examples/feature-pipeline/.orchestrator/roles/opencoder.yaml` (NEW) — an `opencode` role.
- `examples/feature-pipeline/.orchestrator/pipelines/mixed-harness.yaml` (NEW) — Claude classify + OpenCode implement.
- Tests: `tests/unit/test_opencode_parser.py`, `tests/unit/test_opencode_translate.py`, `tests/unit/test_registry.py`, `tests/integration/test_opencode_adapter.py`, `tests/integration/test_mixed_harness.py` (NEW).

---

## Task 1: OpenCode NDJSON parser (pure function)

**Files:**
- Create: `orchestrator/harness/opencode.py` (parser only this task)
- Test: `tests/unit/test_opencode_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_opencode_parser.py
from orchestrator.harness.events import Cost, FileEdit, MessageChunk, SessionStarted, ToolCall
from orchestrator.harness.opencode import parse_opencode_line


def test_step_start_to_session_started():
    evs = parse_opencode_line({"type": "step_start", "sessionID": "oc-1"}, {})
    assert evs == [SessionStarted("oc-1")]


def test_text_to_message_chunk():
    evs = parse_opencode_line({"type": "text", "text": "hello "}, {})
    assert evs == [MessageChunk("hello ")]


def test_tool_use_read_is_in_progress_no_fileedit():
    evs = parse_opencode_line(
        {"type": "tool_use", "tool": "read", "id": "t1", "input": {"path": "README.md"}}, {}
    )
    assert ToolCall("read", "in_progress") in evs
    assert not any(isinstance(e, FileEdit) for e in evs)


def test_tool_use_edit_emits_fileedit():
    evs = parse_opencode_line(
        {"type": "tool_use", "tool": "edit", "id": "t2", "input": {"path": "src/a.py"}}, {}
    )
    assert ToolCall("edit", "in_progress") in evs
    assert FileEdit("src/a.py", "modify") in evs


def test_step_finish_emits_cost():
    evs = parse_opencode_line({"type": "step_finish", "cost": 0.004, "tokens": 120}, {})
    assert evs == [Cost(usd=0.004, tokens=120)]


def test_unknown_event_ignored():
    assert parse_opencode_line({"type": "whatever"}, {}) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_opencode_parser.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.harness.opencode`).

- [ ] **Step 3: Implement the parser**

Create `orchestrator/harness/opencode.py`:

```python
"""OpenCodeCLIAdapter: drive `opencode run --format json` (spec §5, 2nd adapter).

Proves harness != model: OpenCode reaches 75+ providers (e.g. zhipu/glm-4.6).
Mirrors ClaudeCodeCLIAdapter: pure NDJSON parser + async streaming + caps
translation. OpenCode has no OS sandbox, so the worktree is the isolation
boundary; caps translate to an OpenCode permission config (best-effort).
"""

from __future__ import annotations

from orchestrator.harness.events import (
    Cost,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)

# OpenCode tool names that mutate files → also emit a FileEdit.
_EDIT_TOOLS = {"edit": "modify", "write": "create", "patch": "modify"}


def parse_opencode_line(obj: dict, tool_names: dict[str, str]) -> list[Event]:
    """Map one decoded OpenCode JSON event to normalized events.

    `tool_names` is mutated (tool id → name) for symmetry with the Claude
    parser; OpenCode reports tool completion on `step_finish`/separate events
    which the adapter does not currently surface as completed ToolCalls.
    """
    kind = obj.get("type")

    if kind == "step_start":
        return [SessionStarted(obj.get("sessionID", ""))]

    if kind == "text":
        return [MessageChunk(obj.get("text", ""))]

    if kind == "tool_use":
        name = obj.get("tool", "") or obj.get("name", "")
        tool_id = obj.get("id", "")
        if tool_id:
            tool_names[tool_id] = name
        events: list[Event] = [ToolCall(name, "in_progress")]
        if name in _EDIT_TOOLS:
            path = (obj.get("input", {}) or {}).get("path", "") or (
                obj.get("input", {}) or {}
            ).get("file_path", "")
            if path:
                events.append(FileEdit(path, _EDIT_TOOLS[name]))
        return events

    if kind == "step_finish":
        return [Cost(usd=float(obj.get("cost", 0.0)), tokens=int(obj.get("tokens", 0)))]

    return []
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_opencode_parser.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/harness/opencode.py tests/unit/test_opencode_parser.py
git commit -m "feat(m6a): OpenCode NDJSON parser → normalized event model"
```

---

## Task 2: OpenCode caps translation (permission config)

**Files:**
- Modify: `orchestrator/harness/opencode.py` (add `build_permission_config`)
- Test: `tests/unit/test_opencode_translate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_opencode_translate.py
from orchestrator.harness.opencode import build_permission_config
from orchestrator.safety.capabilities import ResolvedCaps


def test_read_only_denies_edit_and_bash():
    cfg = build_permission_config(ResolvedCaps.read_only())
    perm = cfg["permission"]
    assert perm["edit"] == "deny"
    # bash either a flat "deny" or an object whose default denies
    assert perm["bash"] == "deny" or perm["bash"].get("*") == "deny"


def test_edit_role_allows_edit():
    caps = ResolvedCaps(allowed_tools=("Edit", "Write"), disallowed_tools=(),
                        permission_mode="acceptEdits")
    cfg = build_permission_config(caps)
    assert cfg["permission"]["edit"] == "allow"


def test_shell_deny_patterns_become_bash_denies():
    caps = ResolvedCaps(allowed_tools=("Bash",), disallowed_tools=(),
                        permission_mode="acceptEdits", role_shell_deny=("rm -rf", "git push --force"))
    bash = build_permission_config(caps)["permission"]["bash"]
    assert isinstance(bash, dict)
    assert bash.get("rm -rf*") == "deny" or bash.get("rm -rf") == "deny"
    assert bash.get("*") in ("allow", "ask")


def test_env_files_are_read_denied():
    cfg = build_permission_config(ResolvedCaps.read_only())
    read = cfg["permission"].get("read", {})
    assert read.get("*.env") == "deny"
```

> IMPLEMENTER NOTE: `ResolvedCaps` is a frozen dataclass — check its actual fields first (`orchestrator/safety/capabilities.py`). It has `allowed_tools`, `disallowed_tools`, `permission_mode`. It may NOT have a `role_shell_deny` attribute on the resolved object (that name appears in the resolver internals). If `ResolvedCaps` does not carry shell-deny patterns, do ONE of: (a) read them from a field that does exist, or (b) add a `shell_deny: tuple[str, ...] = ()` field to `ResolvedCaps` and populate it in `resolve_capabilities` (small, additive). Pick the approach that fits the existing shape; adjust the test's caps construction to match `ResolvedCaps`'s real signature. The REQUIRED behavior: read-only → edit/bash denied; edit role → edit allowed; shell-deny patterns → bash deny entries; `.env` read-denied.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_opencode_translate.py -v`
Expected: FAIL (`build_permission_config` missing).

- [ ] **Step 3: Implement**

Add to `orchestrator/harness/opencode.py` (decide read-only vs edit by whether edit tools are allowed; map shell-deny patterns to bash denies; always read-deny credential files):

```python
from orchestrator.safety.capabilities import ResolvedCaps

# Credential-ish paths excluded from reads (mirrors spec §4.1 fs credential exclusion).
_READ_DENY = ["*.env", "*.env.*", "**/.ssh/**", "**/.aws/**"]


def _can_edit(caps: ResolvedCaps) -> bool:
    edit_markers = {"Edit", "Write", "MultiEdit", "edit", "write", "patch"}
    if any(t in edit_markers for t in caps.disallowed_tools):
        return False
    return any(t in edit_markers for t in caps.allowed_tools) or caps.permission_mode != "default"


def build_permission_config(caps: ResolvedCaps) -> dict:
    """ResolvedCaps → an OpenCode `permission` config (best-effort).

    OpenCode has no OS sandbox; this constrains the agent's tools, while the
    worktree remains the hard filesystem boundary.
    """
    can_edit = _can_edit(caps)
    shell_deny = tuple(getattr(caps, "shell_deny", ()) or ())
    bash: dict[str, str] | str
    if not can_edit:
        bash = "deny"
    else:
        bash = {f"{pat}*" if not pat.endswith("*") else pat: "deny" for pat in shell_deny}
        bash["*"] = "allow"
    read = {"*": "allow"}
    for pat in _READ_DENY:
        read[pat] = "deny"
    return {
        "permission": {
            "edit": "allow" if can_edit else "deny",
            "bash": bash,
            "read": read,
        }
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_opencode_translate.py -v`
Expected: PASS. If you added a `shell_deny` field to `ResolvedCaps`, also run the full suite to confirm `resolve_capabilities` still passes: `uv run --extra dev python -m pytest -q`.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/harness/opencode.py tests/unit/test_opencode_translate.py
# include capabilities.py if you added the shell_deny field:
git add -A
git commit -m "feat(m6a): translate caps → OpenCode permission config (worktree is the boundary)"
```

---

## Task 3: Fake OpenCode binary (test fixture)

**Files:**
- Create: `tests/fixtures/fake_opencode/__init__.py` (empty)
- Create: `tests/fixtures/fake_opencode/fake_opencode.py`
- Create: `tests/fixtures/fake_opencode/scripts/implement.ndjson`, `scripts/default.ndjson`

- [ ] **Step 1: Create the fake binary**

`tests/fixtures/fake_opencode/fake_opencode.py` (mirrors `tests/fixtures/fake_harness/fake_harness.py` — read that first for the env-var conventions):

```python
#!/usr/bin/env python3
"""Fake `opencode` binary for tests. Zero API cost.

- Records argv (one per line) to $ORCH_OC_ARGV (if set).
- Records the OPENCODE_CONFIG file path to $ORCH_OC_CONFIG_SEEN (if set).
- Streams the NDJSON at $ORCH_OC_SCRIPT (default scripts/default.ndjson) to stdout.
- If $ORCH_OC_TOUCH is set, creates that file in --dir (or cwd) before finishing.
- Exits 0 unless $ORCH_OC_EXIT is set non-zero.
"""

import os
import sys
from pathlib import Path

DEFAULT_SCRIPT = Path(__file__).parent / "scripts" / "default.ndjson"


def main() -> int:
    args = sys.argv[1:]
    argv_file = os.environ.get("ORCH_OC_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(args))

    cfg_seen = os.environ.get("ORCH_OC_CONFIG_SEEN")
    if cfg_seen:
        Path(cfg_seen).write_text(os.environ.get("OPENCODE_CONFIG", ""))

    # working dir: the value after --dir, else cwd
    workdir = Path(".")
    if "--dir" in args:
        i = args.index("--dir")
        if i + 1 < len(args):
            workdir = Path(args[i + 1])

    touch = os.environ.get("ORCH_OC_TOUCH")
    if touch:
        (workdir / touch).write_text("created by fake opencode\n")

    script = Path(os.environ.get("ORCH_OC_SCRIPT", str(DEFAULT_SCRIPT)))
    sys.stdout.write(script.read_text())
    sys.stdout.flush()
    return int(os.environ.get("ORCH_OC_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
```

`tests/fixtures/fake_opencode/scripts/default.ndjson`:

```
{"type":"step_start","sessionID":"oc-default-1","timestamp":1}
{"type":"text","text":"Working. "}
{"type":"tool_use","tool":"read","id":"t1","input":{"path":"README.md"}}
{"type":"text","text":"Done."}
{"type":"step_finish","cost":0.003,"tokens":80}
```

`tests/fixtures/fake_opencode/scripts/implement.ndjson`:

```
{"type":"step_start","sessionID":"oc-impl-1","timestamp":1}
{"type":"text","text":"Implementing. "}
{"type":"tool_use","tool":"edit","id":"t1","input":{"path":"feature.py"}}
{"type":"text","text":"Implemented the feature."}
{"type":"step_finish","cost":0.006,"tokens":150}
```

- [ ] **Step 2: Smoke the fixture**

Run: `ORCH_OC_SCRIPT=tests/fixtures/fake_opencode/scripts/implement.ndjson uv run python tests/fixtures/fake_opencode/fake_opencode.py run -m zhipu/glm-4.6 --dir . --format json "do it"`
Expected: prints the implement NDJSON to stdout, exit 0.

- [ ] **Step 3: ruff + commit**

```bash
uv run --extra dev ruff check .
git add tests/fixtures/fake_opencode/
git commit -m "test(m6a): fake opencode binary + NDJSON scripts (zero-cost contract)"
```

---

## Task 4: OpenCodeCLIAdapter (async streaming + spawn + Done synthesis)

**Files:**
- Modify: `orchestrator/harness/opencode.py` (add the adapter class)
- Test: `tests/integration/test_opencode_adapter.py`

- [ ] **Step 1: Write the failing test** (mirrors `tests/integration/test_adapter_contract.py`)

```python
# tests/integration/test_opencode_adapter.py
import sys
from pathlib import Path

import pytest

from orchestrator.harness.events import Cost, Done, FileEdit, SessionStarted, ToolCall
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, text):
    session = await adapter.start_session(cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=[])
    events = []
    stream = await adapter.prompt(session, text)
    async for ev in stream:
        events.append(ev)
    return session, events


async def test_streams_normalized_events(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "implement.ndjson"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "implement it")
    assert isinstance(events[0], SessionStarted)
    assert events[0].session_id == "oc-impl-1"
    assert any(isinstance(e, ToolCall) and e.name == "edit" for e in events)
    assert any(isinstance(e, FileEdit) and e.path == "feature.py" for e in events)
    assert any(isinstance(e, Cost) and e.usd == 0.006 for e in events)
    assert isinstance(events[-1], Done) and events[-1].is_error is False
    assert "Implemented the feature." in events[-1].result


async def test_passes_model_dir_and_format(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_ARGV", str(tmp_path / "argv.txt"))
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)], model="zhipu/glm-4.6")
    await _drive(adapter, tmp_path, "hello oc")
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "run" in argv
    assert "--format" in argv and "json" in argv
    assert "-m" in argv and "zhipu/glm-4.6" in argv
    assert "--dir" in argv
    assert "hello oc" in argv


async def test_caps_written_to_opencode_config(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_CONFIG_SEEN", str(tmp_path / "cfgpath.txt"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, "x")
    cfg_path = (tmp_path / "cfgpath.txt").read_text().strip()
    assert cfg_path, "OPENCODE_CONFIG should be set for the subprocess"
    import json
    perm = json.loads(Path(cfg_path).read_text())["permission"]
    assert perm["edit"] == "deny"  # read_only caps
    # the config lives OUTSIDE the worktree (no diff pollution)
    assert str(tmp_path) not in cfg_path or "/.orch-oc/" in cfg_path or "tmp" in cfg_path.lower()


async def test_nonzero_exit_yields_error_done(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_EXIT", "2")
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "x")
    assert isinstance(events[-1], Done) and events[-1].is_error is True
```

> IMPLEMENTER NOTE on the config-location assertion: write the permission config to a path OUTSIDE the worktree (e.g. a `tempfile.NamedTemporaryFile(delete=False, suffix=".json")` or under a per-session temp dir) so it never appears in `git diff`. The last assertion in `test_caps_written_to_opencode_config` is intentionally loose; make it pass by using a system temp path (which contains "tmp"). Clean the temp file in `cancel()` or after the stream ends if practical (a leaked temp file in $TMPDIR is acceptable for MVP).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_opencode_adapter.py -v`
Expected: FAIL (`OpenCodeCLIAdapter` missing).

- [ ] **Step 3: Implement the adapter**

Add to `orchestrator/harness/opencode.py` (mirror `ClaudeCodeCLIAdapter` structure — read it first):

```python
import asyncio
import json
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from orchestrator.harness.adapter import McpServer, SessionId
from orchestrator.harness.events import Done, SessionStarted


@dataclass
class _OCSession:
    cwd: Path
    caps: ResolvedCaps
    mcp_servers: list[McpServer]
    config_path: str | None = None
    harness_session_id: str | None = None


class OpenCodeCLIAdapter:
    """Drives OpenCode via `opencode run --format json`.

    `binary` default `["opencode"]`; honors $ORCH_OPENCODE_BIN. `model` is the
    `provider/model` string (from the role); `glm` is aliased to zhipu/glm-4.6.
    """

    def __init__(self, binary: list[str] | None = None, *, model: str | None = None) -> None:
        if binary is None:
            env_bin = os.environ.get("ORCH_OPENCODE_BIN")
            binary = env_bin.split() if env_bin else ["opencode"]
        self._binary = binary
        self._model = _alias_model(model)
        self._sessions: dict[SessionId, _OCSession] = {}

    async def start_session(self, *, cwd: Path, caps: ResolvedCaps,
                            mcp_servers: list[McpServer]) -> SessionId:
        handle = uuid.uuid4().hex
        cfg = build_permission_config(caps)
        fd, path = tempfile.mkstemp(prefix="orch-oc-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg, fh)
        self._sessions[handle] = _OCSession(
            cwd=Path(cwd), caps=caps, mcp_servers=list(mcp_servers), config_path=path
        )
        return handle

    async def prompt(self, session: SessionId, text: str, *,
                     output_schema: dict | None = None) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        cmd = [*self._binary, "run", "--format", "json", "--print-logs",
               "--dir", str(sess.cwd)]
        if self._model:
            cmd += ["-m", self._model]
        cmd.append(text)
        return self._stream(session, cmd)

    async def _stream(self, session: SessionId, cmd: list[str]) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        env = dict(os.environ)
        if sess.config_path:
            env["OPENCODE_CONFIG"] = sess.config_path
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(sess.cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        tool_names: dict[str, str] = {}
        text_parts: list[str] = []
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for ev in parse_opencode_line(obj, tool_names):
                if isinstance(ev, SessionStarted):
                    sess.harness_session_id = ev.session_id
                if isinstance(ev, MessageChunk):
                    text_parts.append(ev.text)
                yield ev
        returncode = await proc.wait()
        # OpenCode has no single "result" event; synthesize Done at stream end.
        yield Done(result="".join(text_parts), is_error=(returncode != 0))

    async def resume(self, session: SessionId) -> SessionId:
        return session

    async def cancel(self, session: SessionId) -> None:
        sess = self._sessions.pop(session, None)
        if sess and sess.config_path:
            try:
                os.unlink(sess.config_path)
            except OSError:
                pass
```

And add the model alias helper near the top of the module:

```python
_MODEL_ALIASES = {"glm": "zhipu/glm-4.6"}


def _alias_model(model: str | None) -> str | None:
    if model is None:
        return None
    return _MODEL_ALIASES.get(model, model)
```

(Ensure `Event` and `MessageChunk` are imported in the module — they are used by `_stream`.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_opencode_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/harness/opencode.py tests/integration/test_opencode_adapter.py
git commit -m "feat(m6a): OpenCodeCLIAdapter — spawn, stream NDJSON, synthesize Done, inject config"
```

---

## Task 5: HarnessRegistry (per-Harness adapter resolution)

**Files:**
- Create: `orchestrator/harness/registry.py`
- Test: `tests/unit/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_registry.py
import sys
from pathlib import Path

import pytest

from orchestrator.config.schemas import Harness
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry


def test_single_returns_same_adapter_for_any_harness():
    a = ClaudeCodeCLIAdapter(binary=["x"])
    reg = HarnessRegistry.single(a)
    assert reg.adapter_for(Harness.claude_code) is a
    assert reg.adapter_for(Harness.opencode) is a
    assert reg.default_adapter() is a


def test_explicit_mapping_routes_by_harness():
    claude = ClaudeCodeCLIAdapter(binary=["c"])
    oc = OpenCodeCLIAdapter(binary=["o"])
    reg = HarnessRegistry({Harness.claude_code: claude, Harness.opencode: oc})
    assert reg.adapter_for(Harness.claude_code) is claude
    assert reg.adapter_for(Harness.opencode) is oc


def test_unregistered_harness_raises():
    reg = HarnessRegistry({Harness.claude_code: ClaudeCodeCLIAdapter(binary=["c"])})
    with pytest.raises(KeyError):
        reg.adapter_for(Harness.codex)


def test_from_env_builds_claude_and_opencode(monkeypatch):
    monkeypatch.setenv("ORCH_CLAUDE_BIN", "fakeclaude")
    monkeypatch.setenv("ORCH_OPENCODE_BIN", "fakeoc")
    reg = HarnessRegistry.from_env()
    assert isinstance(reg.adapter_for(Harness.claude_code), ClaudeCodeCLIAdapter)
    assert isinstance(reg.adapter_for(Harness.opencode), OpenCodeCLIAdapter)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/unit/test_registry.py -v`
Expected: FAIL (`ModuleNotFoundError: orchestrator.harness.registry`).

- [ ] **Step 3: Implement**

Create `orchestrator/harness/registry.py`:

```python
"""HarnessRegistry: resolve a HarnessAdapter per role's harness (spec §5).

The swappability payoff: a pipeline can run different steps on different
harnesses. A bare adapter wraps to a `.single()` registry for back-compat with
the single-adapter call sites that predate M6a.
"""

from __future__ import annotations

from orchestrator.config.schemas import Harness
from orchestrator.harness.adapter import HarnessAdapter


class HarnessRegistry:
    def __init__(self, adapters: dict[Harness, HarnessAdapter] | None = None, *,
                 default: Harness = Harness.claude_code) -> None:
        self._adapters: dict[Harness, HarnessAdapter] = dict(adapters or {})
        self._single: HarnessAdapter | None = None
        self._default = default

    @classmethod
    def single(cls, adapter: HarnessAdapter) -> HarnessRegistry:
        """All harnesses resolve to one adapter (back-compat / tests)."""
        reg = cls()
        reg._single = adapter
        return reg

    @classmethod
    def from_env(cls) -> HarnessRegistry:
        """Default production registry: real adapters honoring $ORCH_*_BIN."""
        from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
        from orchestrator.harness.opencode import OpenCodeCLIAdapter

        return cls({
            Harness.claude_code: ClaudeCodeCLIAdapter(),
            Harness.opencode: OpenCodeCLIAdapter(),
        })

    def adapter_for(self, harness: Harness) -> HarnessAdapter:
        if self._single is not None:
            return self._single
        if harness not in self._adapters:
            raise KeyError(f"no adapter registered for harness '{harness.value}'")
        return self._adapters[harness]

    def default_adapter(self) -> HarnessAdapter:
        return self.adapter_for(self._default)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/unit/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/harness/registry.py tests/unit/test_registry.py
git commit -m "feat(m6a): HarnessRegistry — per-harness adapter resolution + single/from_env"
```

---

## Task 6: Wire the registry into the scheduler (resolve per role.harness)

**Files:**
- Modify: `orchestrator/runtime/scheduler.py`
- Modify: `orchestrator/runtime/controller.py`
- Test: `tests/integration/test_mixed_harness.py`

- [ ] **Step 1: Write the failing test** (a pipeline whose `classify` runs on Claude and `implement` runs on OpenCode, each driven by its fake)

```python
# tests/integration/test_mixed_harness.py
import subprocess
import sys
from pathlib import Path

from orchestrator.config.schemas import Harness, Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

CLAUDE_FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
CLAUDE_SCRIPTS = CLAUDE_FAKE.parent / "scripts"
OC_FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
OC_SCRIPTS = OC_FAKE.parent / "scripts"


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


async def test_mixed_harness_routes_by_role(tmp_path, monkeypatch):
    # The OpenCode implement step touches feature.py; assert its diff was captured.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(CLAUDE_SCRIPTS))
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(OC_SCRIPTS / "implement.ndjson"))
    monkeypatch.setenv("ORCH_OC_TOUCH", "feature.py")

    # Build a workspace in code with two roles on two harnesses.
    from orchestrator.config.loader import load_workspace
    ws = load_workspace(Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator")
    # ws must contain an 'opencoder' role with harness: opencode (added in Task 7).
    assert "opencoder" in ws.roles and ws.roles["opencoder"].harness == Harness.opencode

    registry = HarnessRegistry({
        Harness.claude_code: ClaudeCodeCLIAdapter(binary=[sys.executable, str(CLAUDE_FAKE)]),
        Harness.opencode: OpenCodeCLIAdapter(binary=[sys.executable, str(OC_FAKE)]),
    })
    repo = _repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, registry, repo, checkpoint_db=db)

    pipe = Pipeline(
        name="mixed",
        steps=[
            Step(id="classify", type=StepType.task, prompt="classify {{task}}"),
            Step(id="implement", role="opencoder", needs=["classify"],
                 prompt="implement {{task}}", success_criteria="true"),
        ],
    )
    ctx = await sched.run(pipe, {"task": "add widget"}, "run-mixed-1")
    assert ctx.status == RunStatus.COMPLETED
    impl = ctx.artifacts["implement"]
    assert not impl.is_error
    assert "feature.py" in impl.diff  # OpenCode's edit was captured


async def test_bare_adapter_still_works_backcompat(tmp_path, monkeypatch):
    # Passing a single adapter (pre-M6a call style) must still run.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(CLAUDE_SCRIPTS))
    from orchestrator.config.loader import load_workspace
    ws = load_workspace(Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(CLAUDE_FAKE)])
    repo = _repo(tmp_path)
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(name="p", steps=[Step(id="classify", type=StepType.task, prompt="c {{task}}")])
    ctx = await sched.run(pipe, {"task": "x"}, "run-bc-1")
    assert ctx.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev python -m pytest tests/integration/test_mixed_harness.py -v`
Expected: FAIL — first because `opencoder` role doesn't exist yet (Task 7), and because the scheduler doesn't accept a registry / doesn't route by harness. (You may implement Task 7's role file now if you want this test green within this task; the plan lists Task 7 separately for the example assets. Recommended: create `examples/.../roles/opencoder.yaml` as part of THIS task so the test runs, and let Task 7 add the demo pipeline + docs.)

- [ ] **Step 3: Implement — scheduler accepts a registry and resolves per harness**

In `orchestrator/runtime/scheduler.py`:

- Import: `from orchestrator.harness.registry import HarnessRegistry` and `from orchestrator.config.schemas import Harness` (StepType already imported).
- In `__init__`, normalize the `adapter` param to a registry:
  ```python
  def __init__(self, workspace, adapter, repo, *, checkpoint_db=None):
      self.workspace = workspace
      self.registry = adapter if isinstance(adapter, HarnessRegistry) else HarnessRegistry.single(adapter)
      self.repo = Path(repo)
      ...
  ```
  (Remove the old `self.adapter = adapter`.)
- In `_make_node`, resolve the adapter per step and pass the concrete adapter to the executor:
  ```python
  async def node(state: GraphState) -> dict:
      ctx = state["ctx"]
      if step.type == StepType.task:
          if step.merge_strategy is not None:
              adapter = self.registry.default_adapter()
              await run_merge_step(self.workspace, pipeline, step, ctx, repo=self.repo, adapter=adapter)
          else:
              adapter = self.registry.default_adapter()
              await run_task_step(self.workspace, pipeline, step, ctx, repo=self.repo, adapter=adapter)
      elif step.type == StepType.agent:
          harness = self.workspace.roles[step.role].harness
          adapter = self.registry.adapter_for(harness)
          await run_agent_step(self.workspace, pipeline, step, ctx, repo=self.repo, adapter=adapter)
      else:  # gate
          run_gate_step(step, ctx)
      return {"ctx": ctx}
  ```
  (Replace the previous `self.adapter` references.)

In `orchestrator/runtime/controller.py`: the `adapter` param type is now "adapter or registry"; no logic change needed (it passes through to the scheduler which normalizes). Update the type hint/docstring to note it accepts a `HarnessAdapter | HarnessRegistry`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --extra dev python -m pytest tests/integration/test_mixed_harness.py -v`
Expected: PASS (requires `examples/.../roles/opencoder.yaml` — create it now if not present; see Task 7 Step 1 for its content).

Then the FULL suite: `uv run --extra dev python -m pytest -q`. ALL existing tests pass a bare adapter to `DeterministicScheduler` → normalized via `.single` → unchanged behavior. Baseline before M6a was 169; expect prior tests still green + the new ones.

- [ ] **Step 5: ruff + commit**

```bash
uv run --extra dev ruff check .
git add orchestrator/runtime/scheduler.py orchestrator/runtime/controller.py examples/feature-pipeline/.orchestrator/roles/opencoder.yaml tests/integration/test_mixed_harness.py
git commit -m "feat(m6a): scheduler resolves adapter per role.harness via HarnessRegistry"
```

---

## Task 7: CLI wiring + example assets + docs

**Files:**
- Modify: `orchestrator/cli.py`
- Create: `examples/feature-pipeline/.orchestrator/roles/opencoder.yaml` (if not already created in Task 6)
- Create: `examples/feature-pipeline/.orchestrator/pipelines/mixed-harness.yaml`
- Test: extend `tests/integration/test_example_compiles.py` (or add a compile assertion)

- [ ] **Step 1: Create the OpenCode role**

`examples/feature-pipeline/.orchestrator/roles/opencoder.yaml`:

```yaml
# An implementer that runs on the OpenCode harness (harness != model).
harness: opencode
model: zhipu/glm-4.6        # provider/model; `glm` alias also accepted
permissions: edit
access:
  filesystem: { write: ["src/**", "tests/**"] }
  shell: { deny: ["rm -rf", "git push --force"] }
```

- [ ] **Step 2: Create the demo pipeline**

`examples/feature-pipeline/.orchestrator/pipelines/mixed-harness.yaml`:

```yaml
# M6a demo: classify on Claude (task) -> implement on OpenCode (harness != model).
mode: declarative
inputs: { task: string }
steps:
  - id: classify
    type: task
    prompt: 'Classify {{task}} as one of: bugfix | feature | refactor. Reply JSON {"kind":"<one>"}.'
    output_schema: { kind: "enum[bugfix,feature,refactor]" }
  - id: implement
    role: opencoder
    needs: [classify]
    prompt: "Kind: {{classify.output.kind}}\nImplement: {{task}}"
    success_criteria: "true"
```

- [ ] **Step 3: Wire the CLI to use the registry**

In `orchestrator/cli.py`:
- Add `from orchestrator.harness.registry import HarnessRegistry`.
- In `run`: replace `adapter = ClaudeCodeCLIAdapter()  # honors $ORCH_CLAUDE_BIN` with `registry = HarnessRegistry.from_env()`.
  - Full-pipeline path: pass `registry` to `make_controller(...)` (where `adapter` was passed).
  - `--only` path: resolve the step's adapter before calling `run_agent_step`:
    ```python
    adapter = registry.adapter_for(workspace.roles[step.role].harness)
    ```
    (the `--only` guard already ensures `step.type is agent`, so `step.role` exists).
- In `resume`: replace `adapter = ClaudeCodeCLIAdapter()` with `registry = HarnessRegistry.from_env()` and pass `registry` to `make_controller(...)`.

- [ ] **Step 4: Add a compile assertion for the new pipeline**

In `tests/integration/test_example_compiles.py` (read it first; if it iterates pipelines, `mixed-harness` is picked up automatically — then this step is just confirming it still passes). If it enumerates explicitly, add `mixed-harness` to the list. Run:

`uv run orch compile mixed-harness --root examples/feature-pipeline/.orchestrator`
Expected: `OK`, edges `classify --> implement`.

- [ ] **Step 5: Manual CLI smoke (real `orch`, fake binaries)**

From repo root, in a throwaway git repo, with `ORCH_CLAUDE_BIN`/`ORCH_FAKE_SCRIPT_DIR` and `ORCH_OPENCODE_BIN`/`ORCH_OC_SCRIPT` pointing at the fakes, run:
`uv run orch run mixed-harness --task "add a flag" --root examples/feature-pipeline/.orchestrator --repo <tmp-repo>`
Confirm both steps run (classify on the Claude fake, implement on the OpenCode fake) and the run completes. Capture the output for the M6a follow-ups note.

- [ ] **Step 6: Run the full suite + ruff + commit**

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev ruff check .
git add orchestrator/cli.py examples/feature-pipeline/.orchestrator/ tests/integration/test_example_compiles.py
git commit -m "feat(m6a): orch run/resume use HarnessRegistry; mixed-harness example + opencoder role"
```

---

## Task 8: M6a follow-ups note

**Files:**
- Create: `docs/superpowers/notes/m6a-opencode-followups.md`

- [ ] **Step 1: Write the note**

Capture, with rationale: what M6a shipped (OpenCode adapter + registry); the **real-vs-fake reconciliation** risk (OpenCode NDJSON field names — `tool` vs `name`, `cost`/`tokens` location, whether a final/error event exists — must be verified against the real `opencode` binary, parser is tolerant); caps translation is best-effort (no OS sandbox; worktree is the boundary); `Codex` adapter still not built (`adapter_for(Harness.codex)` raises); `output_schema` not yet passed to OpenCode; MCP servers still `[]` (knowledge provider is the next sub-milestone, M6b). Mirror the structure of `docs/superpowers/notes/m5-review-followups.md`.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/notes/m6a-opencode-followups.md
git commit -m "docs(m6a): OpenCode adapter follow-ups"
```

---

## Final Review (after all tasks)

Dispatch a final holistic reviewer (most capable model) over the whole M6a diff. Focus:
- **Registry back-compat**: every pre-M6a call site (bare adapter → `DeterministicScheduler`) still works via `.single`; confirm by the full suite staying green and the explicit `test_bare_adapter_still_works_backcompat`.
- **Per-harness routing**: agent steps use `role.harness`'s adapter; task/merge/gate use the default; `--only` resolves correctly.
- **Adapter parity**: `OpenCodeCLIAdapter` satisfies the same `HarnessAdapter` Protocol contract as Claude (SessionStarted → … → Done; non-zero exit → error Done; no stderr deadlock — note OpenCode `--print-logs` writes to stderr which is `DEVNULL`'d).
- **No worktree pollution**: the permission config is written outside the worktree (`OPENCODE_CONFIG`), so agent diffs never include it.
- **Scope**: no orchestrator-agent / knowledge / status / safety-polish work; `Codex` still unbuilt.

Then use **superpowers:finishing-a-development-branch** to complete (merge to `orchestrator-design`, per the established milestone workflow).

## Self-Review (against spec §5 + the M6a decisions)

- **Spec coverage:** 2nd adapter `OpenCodeCLIAdapter` (Tasks 1,2,4) · `opencode run --format json` parse (Task 1) · caps→permission map (Task 2, the chosen fidelity) · harness≠model via `--model provider/model` + `glm` alias (Task 4) · the swappability payoff = per-role registry (Tasks 5,6) · `harness/opencode.py` per repo layout §11. ✓
- **Placeholder scan:** every code step carries real code; the one looseness (config-path assertion, OpenCode field names) is covered by explicit IMPLEMENTER NOTES with a required-behavior contract + tolerant parsing. ✓
- **Type consistency:** `HarnessRegistry.adapter_for/default_adapter/single/from_env` used consistently in scheduler (Task 6) and CLI (Task 7); `build_permission_config`/`parse_opencode_line`/`OpenCodeCLIAdapter(model=...)` signatures match across tasks; `Harness` enum values reused (`claude_code`, `opencode`, `codex`). ✓
- **Ordering risk:** Task 6's mixed-harness test needs the `opencoder` role — flagged to create it in Task 6 (Task 7 owns the demo pipeline + CLI + docs). ✓
- **Back-compat:** the registry normalizes a bare adapter via `.single`, so M1–M5's many single-adapter call sites and the direct `run_*_step(adapter=...)` test calls are untouched (executors keep their single-`adapter` signature). ✓
```
