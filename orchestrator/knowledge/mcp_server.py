"""Knowledge MCP server (spec §8): stdio JSON-RPC 2.0, newline-delimited.

Exposes `search` (lexical, always) and `write` (append a durable lesson, ONLY
when a write target is configured — deny-wins gating is enforced by the provider
that constructs this server's config). Hand-rolled (no MCP SDK dep); the fake
harnesses define the contract, real-harness reconciliation is a follow-up.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.knowledge.lexical import search
from orchestrator.observability.store import connect

PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True)
class SpanSink:
    """Row-writes spans into the run's span store (we run in a harness-spawned
    subprocess, so we can't share the orchestrator's OTel provider). The trace
    context arrives via env from the provider that configured this server."""

    db: Path
    trace_id: str
    parent_id: str | None
    step: str

    def emit(self, name: str, attrs: dict, start_ns: int, end_ns: int) -> None:
        row = (
            self.trace_id,
            os.urandom(8).hex(),
            self.parent_id,
            name,
            start_ns,
            end_ns,
            json.dumps({"step.id": self.step, **attrs}),
        )
        with contextlib.closing(connect(self.db)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO spans "
                "(trace_id, span_id, parent_id, name, start_ns, end_ns, attrs) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            conn.commit()


@dataclass(frozen=True)
class ServerState:
    sources: list[str]
    root: Path
    write_target: Path | None = None  # None -> write tool not offered
    sink: SpanSink | None = None  # None -> span emission off (no span env)


def _tools(state: ServerState) -> list[dict]:
    tools = [
        {
            "name": "search",
            "description": "Lexical search over the project's knowledge sources.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    if state.write_target is not None:
        tools.append({
            "name": "write",
            "description": "Append a durable lesson to the knowledge base.",
            "inputSchema": {
                "type": "object",
                "properties": {"lesson": {"type": "string"}},
                "required": ["lesson"],
            },
        })
    return tools


def _ok(req_id: int | None, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: int | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _do_search(state: ServerState, args: dict) -> dict:
    hits = search(str(args.get("query", "")), state.sources, state.root, limit=10)
    if not hits:
        return _text("No matching knowledge found.")
    lines = [f"{h.path}:{h.line}: {h.snippet}" for h in hits]
    return _text("\n".join(lines))


def _do_write(state: ServerState, args: dict) -> dict:
    # Defense-in-depth: `write` is hidden from tools/list when ungranted, but
    # re-check here in case a forged tools/call reaches this handler.
    if state.write_target is None:
        return _text("write not permitted for this role", is_error=True)
    lesson = str(args.get("lesson", "")).strip()
    if not lesson:
        return _text("empty lesson", is_error=True)
    state.write_target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    with state.write_target.open("a") as fh:
        fh.write(f"- ({stamp}) {lesson}\n")
    return _text(f"recorded lesson to {state.write_target.name}")


def handle_request(req: dict, state: ServerState) -> dict | None:
    """Dispatch one JSON-RPC request. Returns None for notifications."""
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "knowledge", "version": "0.1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": _tools(state)})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        start_ns = time.time_ns()
        if name == "search":
            result = _do_search(state, args)
        elif name == "write":
            result = _do_write(state, args)
        else:
            result = _text(f"unknown tool '{name}'", is_error=True)
        if state.sink is not None:
            end_ns = time.time_ns()
            is_error = bool(result.get("isError", False))
            state.sink.emit(
                "mcp.call",
                {"mcp.tool": str(name), "mcp.is_error": is_error},
                start_ns,
                end_ns,
            )
            if name == "write" and not is_error:
                state.sink.emit(
                    "knowledge.write",
                    {
                        "kb.target": str(state.write_target),
                        "kb.lesson": str(args.get("lesson", "")).strip(),
                    },
                    start_ns,
                    end_ns,
                )
        return _ok(req_id, result)
    return _err(req_id, -32601, f"method not found: {method}")


def state_from_env() -> ServerState:
    raw_sources = os.environ.get("ORCH_KB_SOURCES", "[]")
    try:
        sources = json.loads(raw_sources)
    except json.JSONDecodeError as e:
        raise ValueError(f"ORCH_KB_SOURCES is not valid JSON: {e}") from e
    root = Path(os.environ.get("ORCH_KB_ROOT", "."))
    wt = os.environ.get("ORCH_KB_WRITE_TARGET")
    sink: SpanSink | None = None
    span_db = os.environ.get("ORCH_SPAN_DB")
    trace_id = os.environ.get("ORCH_SPAN_TRACE")
    if span_db and trace_id:
        sink = SpanSink(
            db=Path(span_db),
            trace_id=trace_id,
            parent_id=os.environ.get("ORCH_SPAN_PARENT"),
            step=os.environ.get("ORCH_KB_STEP", ""),
        )
    return ServerState(
        sources=sources, root=root, write_target=Path(wt) if wt else None, sink=sink
    )


def main() -> int:
    state = state_from_env()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req, state)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
