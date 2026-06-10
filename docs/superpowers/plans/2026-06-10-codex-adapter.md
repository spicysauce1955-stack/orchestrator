# CodexCLIAdapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Third harness adapter — drive OpenAI Codex via `codex exec --json` behind the spec §5 `HarnessAdapter` seam, with knowledge-MCP wiring, registered in `HarnessRegistry.from_env()`.

**Architecture:** New `orchestrator/harness/codex.py` mirroring `opencode.py`: a pure JSONL parser (`parse_codex_line`), an MCP `-c`-override builder (`_mcp_overrides`), and an async streaming subprocess wrapper that synthesizes `Done` at stream end (codex has no single result event). Sandbox is always bypassed (`--dangerously-bypass-approvals-and-sandbox`) — the orchestrator's worktree is the isolation boundary (same accepted MVP stance as OpenCode; codex's own bwrap sandbox fails to init in externally-isolated environments). MCP servers are injected as `-c mcp_servers.*` config overrides which layer on the user's real `~/.codex/config.toml` — a temp `CODEX_HOME` was rejected because it breaks `auth.json`.

**Tech Stack:** Python 3.12, asyncio subprocess, pytest (`asyncio_mode = "auto"` — write bare `async def` tests, no decorator). Spec: `docs/superpowers/specs/2026-06-10-codex-adapter-design.md`.

**Run all tests with:** `.venv/bin/python -m pytest <path> -v` from the repo root (or `uv run pytest`).

---

## File map

- Create: `orchestrator/harness/codex.py` — parser + `_mcp_overrides` + `CodexCLIAdapter`
- Create: `tests/unit/test_codex_parser.py` — parser unit tests (real captured shapes)
- Create: `tests/unit/test_codex_mcp_overrides.py` — `-c` flag builder tests
- Create: `tests/fixtures/fake_codex/__init__.py` (empty), `tests/fixtures/fake_codex/fake_codex.py`, `tests/fixtures/fake_codex/scripts/default.ndjson`, `tests/fixtures/fake_codex/scripts/implement.ndjson`
- Create: `tests/integration/test_codex_adapter.py` — fake-binary E2E
- Modify: `orchestrator/harness/registry.py` (`from_env`)
- Modify: `tests/unit/test_registry.py` (unregistered-case fix + from_env codex)

Event shapes come from real transcripts (`bench/results/20260609-165107/*/C_codex/transcript.txt`):
`thread.started {thread_id}` · `item.started/completed {item: {id, type, …}}` with item types
`agent_message {text}`, `command_execution {command, status}`, `file_change {changes: [{path, kind}]}`,
`error {message}` · `turn.completed {usage: {input_tokens, output_tokens, …}}`.

---

### Task 1: `parse_codex_line` (pure parser)

