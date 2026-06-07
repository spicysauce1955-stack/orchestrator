import json
import sys
from pathlib import Path

from orchestrator.harness.adapter import McpServer
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, servers):
    session = await adapter.start_session(
        cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=servers
    )
    stream = await adapter.prompt(session, "go")
    async for _ in stream:
        pass


async def test_mcp_servers_in_opencode_config(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_CONFIG_SEEN", str(tmp_path / "cfgpath.txt"))
    server = McpServer(name="knowledge", command=sys.executable,
                       args=["-m", "orchestrator.knowledge.mcp_server"],
                       env={"ORCH_KB_SOURCES": "[]", "ORCH_KB_ROOT": str(tmp_path)})
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [server])

    cfg_path = (tmp_path / "cfgpath.txt").read_text().strip()
    cfg = json.loads(Path(cfg_path).read_text())
    mcp = cfg["mcp"]["knowledge"]
    assert mcp["type"] == "local"
    assert mcp["command"] == [sys.executable, "-m", "orchestrator.knowledge.mcp_server"]
    assert mcp["enabled"] is True


async def test_no_servers_no_mcp_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_CONFIG_SEEN", str(tmp_path / "cfgpath.txt"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, [])
    cfg = json.loads(Path((tmp_path / "cfgpath.txt").read_text().strip()).read_text())
    assert "mcp" not in cfg or cfg["mcp"] == {}
