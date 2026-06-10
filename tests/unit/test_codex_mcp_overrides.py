"""Tests for _mcp_overrides: McpServer list → `codex -c` config overrides."""

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
        env={
            "ORCH_KB_SOURCES": json.dumps(["a.md", "b.md"]),
            "ORCH_KB_ROOT": "/tmp/kb",
            "ORCH_KB_WRITE_TARGET": "/tmp/kb/lessons.md",
        },
    )
    flags = _mcp_overrides([srv])
    # pairwise: ["-c", "key=value", "-c", "key=value", ...]
    assert flags[::2] == ["-c"] * (len(flags) // 2)
    kv = dict(f.split("=", 1) for f in flags[1::2])
    assert kv["mcp_servers.knowledge.command"] == '"/usr/bin/python3"'
    assert kv["mcp_servers.knowledge.args"] == '["-m", "orchestrator.knowledge.mcp_server"]'
    # JSON blob survives as an escaped TOML string
    kb_sources_key = "mcp_servers.knowledge.env.ORCH_KB_SOURCES"
    kb_sources_val = json.dumps(json.dumps(["a.md", "b.md"]))
    assert kv[kb_sources_key] == kb_sources_val
    assert kv["mcp_servers.knowledge.env.ORCH_KB_ROOT"] == '"/tmp/kb"'
    assert kv["mcp_servers.knowledge.env.ORCH_KB_WRITE_TARGET"] == '"/tmp/kb/lessons.md"'
    # 1 command + 1 args + len(env) env keys, each as a ("-c", "key=value") pair
    assert len(flags) == 2 * (2 + len(srv.env))


def test_server_without_args_or_env_emits_command_only():
    flags = _mcp_overrides([McpServer(name="x", command="xbin")])
    assert flags == ["-c", 'mcp_servers.x.command="xbin"']