**Files:**
- Create: `tests/unit/test_codex_parser.py`
- Create: `orchestrator/harness/codex.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_codex_parser.py
from orchestrator.harness.events import Cost, FileEdit, MessageChunk, SessionStarted, ToolCall
from orchestrator.harness.codex import parse_codex_line

# Shapes mirror real `codex exec --json` transcripts captured in
# bench/results/20260609-165107/*/C_codex/transcript.txt.


def test_thread_started_to_session_started():
    evs = parse_codex_line(
        {"type": "thread.started", "thread_id": "019eacb0-b090-7d12"}, {}
    )
    assert evs == [SessionStarted("019eacb0-b090-7d12")]


def test_agent_message_completed_to_message_chunk():
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": "Inspecting the repo."},
        },
        {},
    )
    assert evs == [MessageChunk("Inspecting the repo.")]


def test_command_execution_started_and_completed_to_toolcall():
    items: dict[str, str] = {}
    started = parse_codex_line(
        {
            "type": "item.started",
            "item": {
                "id": "item_2",
                "type": "command_execution",
                "command": "/bin/bash -lc 'sed -n 1,220p x.py'",
                "status": "in_progress",
            },
        },
        items,
    )
    assert started == [ToolCall("command", "in_progress")]
    completed = parse_codex_line(
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "command_execution", "status": "completed"},
        },
        items,
    )
    assert completed == [ToolCall("command", "completed")]
    assert items["item_2"] == "command_execution"


def test_file_change_completed_emits_fileedit_per_change():
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {
                "id": "item_8",
                "type": "file_change",
                "changes": [
                    {"path": "/repo/convex_hull.py", "kind": "update"},
                    {"path": "/repo/new_module.py", "kind": "add"},
                    {"path": "/repo/old.py", "kind": "delete"},
                ],
                "status": "completed",
            },
        },
        {},
    )
    assert FileEdit("/repo/convex_hull.py", "modify") in evs
    assert FileEdit("/repo/new_module.py", "create") in evs
    assert FileEdit("/repo/old.py", "delete") in evs


def test_file_change_started_emits_nothing():
    # codex repeats the changes payload on item.started; only completion counts,
    # so a change is not double-emitted.
    evs = parse_codex_line(
        {
            "type": "item.started",
            "item": {
                "id": "item_8",
                "type": "file_change",
                "changes": [{"path": "/repo/a.py", "kind": "update"}],
                "status": "in_progress",
            },
        },
        {},
    )
    assert not any(isinstance(e, FileEdit) for e in evs)


def test_turn_completed_sums_tokens_into_cost():
    evs = parse_codex_line(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 144154,
                "cached_input_tokens": 78080,
                "output_tokens": 1487,
                "reasoning_output_tokens": 36,
            },
        },
        {},
    )
    assert evs == [Cost(usd=0.0, tokens=144154 + 1487)]


def test_error_item_emits_no_events():
    # codex emits non-fatal error items (e.g. config deprecation warnings) in
    # every run; the adapter (not the parser) decides whether to surface them.
    evs = parse_codex_line(
        {
            "type": "item.completed",
            "item": {"id": "item_0", "type": "error", "message": "`[features].codex_hooks` is deprecated."},
        },
        {},
    )
    assert evs == []


def test_unknown_types_ignored():
    assert parse_codex_line({"type": "turn.started"}, {}) == []
    assert parse_codex_line({"type": "item.started", "item": {"id": "x", "type": "agent_message", "text": "partial"}}, {}) == []
    assert parse_codex_line({}, {}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_codex_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator.harness.codex'`

- [ ] **Step 3: Write the parser**

```python
# orchestrator/harness/codex.py
"""CodexCLIAdapter: drive `codex exec --json` (spec §5, 3rd adapter).

Design: docs/superpowers/specs/2026-06-10-codex-adapter-design.md.
Mirrors OpenCodeCLIAdapter (no single result event → synthesized Done; no
usable OS sandbox → the worktree is the isolation boundary). Knowledge MCP is
wired via `-c mcp_servers.*` overrides layered on the user's real config —
a temp CODEX_HOME would break auth.json.
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

# codex file_change kinds → normalized FileEdit kinds
_CHANGE_KINDS = {"add": "create", "update": "modify", "delete": "delete"}


def parse_codex_line(obj: dict, items: dict[str, str]) -> list[Event]:
    """Map one decoded `codex exec --json` object to normalized events.

    `items` is mutated (item id → item type) so started/completed pairs can be
    correlated (symmetry with the other parsers' `tool_names`). Error items
    return no events: codex emits non-fatal ones (config deprecations) in
    every run, so the adapter decides whether to surface them at exit.
    """
    kind = obj.get("type")

    if kind == "thread.started":
        return [SessionStarted(obj.get("thread_id", ""))]

    if kind == "turn.completed":
        usage = obj.get("usage") or {}
        tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
        return [Cost(usd=0.0, tokens=tokens)]

    if kind in ("item.started", "item.completed"):
        item = obj.get("item") or {}
        itype = item.get("type", "")
        item_id = item.get("id", "")
        if item_id and itype:
            items[item_id] = itype
        completed = kind == "item.completed"
        if itype == "agent_message" and completed:
            return [MessageChunk(item.get("text", ""))]
        if itype == "command_execution":
            return [ToolCall("command", "completed" if completed else "in_progress")]
        if itype == "file_change" and completed:
            # Completed only: codex repeats the payload on item.started.
            return [
                FileEdit(ch.get("path", ""), _CHANGE_KINDS.get(ch.get("kind", ""), "modify"))
                for ch in item.get("changes", []) or []
                if ch.get("path")
            ]

    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_codex_parser.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_codex_parser.py orchestrator/harness/codex.py
git commit -m "feat(harness): codex JSONL parser (parse_codex_line)"
```

