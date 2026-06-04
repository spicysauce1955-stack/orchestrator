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
