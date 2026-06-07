import json
import os
import subprocess
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, KnowledgeSource
from orchestrator.knowledge.provider import build_knowledge_mcp
from orchestrator.safety.capabilities import ResolvedCaps


def _ws():
    ws = Workspace(config=Config())
    ws.knowledge_sources = {
        "lessons": KnowledgeSource(name="lessons",
                                   sources=[".orchestrator/knowledge/lessons.md"]),
    }
    return ws


def _rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _read(proc):
    line = proc.stdout.readline()
    assert line.strip(), "subprocess produced no output (did it crash?)"
    return json.loads(line)


def test_audit_write_is_searchable_next_run(tmp_path):
    root = tmp_path
    (root / ".orchestrator" / "knowledge").mkdir(parents=True)

    # 1) Auditor caps (read+write) -> server with the write tool.
    auditor_caps = ResolvedCaps(knowledge_read=("lessons",), knowledge_write=("lessons",))
    [wsrv] = build_knowledge_mcp(_ws(), auditor_caps, root)

    # 2) Auditor writes a durable lesson via the MCP write tool.
    env = {**os.environ, **wsrv.env}
    wp = subprocess.Popen([wsrv.command, *wsrv.args], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, env=env,
                          cwd=str(Path(__file__).parents[2]))
    try:
        _rpc(wp, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "write",
                             "arguments": {"lesson": "rebase agent worktrees off base"}}})
        assert _read(wp)["result"]["isError"] is False
    finally:
        wp.stdin.close()
        wp.wait(timeout=5)

    # 3) Next run: a reader role (read only) searches and finds the lesson.
    reader_caps = ResolvedCaps(knowledge_read=("lessons",))
    [rsrv] = build_knowledge_mcp(_ws(), reader_caps, root)
    assert "ORCH_KB_WRITE_TARGET" not in rsrv.env  # reader cannot write
    renv = {**os.environ, **rsrv.env}
    rp = subprocess.Popen([rsrv.command, *rsrv.args], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True, env=renv,
                          cwd=str(Path(__file__).parents[2]))
    try:
        _rpc(rp, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "search", "arguments": {"query": "rebase worktrees"}}})
        out = _read(rp)["result"]["content"][0]["text"]
        assert "rebase agent worktrees" in out
    finally:
        rp.stdin.close()
        rp.wait(timeout=5)