---

### Task 2: `_mcp_overrides` (McpServer → `-c` flags)

**Files:**
- Create: `tests/unit/test_codex_mcp_overrides.py`
- Modify: `orchestrator/harness/codex.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_codex_mcp_overrides.py
import json

from orchestrator.harness.adapter import McpServer
from orchestrator.harness.codex import _mcp_overrides


def test_empty_list_no_flags():
    assert _mcp_overrides([]) == []


def test_knowledge_server_overrides():
    # The real shape built by orchestrator/knowledge/provider.py: env carries a
    # JSON blob which must round-trip as a quoted TOML string.
    srv = McpServer(
        name="knowledge",
        command="/usr/bin/python3",
        args=["-m", "orchestrator.knowledge.mcp_server"],
        env={"ORCH_KB_SOURCES": json.dumps(["a.md", "b.md"]), "ORCH_KB_ROOT": "/tmp/kb"},
    )
    flags = _mcp_overrides([srv])
    # pairwise: ["-c", "key=value", "-c", "key=value", ...]
    assert flags[::2] == ["-c"] * (len(flags) // 2)
    kv = dict(f.split("=", 1) for f in flags[1::2])
    assert kv["mcp_servers.knowledge.command"] == '"/usr/bin/python3"'
    assert kv["mcp_servers.knowledge.args"] == '["-m", "orchestrator.knowledge.mcp_server"]'
    # JSON blob survives as an escaped TOML string
    assert kv["mcp_servers.knowledge.env.ORCH_KB_SOURCES"] == json.dumps(json.dumps(["a.md", "b.md"]))
    assert kv["mcp_servers.knowledge.env.ORCH_KB_ROOT"] == '"/tmp/kb"'


def test_server_without_args_or_env_emits_command_only():
    flags = _mcp_overrides([McpServer(name="x", command="xbin")])
    assert flags == ["-c", 'mcp_servers.x.command="xbin"']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_codex_mcp_overrides.py -v`
Expected: FAIL — `ImportError: cannot import name '_mcp_overrides'`

- [ ] **Step 3: Implement**

Append to `orchestrator/harness/codex.py` (also add `import json` and
`from orchestrator.harness.adapter import McpServer` at the top):

```python
def _mcp_overrides(servers: list[McpServer]) -> list[str]:
    """McpServer list → `codex -c` config overrides (verified vs `codex mcp list`).

    `-c` values are parsed as TOML; json.dumps of a str / list[str] is valid
    TOML for those types. Per-key `env.<KEY>` dotted paths avoid inline-table
    syntax. Layering on the real config preserves auth.json and the user's
    existing servers; there is no temp file to clean up.
    """
    flags: list[str] = []
    for s in servers:
        base = f"mcp_servers.{s.name}"
        flags += ["-c", f"{base}.command={json.dumps(s.command)}"]
        if s.args:
            flags += ["-c", f"{base}.args={json.dumps(list(s.args))}"]
        for key, value in s.env.items():
            flags += ["-c", f"{base}.env.{key}={json.dumps(value)}"]
    return flags
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_codex_mcp_overrides.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_codex_mcp_overrides.py orchestrator/harness/codex.py
git commit -m "feat(harness): codex MCP wiring via -c config overrides"
```

