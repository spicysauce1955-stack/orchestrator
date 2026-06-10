"""Abandoning an adapter event stream must not orphan the harness subprocess.

The deferred cross-cutting follow-up (codex-adapter-followups.md): if the
consumer abandons `_stream` mid-iteration (aclose / task cancellation), the
child kept running and the stderr-drain task was never awaited. Same for
`cancel()` called while a prompt is in flight. One contract, all 3 adapters.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.codex import CodexCLIAdapter
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

HANG = Path(__file__).parent.parent / "fixtures" / "hang_harness.py"

# One valid first NDJSON line per adapter so the stream yields exactly one
# event (SessionStarted) and then hangs with the generator suspended at yield.
ADAPTERS = {
    "claude": (
        ClaudeCodeCLIAdapter,
        '{"type": "system", "subtype": "init", "session_id": "s1"}',
    ),
    "opencode": (
        OpenCodeCLIAdapter,
        '{"type": "step_start", "sessionID": "oc1"}',
    ),
    "codex": (
        CodexCLIAdapter,
        '{"type": "thread.started", "thread_id": "t1"}',
    ),
}


async def _start_hanging_stream(adapter_cls, tmp_path, monkeypatch, first_line):
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("ORCH_HANG_LINE", first_line)
    monkeypatch.setenv("ORCH_HANG_PID_FILE", str(pid_file))
    adapter = adapter_cls(binary=[sys.executable, str(HANG)])
    session = await adapter.start_session(
        cwd=tmp_path, caps=ResolvedCaps.read_only(), mcp_servers=[]
    )
    stream = await adapter.prompt(session, "go")
    first = await anext(stream)
    assert type(first).__name__ == "SessionStarted"
    # The child has started; wait for it to report its PID.
    deadline = time.monotonic() + 5.0
    while not pid_file.exists() or not pid_file.read_text():
        assert time.monotonic() < deadline, "child never wrote its PID"
        await asyncio.sleep(0.02)
    return adapter, session, stream, int(pid_file.read_text())


async def _assert_child_dead(pid: int, timeout: float = 5.0) -> None:
    """The child must be killed AND reaped (a zombie still answers kill 0)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    pytest.fail(f"harness child {pid} still alive after stream cleanup")


@pytest.mark.parametrize("name", ADAPTERS)
async def test_abandoning_stream_kills_subprocess(name, tmp_path, monkeypatch):
    adapter_cls, first_line = ADAPTERS[name]
    adapter, _session, stream, pid = await _start_hanging_stream(
        adapter_cls, tmp_path, monkeypatch, first_line
    )
    await stream.aclose()  # consumer abandons mid-iteration → GeneratorExit at yield
    await _assert_child_dead(pid)


@pytest.mark.parametrize("name", ADAPTERS)
async def test_cancel_kills_running_subprocess(name, tmp_path, monkeypatch):
    adapter_cls, first_line = ADAPTERS[name]
    adapter, session, stream, pid = await _start_hanging_stream(
        adapter_cls, tmp_path, monkeypatch, first_line
    )
    await adapter.cancel(session)
    await _assert_child_dead(pid)
    await stream.aclose()  # cleanup; must be safe after cancel already killed
