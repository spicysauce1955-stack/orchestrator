import json
import os
import subprocess
import sys
from pathlib import Path


def _rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _read(proc):
    line = proc.stdout.readline()
    assert line.strip(), "subprocess produced no output (did it crash?)"
    return json.loads(line)


def _spawn(tmp_path, env_extra):
    (tmp_path / "kb.md").write_text("lesson: drain stderr before wiring real binary\n")
    env = {
        "ORCH_KB_SOURCES": json.dumps(["*.md"]),
        "ORCH_KB_ROOT": str(tmp_path),
        **env_extra,
    }
    full_env = {**os.environ, **env}
    return subprocess.Popen(
        [sys.executable, "-m", "orchestrator.knowledge.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=full_env,
        cwd=str(Path(__file__).parents[2]),
    )


def test_stdio_initialize_and_search(tmp_path):
    proc = _spawn(tmp_path, {})
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert _read(proc)["result"]["serverInfo"]["name"] == "knowledge"
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})  # no reply
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "search", "arguments": {"query": "drain stderr"}}})
        out = _read(proc)["result"]["content"][0]["text"]
        assert "drain stderr" in out.lower()
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_stdio_write_persists_to_target(tmp_path):
    target = tmp_path / "lessons.md"
    proc = _spawn(tmp_path, {"ORCH_KB_WRITE_TARGET": str(target)})
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "write", "arguments": {"lesson": "pin protocol version"}}})
        assert _read(proc)["result"]["isError"] is False
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
    assert "pin protocol version" in target.read_text()