---

### Task 3: `CodexCLIAdapter` + fake binary + E2E

**Files:**
- Create: `tests/fixtures/fake_codex/__init__.py` (empty file)
- Create: `tests/fixtures/fake_codex/fake_codex.py`
- Create: `tests/fixtures/fake_codex/scripts/default.ndjson`
- Create: `tests/fixtures/fake_codex/scripts/implement.ndjson`
- Create: `tests/integration/test_codex_adapter.py`
- Modify: `orchestrator/harness/codex.py` (append adapter class)

- [ ] **Step 1: Create the fake codex binary**

```python
# tests/fixtures/fake_codex/fake_codex.py
#!/usr/bin/env python3
"""Fake `codex` binary for tests. Zero API cost.

- Records argv (one per line) to $ORCH_CODEX_ARGV (if set).
- Streams the NDJSON at $ORCH_CODEX_SCRIPT (default scripts/default.ndjson) to stdout.
- If $ORCH_CODEX_TOUCH is set, creates that file under the `-C` dir (or cwd).
- If $ORCH_CODEX_STDERR is set, writes it to stderr.
- Exits 0 unless $ORCH_CODEX_EXIT is set non-zero.
"""

import os
import sys
from pathlib import Path

DEFAULT_SCRIPT = Path(__file__).parent / "scripts" / "default.ndjson"


def main() -> int:
    args = sys.argv[1:]
    argv_file = os.environ.get("ORCH_CODEX_ARGV")
    if argv_file:
        Path(argv_file).write_text("\n".join(args))

    workdir = Path(".")
    if "-C" in args:
        i = args.index("-C")
        if i + 1 < len(args):
            workdir = Path(args[i + 1])

    touch = os.environ.get("ORCH_CODEX_TOUCH")
    if touch:
        (workdir / touch).write_text("created by fake codex\n")

    err = os.environ.get("ORCH_CODEX_STDERR")
    if err:
        sys.stderr.write(err)
        sys.stderr.flush()

    script = Path(os.environ.get("ORCH_CODEX_SCRIPT", str(DEFAULT_SCRIPT)))
    sys.stdout.write(script.read_text())
    sys.stdout.flush()
    return int(os.environ.get("ORCH_CODEX_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create the NDJSON scripts** (shapes match the real transcripts)

`tests/fixtures/fake_codex/scripts/default.ndjson`:

```
{"type":"thread.started","thread_id":"codex-default-1"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"`[features].codex_hooks` is deprecated."}}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"Looking around. "}}
{"type":"item.started","item":{"id":"item_2","type":"command_execution","command":"/bin/bash -lc ls","status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_2","type":"command_execution","command":"/bin/bash -lc ls","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"Done."}}
{"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":0,"output_tokens":30}}
```

`tests/fixtures/fake_codex/scripts/implement.ndjson`:

```
{"type":"thread.started","thread_id":"codex-impl-1"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"Implementing. "}}
{"type":"item.started","item":{"id":"item_2","type":"file_change","changes":[{"path":"feature.py","kind":"add"}],"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_2","type":"file_change","changes":[{"path":"feature.py","kind":"add"}],"status":"completed"}}
{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"Implemented the feature."}}
{"type":"turn.completed","usage":{"input_tokens":900,"cached_input_tokens":100,"output_tokens":100}}
```

- [ ] **Step 3: Write the failing E2E tests**

```python
# tests/integration/test_codex_adapter.py
import sys
from pathlib import Path

from orchestrator.harness.adapter import McpServer
from orchestrator.harness.codex import CodexCLIAdapter
from orchestrator.harness.events import Cost, Done, FileEdit, MessageChunk, SessionStarted, ToolCall
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_codex" / "fake_codex.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, text, mcp_servers=()):
    session = await adapter.start_session(
        cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=list(mcp_servers)
    )
    events = []
    stream = await adapter.prompt(session, text)
    async for ev in stream:
        events.append(ev)
    return session, events


