"""OpenCodeCLIAdapter: drive `opencode run --format json` (spec §5, 2nd adapter).

Proves harness != model: OpenCode reaches 75+ providers (e.g. zhipu/glm-4.6).
Mirrors ClaudeCodeCLIAdapter: pure NDJSON parser + async streaming + caps
translation. OpenCode has no OS sandbox, so the worktree is the isolation
boundary; caps translate to an OpenCode permission config (best-effort).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
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
from orchestrator.safety.capabilities import ResolvedCaps

# OpenCode tool names that mutate files → also emit a FileEdit.
_EDIT_TOOLS = {"edit": "modify", "write": "create", "patch": "modify"}

# Credential-ish paths excluded from reads (mirrors spec §4.1 fs credential exclusion).
_READ_DENY = ["*.env", "*.env.*", "**/.ssh/**", "**/.aws/**"]

# Convenience aliases for the `provider/model` string carried by a role.
_MODEL_ALIASES = {"glm": "zhipu/glm-4.6"}


def _alias_model(model: str | None) -> str | None:
    if model is None:
        return None
    return _MODEL_ALIASES.get(model, model)


def parse_opencode_line(obj: dict, tool_names: dict[str, str]) -> list[Event]:
    """Map one decoded OpenCode JSON event to normalized events.

    `tool_names` is mutated (tool id → name) for symmetry with the Claude
    parser; OpenCode reports tool completion on `step_finish`/separate events
    which the adapter does not currently surface as completed ToolCalls.
    """
    kind = obj.get("type")
    # Real opencode nests the payload under `part`; the event's top level carries
    # only `type`/`sessionID`/`timestamp`. (The fakes mirror this shape.)
    part = obj.get("part") or {}

    if kind == "step_start":
        return [SessionStarted(obj.get("sessionID", ""))]

    if kind == "text":
        return [MessageChunk(part.get("text", ""))]

    if kind == "tool_use":
        name = part.get("tool", "") or part.get("name", "")
        tool_id = part.get("callID", "") or part.get("id", "")
        if tool_id:
            tool_names[tool_id] = name
        state = part.get("state") or {}
        status = state.get("status") or "in_progress"
        events: list[Event] = [ToolCall(name, status)]
        if name in _EDIT_TOOLS:
            inp = state.get("input") or {}
            path = inp.get("filePath") or inp.get("path") or inp.get("file_path") or ""
            if path:
                events.append(FileEdit(path, _EDIT_TOOLS[name]))
        return events

    if kind == "step_finish":
        cost = float(part.get("cost", 0.0) or 0.0)
        raw_tokens = part.get("tokens", 0)
        # Real opencode reports tokens as a dict {total,input,output,...}; the
        # fakes (and older shapes) may use a flat int.
        if isinstance(raw_tokens, dict):
            tokens = int(raw_tokens.get("total", 0) or 0)
        else:
            tokens = int(raw_tokens or 0)
        return [Cost(usd=cost, tokens=tokens)]

    return []


def _can_edit(caps: ResolvedCaps) -> bool:
    edit_markers = {"Edit", "Write", "MultiEdit", "edit", "write", "patch"}
    if any(t in edit_markers for t in caps.disallowed_tools):
        return False
    return any(t in edit_markers for t in caps.allowed_tools) or caps.permission_mode != "default"


def build_permission_config(caps: ResolvedCaps) -> dict:
    """ResolvedCaps → an OpenCode `permission` config (best-effort).

    OpenCode has no OS sandbox; this constrains the agent's tools, while the
    worktree remains the hard filesystem boundary.
    """
    can_edit = _can_edit(caps)
    shell_deny = tuple(getattr(caps, "shell_deny", ()) or ())
    bash: dict[str, str] | str
    if not can_edit:
        bash = "deny"
    else:
        bash = {f"{pat}*" if not pat.endswith("*") else pat: "deny" for pat in shell_deny}
        bash["*"] = "allow"
    read = {"*": "allow"}
    for pat in _READ_DENY:
        read[pat] = "deny"
    return {
        "permission": {
            "edit": "allow" if can_edit else "deny",
            "bash": bash,
            "read": read,
        }
    }


@dataclass
class _OCSession:
    cwd: Path
    caps: ResolvedCaps
    mcp_servers: list[McpServer]
    model: str | None = None
    config_path: str | None = None
    harness_session_id: str | None = None


class OpenCodeCLIAdapter:
    """Drives OpenCode via `opencode run --format json`.

    `binary` default `["opencode"]`; honors $ORCH_OPENCODE_BIN. `model` is the
    `provider/model` string (from the role); `glm` is aliased to zhipu/glm-4.6.
    """

    def __init__(self, binary: list[str] | None = None, *, model: str | None = None) -> None:
        if binary is None:
            env_bin = os.environ.get("ORCH_OPENCODE_BIN")
            binary = env_bin.split() if env_bin else ["opencode"]
        self._binary = binary
        self._model = _alias_model(model)
        self._sessions: dict[SessionId, _OCSession] = {}

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: ResolvedCaps,
        mcp_servers: list[McpServer],
        model: str | None = None,
    ) -> SessionId:
        handle = uuid.uuid4().hex
        cfg = build_permission_config(caps)
        if mcp_servers:
            # command is a single binary; args are kept separate and spliced into
            # OpenCode's list form. (McpServer.command must not embed spaces.)
            cfg["mcp"] = {
                s.name: {
                    "type": "local",
                    "command": [s.command, *s.args],
                    "environment": dict(s.env),
                    "enabled": True,
                }
                for s in mcp_servers
            }
        fd, path = tempfile.mkstemp(prefix="orch-oc-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg, fh)
        # A per-session model (from the role) overrides the construction default.
        self._sessions[handle] = _OCSession(
            cwd=Path(cwd),
            caps=caps,
            mcp_servers=list(mcp_servers),
            model=_alias_model(model) if model else self._model,
            config_path=path,
        )
        return handle

    async def prompt(
        self, session: SessionId, text: str, *, output_schema: dict | None = None
    ) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        cmd = [
            *self._binary,
            "run",
            "--format",
            "json",
            "--print-logs",
            "--dir",
            str(sess.cwd),
        ]
        if sess.model:
            cmd += ["-m", sess.model]
        cmd.append(text)
        return self._stream(session, cmd)

    async def _stream(self, session: SessionId, cmd: list[str]) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        env = dict(os.environ)
        if sess.config_path:
            env["OPENCODE_CONFIG"] = sess.config_path
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sess.cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain stderr concurrently (--print-logs writes there) so a chatty child
        # never blocks on a full pipe and a non-zero exit can report its cause.
        stderr_chunks: list[bytes] = []

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            data = await proc.stderr.read()
            if data:
                stderr_chunks.append(data)

        stderr_task = asyncio.ensure_future(_drain_stderr())
        tool_names: dict[str, str] = {}
        text_parts: list[str] = []
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for ev in parse_opencode_line(obj, tool_names):
                if isinstance(ev, SessionStarted):
                    sess.harness_session_id = ev.session_id
                if isinstance(ev, MessageChunk):
                    text_parts.append(ev.text)
                yield ev
        returncode = await proc.wait()
        await stderr_task
        # OpenCode has no single "result" event; synthesize Done at stream end.
        if returncode != 0:
            tail = b"".join(stderr_chunks).decode(errors="replace").strip()
            result = "".join(text_parts)
            if tail:
                result = f"{result}\n[opencode exited {returncode}: {tail[-500:]}]".strip()
            yield Done(result=result, is_error=True)
        else:
            yield Done(result="".join(text_parts), is_error=False)

    async def resume(self, session: SessionId) -> SessionId:
        return session

    async def cancel(self, session: SessionId) -> None:
        sess = self._sessions.pop(session, None)
        if sess and sess.config_path:
            try:
                os.unlink(sess.config_path)
            except OSError:
                pass
