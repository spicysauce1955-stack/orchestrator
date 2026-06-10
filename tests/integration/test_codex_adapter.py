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
    assert any(
        isinstance(e, FileEdit) and e.path == "feature.py" and e.kind == "create"
        for e in events
    )
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