async def test_streams_normalized_events_and_synthesizes_done(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_CODEX_SCRIPT", str(SCRIPTS / "implement.ndjson"))
    adapter = CodexCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "implement it")
    assert isinstance(events[0], SessionStarted)
    assert events[0].session_id == "codex-impl-1"
    assert any(isinstance(e, FileEdit) and e.path == "feature.py" and e.kind == "create" for e in events)
    assert any(isinstance(e, Cost) and e.tokens == 1000 for e in events)
    done = events[-1]
    assert isinstance(done, Done) and done.is_error is False
    assert "Implemented the feature." in done.result


async def test_passes_exec_json_bypass_model_and_cwd(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_CODEX_ARGV", str(tmp_path / "argv.txt"))
    adapter = CodexCLIAdapter(binary=[sys.executable, str(FAKE)], model="gpt-5.3-codex")
    await _drive(adapter, tmp_path, "hello codex")
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert argv[0] == "exec"
    assert "--json" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert "-C" in argv and str(tmp_path) in argv
    assert "-m" in argv and "gpt-5.3-codex" in argv
    assert argv[-1] == "hello codex"


async def test_session_model_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_CODEX_ARGV", str(tmp_path / "argv.txt"))
    adapter = CodexCLIAdapter(binary=[sys.executable, str(FAKE)])  # no construction model
    session = await adapter.start_session(
        cwd=tmp_path, caps=ResolvedCaps.read_only(), mcp_servers=[], model="o4-mini"
    )
    stream = await adapter.prompt(session, "x")
    async for _ in stream:
        pass
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "-m" in argv and "o4-mini" in argv


async def test_mcp_servers_become_c_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_CODEX_ARGV", str(tmp_path / "argv.txt"))
    srv = McpServer(name="knowledge", command="py", args=["-m", "kb"], env={"K": "v"})
    adapter = CodexCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, "x", mcp_servers=[srv])
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert 'mcp_servers.knowledge.command="py"' in argv
    assert 'mcp_servers.knowledge.args=["-m", "kb"]' in argv
    assert 'mcp_servers.knowledge.env.K="v"' in argv
    # prompt is still the final argument, after all overrides
    assert argv[-1] == "x"


async def test_nonzero_exit_yields_error_done_with_stderr_tail(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_CODEX_EXIT", "2")
    monkeypatch.setenv("ORCH_CODEX_STDERR", "bwrap: loopback failed")
    adapter = CodexCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "x")
    done = events[-1]
    assert isinstance(done, Done) and done.is_error is True
    assert "bwrap: loopback failed" in done.result


async def test_nonfatal_error_item_does_not_fail_step(monkeypatch, tmp_path):
    # default.ndjson contains the deprecation error item codex emits every run
    adapter = CodexCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "x")
    done = events[-1]
    assert isinstance(done, Done) and done.is_error is False
    assert any(isinstance(e, MessageChunk) for e in events)
    assert any(isinstance(e, ToolCall) and e.status == "completed" for e in events)


async def test_honors_orch_codex_bin(monkeypatch):
    monkeypatch.setenv("ORCH_CODEX_BIN", "fakecodex --flag")
    adapter = CodexCLIAdapter()
    assert adapter._binary == ["fakecodex", "--flag"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_codex_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'CodexCLIAdapter'`

- [ ] **Step 5: Implement the adapter**

Append to `orchestrator/harness/codex.py`. Extend the imports at the top of the
file to (final form):

```python
import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from orchestrator.harness.adapter import McpServer, SessionId
from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)

if TYPE_CHECKING:
    from orchestrator.safety.capabilities import ResolvedCaps
```

Then the session dataclass and adapter:

```python
@dataclass
class _CodexSession:
    cwd: Path
    caps: ResolvedCaps
    mcp_servers: list[McpServer]
    model: str | None = None
    harness_session_id: str | None = None


