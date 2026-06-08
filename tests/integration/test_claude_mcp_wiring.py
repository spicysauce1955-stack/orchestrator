import json
import sys
from pathlib import Path

from orchestrator.harness.adapter import McpServer
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, servers):
    session = await adapter.start_session(
        cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=servers
    )
    stream = await adapter.prompt(session, "go")
    async for _ in stream:
        pass
    return session


async def test_mcp_config_passed_and_tools_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    server = McpServer(name="knowledge", command=sys.executable,
                       args=["-m", "orchestrator.knowledge.mcp_server"],
                       env={"ORCH_KB_SOURCES": "[]", "ORCH_KB_ROOT": str(tmp_path)})
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [server])

    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "--mcp-config" in argv
    cfg_path = argv[argv.index("--mcp-config") + 1]
    cfg = json.loads(Path(cfg_path).read_text())
    assert cfg["mcpServers"]["knowledge"]["command"] == sys.executable
    # the MCP tools are allow-listed so the harness may call them
    allowed = argv[argv.index("--allowedTools") + 1]
    assert "mcp__knowledge" in allowed
    # config lives OUTSIDE the worktree (no diff pollution)
    assert not cfg_path.startswith(str(tmp_path))  # config lives outside the worktree


async def test_session_model_emits_model_flag(monkeypatch, tmp_path):
    # A per-session model (from the role) is translated to a `--model` flag.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    session = await adapter.start_session(
        cwd=tmp_path, caps=ResolvedCaps.read_only(), mcp_servers=[], model="claude-opus-4-8"
    )
    stream = await adapter.prompt(session, "go")
    async for _ in stream:
        pass
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "--model" in argv and "claude-opus-4-8" in argv


async def test_no_model_no_model_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [])
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "--model" not in argv


async def test_no_servers_no_mcp_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [])
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "--mcp-config" not in argv


async def test_cancel_removes_mcp_config(monkeypatch, tmp_path):
    server = McpServer(name="knowledge", command=sys.executable,
                       args=["-m", "orchestrator.knowledge.mcp_server"],
                       env={"ORCH_KB_SOURCES": "[]", "ORCH_KB_ROOT": str(tmp_path)})
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    session = await adapter.start_session(
        cwd=tmp_path, caps=ResolvedCaps.read_only(), mcp_servers=[server]
    )
    cfg_path = adapter._sessions[session].mcp_config_path
    assert cfg_path and Path(cfg_path).exists()
    await adapter.cancel(session)
    assert not Path(cfg_path).exists()
