"""Knowledge MCP server emits mcp.call / knowledge.write spans (M6d follow-up).

The server runs in a harness-spawned subprocess, so it cannot share the
orchestrator's OTel provider: it writes rows straight into the span store at
$ORCH_SPAN_DB under the run's trace context (passed via env by the provider).
"""

import json
import sqlite3
from pathlib import Path

from orchestrator.knowledge.mcp_server import ServerState, SpanSink, handle_request, state_from_env

TRACE = "ab" * 16
PARENT = "cd" * 8


def _call(state: ServerState, name: str, args: dict) -> dict:
    return handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
        state,
    )


def _rows(db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute("SELECT * FROM spans ORDER BY start_ns"))
    conn.close()
    return rows


def _sink(db: Path) -> SpanSink:
    return SpanSink(db=db, trace_id=TRACE, parent_id=PARENT, step="audit")


def test_write_emits_knowledge_write_and_mcp_call_spans(tmp_path):
    db = tmp_path / "spans.sqlite"
    target = tmp_path / "lessons.md"
    state = ServerState(sources=[], root=tmp_path, write_target=target, sink=_sink(db))

    resp = _call(state, "write", {"lesson": "prefer uv over pip"})

    assert resp["result"]["isError"] is False
    by_name = {r["name"]: r for r in _rows(db)}
    assert set(by_name) == {"mcp.call", "knowledge.write"}
    kw = by_name["knowledge.write"]
    assert kw["trace_id"] == TRACE
    assert kw["parent_id"] == PARENT
    attrs = json.loads(kw["attrs"])
    assert attrs["kb.lesson"] == "prefer uv over pip"
    assert attrs["kb.target"] == str(target)
    assert attrs["step.id"] == "audit"
    assert 0 < kw["start_ns"] <= kw["end_ns"]
    call_attrs = json.loads(by_name["mcp.call"]["attrs"])
    assert call_attrs["mcp.tool"] == "write"
    assert call_attrs["mcp.is_error"] is False


def test_search_emits_only_mcp_call_span(tmp_path):
    db = tmp_path / "spans.sqlite"
    state = ServerState(sources=[], root=tmp_path, sink=_sink(db))

    _call(state, "search", {"query": "anything"})

    rows = _rows(db)
    assert [r["name"] for r in rows] == ["mcp.call"]
    attrs = json.loads(rows[0]["attrs"])
    assert attrs["mcp.tool"] == "search"
    assert attrs["step.id"] == "audit"


def test_denied_write_emits_error_mcp_call_and_no_knowledge_write(tmp_path):
    db = tmp_path / "spans.sqlite"
    state = ServerState(sources=[], root=tmp_path, write_target=None, sink=_sink(db))

    resp = _call(state, "write", {"lesson": "smuggled"})

    assert resp["result"]["isError"] is True
    rows = _rows(db)
    assert [r["name"] for r in rows] == ["mcp.call"]
    assert json.loads(rows[0]["attrs"])["mcp.is_error"] is True


def test_no_sink_writes_no_spans(tmp_path):
    db = tmp_path / "spans.sqlite"
    target = tmp_path / "lessons.md"
    state = ServerState(sources=[], root=tmp_path, write_target=target)  # sink=None

    resp = _call(state, "write", {"lesson": "quiet"})

    assert resp["result"]["isError"] is False
    assert not db.exists()


def test_state_from_env_builds_sink(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_KB_SOURCES", "[]")
    monkeypatch.setenv("ORCH_KB_ROOT", str(tmp_path))
    monkeypatch.setenv("ORCH_SPAN_DB", str(tmp_path / "spans.sqlite"))
    monkeypatch.setenv("ORCH_SPAN_TRACE", TRACE)
    monkeypatch.setenv("ORCH_SPAN_PARENT", PARENT)
    monkeypatch.setenv("ORCH_KB_STEP", "audit")

    state = state_from_env()

    assert state.sink is not None
    assert state.sink.db == tmp_path / "spans.sqlite"
    assert state.sink.trace_id == TRACE
    assert state.sink.parent_id == PARENT
    assert state.sink.step == "audit"


def test_state_from_env_without_span_env_has_no_sink(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_KB_SOURCES", "[]")
    monkeypatch.setenv("ORCH_KB_ROOT", str(tmp_path))
    monkeypatch.delenv("ORCH_SPAN_DB", raising=False)
    monkeypatch.delenv("ORCH_SPAN_TRACE", raising=False)

    assert state_from_env().sink is None
