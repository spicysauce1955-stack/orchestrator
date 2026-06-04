"""ClaudeCodeCLIAdapter: drive `claude -p --output-format stream-json` (spec §5).

Split into three concerns:
- `parse_line`        : pure NDJSON-object → normalized events (this task)
- `ClaudeCodeCLIAdapter.translate` : ResolvedCaps → CLI flags (Task 10)
- `ClaudeCodeCLIAdapter` async streaming + diff capture (Task 6)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from orchestrator.harness.adapter import McpServer, SessionId
from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)

# tool_use names that mutate files → also emit a FileEdit
_EDIT_TOOLS = {
    "Write": "create",
    "Edit": "modify",
    "MultiEdit": "modify",
    "NotebookEdit": "modify",
}


def parse_line(obj: dict, tool_names: dict[str, str]) -> list[Event]:
    """Map one decoded stream-json object to normalized events.

    `tool_names` is mutated: tool_use id → tool name, so a later tool_result
    can be reported as a completed call for the right tool.
    """
    kind = obj.get("type")

    if kind == "system" and obj.get("subtype") == "init":
        return [SessionStarted(obj.get("session_id", ""))]

    if kind == "assistant":
        events: list[Event] = []
        for block in obj.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text":
                events.append(MessageChunk(block.get("text", "")))
            elif btype == "tool_use":
                name = block.get("name", "")
                tool_id = block.get("id", "")
                if tool_id:
                    tool_names[tool_id] = name
                events.append(ToolCall(name, "in_progress"))
                if name in _EDIT_TOOLS:
                    path = block.get("input", {}).get("file_path", "")
                    if path:
                        events.append(FileEdit(path, _EDIT_TOOLS[name]))
        return events

    if kind == "user":
        events = []
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "")
                name = tool_names.get(tool_id, "")
                if name:
                    events.append(ToolCall(name, "completed"))
        return events

    if kind == "result":
        usage = obj.get("usage", {}) or {}
        tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return [
            Cost(usd=float(obj.get("total_cost_usd", 0.0)), tokens=tokens),
            Done(result=obj.get("result", ""), is_error=bool(obj.get("is_error", False))),
        ]

    return []


@dataclass
class _Session:
    cwd: Path
    caps: object  # ResolvedCaps — typed as object to avoid circular import at runtime
    mcp_servers: list[McpServer]
    harness_session_id: str | None = None


class ClaudeCodeCLIAdapter:
    """Drives Claude Code via `claude -p --output-format stream-json`.

    `binary` is the command prefix (default `["claude"]`); tests inject the
    fake harness. Honors $ORCH_CLAUDE_BIN when no binary is passed.
    """

    def __init__(self, binary: list[str] | None = None) -> None:
        if binary is None:
            import os

            env_bin = os.environ.get("ORCH_CLAUDE_BIN")
            binary = env_bin.split() if env_bin else ["claude"]
        self._binary = binary
        self._sessions: dict[SessionId, _Session] = {}

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: object,
        mcp_servers: list[McpServer],
    ) -> SessionId:
        handle = uuid.uuid4().hex
        self._sessions[handle] = _Session(cwd=Path(cwd), caps=caps, mcp_servers=list(mcp_servers))
        return handle

    async def prompt(
        self,
        session: SessionId,
        text: str,
        *,
        output_schema: dict | None = None,
    ) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        flags = self.translate(sess.caps, cwd=sess.cwd)
        cmd = [
            *self._binary,
            "-p",
            text,
            "--output-format",
            "stream-json",
            *flags,
        ]
        return self._stream(session, cmd)

    async def _stream(self, session: SessionId, cmd: list[str]) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sess.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        tool_names: dict[str, str] = {}
        saw_done = False
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for ev in parse_line(obj, tool_names):
                if isinstance(ev, SessionStarted):
                    sess.harness_session_id = ev.session_id
                if isinstance(ev, Done):
                    saw_done = True
                yield ev
        returncode = await proc.wait()
        if returncode != 0:
            # A non-zero harness exit is a failure regardless of streamed result.
            yield Done(result=f"harness exited {returncode}", is_error=True)
        elif not saw_done:
            yield Done(result="", is_error=True)

    async def resume(self, session: SessionId) -> SessionId:
        # Re-prompting a resumed session would pass `--resume <harness_session_id>`;
        # full re-prompt wiring lands with the DAG executor (M3). M2 only needs
        # the handle to remain valid.
        return session

    async def cancel(self, session: SessionId) -> None:
        self._sessions.pop(session, None)

    def translate(self, caps: object, *, cwd: Path | None = None) -> list[str]:
        """ResolvedCaps → Claude Code CLI flags (spec §4.1, §5)."""
        from orchestrator.safety.capabilities import ResolvedCaps as RC

        if not isinstance(caps, RC):
            return []
        flags: list[str] = []
        if cwd is not None:
            flags += ["--add-dir", str(cwd)]
        flags += ["--permission-mode", caps.permission_mode]
        if caps.allowed_tools:
            flags += ["--allowedTools", ",".join(caps.allowed_tools)]
        if caps.disallowed_tools:
            flags += ["--disallowedTools", ",".join(caps.disallowed_tools)]
        return flags