class CodexCLIAdapter:
    """Drives Codex via `codex exec --json`.

    `binary` default `["codex"]`; honors $ORCH_CODEX_BIN. Sandbox is always
    bypassed: codex's bwrap sandbox fails in externally-isolated environments,
    and the orchestrator's worktree is the isolation boundary (spec §4/§9 —
    same MVP stance as OpenCode). `caps` is stored for forward compatibility;
    codex exec exposes no per-tool flags to translate it to.
    """

    def __init__(self, binary: list[str] | None = None, *, model: str | None = None) -> None:
        if binary is None:
            env_bin = os.environ.get("ORCH_CODEX_BIN")
            binary = env_bin.split() if env_bin else ["codex"]
        self._binary = binary
        self._model = model
        self._sessions: dict[SessionId, _CodexSession] = {}

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: ResolvedCaps,
        mcp_servers: list[McpServer],
        model: str | None = None,
    ) -> SessionId:
        handle = uuid.uuid4().hex
        # A per-session model (from the role) overrides the construction default.
        self._sessions[handle] = _CodexSession(
            cwd=Path(cwd),
            caps=caps,
            mcp_servers=list(mcp_servers),
            model=model or self._model,
        )
        return handle

    async def prompt(
        self, session: SessionId, text: str, *, output_schema: dict | None = None
    ) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        cmd = [
            *self._binary,
            "exec",
            "-C",
            str(sess.cwd),
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if sess.model:
            cmd += ["-m", sess.model]
        cmd += _mcp_overrides(sess.mcp_servers)
        cmd.append(text)
        return self._stream(session, cmd)

    async def _stream(self, session: SessionId, cmd: list[str]) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sess.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain stderr concurrently so a chatty child never blocks on a full
        # pipe and a non-zero exit can report its cause (same as both peers).
        stderr_chunks: list[bytes] = []

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            data = await proc.stderr.read()
            if data:
                stderr_chunks.append(data)

        stderr_task = asyncio.ensure_future(_drain_stderr())
        items: dict[str, str] = {}
        text_parts: list[str] = []
        error_msgs: list[str] = []
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Error items are non-events (codex emits non-fatal ones every
            # run); remember them in case the process exits non-zero.
            item = obj.get("item") or {}
            if obj.get("type") == "item.completed" and item.get("type") == "error":
                error_msgs.append(item.get("message", ""))
            for ev in parse_codex_line(obj, items):
                if isinstance(ev, SessionStarted):
                    sess.harness_session_id = ev.session_id
                if isinstance(ev, MessageChunk):
                    text_parts.append(ev.text)
                yield ev
        returncode = await proc.wait()
        await stderr_task
        # Codex has no single "result" event; synthesize Done at stream end.
        if returncode != 0:
            tail = b"".join(stderr_chunks).decode(errors="replace").strip()
            detail = "; ".join(filter(None, [*error_msgs[-2:], tail[-500:] if tail else ""]))
            result = "".join(text_parts)
            yield Done(
                result=f"{result}\n[codex exited {returncode}: {detail}]".strip(),
                is_error=True,
            )
        else:
            yield Done(result="".join(text_parts), is_error=False)

    async def resume(self, session: SessionId) -> SessionId:
        # Codex-native resume/fork deferred (spec: out of scope); the handle
        # remains valid, matching the other adapters' MVP stance.
        return session

    async def cancel(self, session: SessionId) -> None:
        self._sessions.pop(session, None)
```

- [ ] **Step 6: Run the E2E tests**

Run: `.venv/bin/python -m pytest tests/integration/test_codex_adapter.py -v`
Expected: 7 PASS

- [ ] **Step 7: Verify protocol conformance + full suite still green**

Run: `.venv/bin/python -c "from orchestrator.harness.adapter import HarnessAdapter; from orchestrator.harness.codex import CodexCLIAdapter; assert isinstance(CodexCLIAdapter(), HarnessAdapter); print('protocol ok')"`
Expected: `protocol ok`

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/fake_codex/ tests/integration/test_codex_adapter.py orchestrator/harness/codex.py
git commit -m "feat(harness): CodexCLIAdapter — codex exec --json streaming + fake-codex E2E"
```

---

### Task 4: Registry wiring

**Files:**
- Modify: `orchestrator/harness/registry.py` (`from_env`, ~line 31)
- Modify: `tests/unit/test_registry.py`

- [ ] **Step 1: Update the registry tests (failing first)**

In `tests/unit/test_registry.py`:

(a) Add the import:

```python
from orchestrator.harness.codex import CodexCLIAdapter
```

(b) Replace `test_unregistered_harness_raises` — it currently uses `Harness.codex`
as its unregistered example, which stops being unregistered. Use an explicitly
empty mapping so the invariant survives:

```python
def test_unregistered_harness_raises():
    reg = HarnessRegistry({Harness.claude_code: ClaudeCodeCLIAdapter(binary=["c"])})
    with pytest.raises(KeyError):
        reg.adapter_for(Harness.opencode)
    with pytest.raises(KeyError):
        HarnessRegistry({}).adapter_for(Harness.codex)
```

(c) Extend `test_from_env_builds_claude_and_opencode` (rename to
`test_from_env_builds_all_adapters`):

```python
def test_from_env_builds_all_adapters(monkeypatch):
    monkeypatch.setenv("ORCH_CLAUDE_BIN", "fakeclaude")
    monkeypatch.setenv("ORCH_OPENCODE_BIN", "fakeoc")
    monkeypatch.setenv("ORCH_CODEX_BIN", "fakecodex")
    reg = HarnessRegistry.from_env()
    assert isinstance(reg.adapter_for(Harness.claude_code), ClaudeCodeCLIAdapter)
    assert isinstance(reg.adapter_for(Harness.opencode), OpenCodeCLIAdapter)
    codex = reg.adapter_for(Harness.codex)
    assert isinstance(codex, CodexCLIAdapter)
    assert codex._binary == ["fakecodex"]
```

- [ ] **Step 2: Run to verify the new assertions fail**

Run: `.venv/bin/python -m pytest tests/unit/test_registry.py -v`
Expected: `test_from_env_builds_all_adapters` FAILS with `KeyError: "no adapter registered for harness 'codex'"`; the unregistered test passes.

- [ ] **Step 3: Register codex in `from_env`**

In `orchestrator/harness/registry.py`, update `from_env`:

```python
    @classmethod
    def from_env(cls) -> HarnessRegistry:
        """Default production registry: real adapters honoring $ORCH_*_BIN."""
        from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
        from orchestrator.harness.codex import CodexCLIAdapter
        from orchestrator.harness.opencode import OpenCodeCLIAdapter

        return cls(
            {
                Harness.claude_code: ClaudeCodeCLIAdapter(),
                Harness.codex: CodexCLIAdapter(),
                Harness.opencode: OpenCodeCLIAdapter(),
            }
        )
```

- [ ] **Step 4: Run the registry tests, then the full suite**

Run: `.venv/bin/python -m pytest tests/unit/test_registry.py -v`
Expected: all PASS

Run: `.venv/bin/python -m pytest tests/ -q && .venv/bin/python -m ruff check orchestrator/ tests/`
Expected: all pass, no lint errors

- [ ] **Step 5: Commit**

```bash
git add orchestrator/harness/registry.py tests/unit/test_registry.py
git commit -m "feat(harness): register CodexCLIAdapter in from_env (Harness.codex routable)"
```

---

## Done criteria

- `Harness.codex` resolves to a working adapter from `HarnessRegistry.from_env()`.
- A pipeline role with `harness: codex` streams normalized events end-to-end against the fake binary.
- Knowledge MCP servers reach codex as `-c mcp_servers.*` overrides (auth-preserving).
- Full test suite + ruff green.

**Not in this plan** (spec "out of scope"): bench `agent_codex` keeps its direct
subprocess call; codex-native resume/fork; USD cost for codex runs.
