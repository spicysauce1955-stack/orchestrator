"""CodexCLIAdapter: drive `codex exec --json` (spec §5, 3rd adapter).

Design: docs/superpowers/specs/2026-06-10-codex-adapter-design.md.
Mirrors OpenCodeCLIAdapter (no single result event → synthesized Done; no
usable OS sandbox → the worktree is the isolation boundary). Knowledge MCP is
wired via `-c mcp_servers.*` overrides layered on the user's real config —
a temp CODEX_HOME would break auth.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from orchestrator.safety.capabilities import ResolvedCaps

# codex file_change kinds → normalized FileEdit kinds
_CHANGE_KINDS = {"add": "create", "update": "modify", "delete": "delete"}


def parse_codex_line(obj: dict, items: dict[str, str]) -> list[Event]:
    """Map one decoded `codex exec --json` object to normalized events.

    `items` is mutated (item id → item type) so started/completed pairs can be
    correlated (symmetry with the other parsers' `tool_names`). Error items
    return no events: codex emits non-fatal ones (config deprecations) in
    every run, so the adapter decides whether to surface them at exit.
    """
    kind = obj.get("type")

    if kind == "thread.started":
        return [SessionStarted(obj.get("thread_id", ""))]

    if kind == "turn.completed":
        usage = obj.get("usage") or {}
        tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
        return [Cost(usd=0.0, tokens=tokens)]

    if kind in ("item.started", "item.completed"):
        item = obj.get("item") or {}
        itype = item.get("type", "")
        item_id = item.get("id", "")
        if item_id and itype:
            items[item_id] = itype
        completed = kind == "item.completed"
        if itype == "agent_message" and completed:
            return [MessageChunk(item.get("text", ""))]
        if itype == "command_execution":
            return [ToolCall("command", "completed" if completed else "in_progress")]
        if itype == "file_change" and completed:
            # Completed only: codex repeats the payload on item.started.
            return [
                FileEdit(ch.get("path", ""), _CHANGE_KINDS.get(ch.get("kind", ""), "modify"))
                for ch in item.get("changes", []) or []
                if ch.get("path")
            ]

    return []


def _mcp_overrides(servers: list[McpServer]) -> list[str]:
    """McpServer list → `codex -c` config overrides (verified vs `codex mcp list`).

    `-c` values are parsed as TOML; json.dumps of a str / list[str] is valid
    TOML for those types. Per-key `env.<KEY>` dotted paths avoid inline-table
    syntax. Layering on the real config preserves auth.json and the user's
    existing servers; there is no temp file to clean up.
    """
    flags: list[str] = []
    for s in servers:
        base = f"mcp_servers.{s.name}"
        flags += ["-c", f"{base}.command={json.dumps(s.command)}"]
        if s.args:
            flags += ["-c", f"{base}.args={json.dumps(list(s.args))}"]
        for key, value in s.env.items():
            flags += ["-c", f"{base}.env.{key}={json.dumps(value)}"]
    return flags


@dataclass
class _CodexSession:
    cwd: Path
    caps: ResolvedCaps
    mcp_servers: list[McpServer]
    model: str | None = None
    harness_session_id: str | None = None


class CodexCLIAdapter:
    """Drives Codex via `codex exec --json`.

    `binary` default `["codex"]`; honors $ORCH_CODEX_BIN. Sandbox is always
    bypassed: codex's bwrap sandbox fails in externally-isolated environments,
    and the orchestrator's worktree is the isolation boundary (spec §4/§9 —
    same MVP stance as OpenCode). `caps` is stored for forward compatibility;
    codex exec exposes no per-tool flags to translate it to.
    """

    def __init__(self, binary: list[str] | None = None, *, model: str | None = None) -> None:
        if binary is None:
            env_bin = os.environ.get("ORCH_CODEX_BIN")
            binary = env_bin.split() if env_bin else ["codex"]
        self._binary = binary
        self._model = model
        self._sessions: dict[SessionId, _CodexSession] = {}

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: ResolvedCaps,
        mcp_servers: list[McpServer],
        model: str | None = None,
    ) -> SessionId:
        handle = uuid.uuid4().hex
        # A per-session model (from the role) overrides the construction default.
        self._sessions[handle] = _CodexSession(
            cwd=Path(cwd),
            caps=caps,
            mcp_servers=list(mcp_servers),
            model=model or self._model,
        )
        return handle

    async def prompt(
        self, session: SessionId, text: str, *, output_schema: dict | None = None
    ) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        cmd = [
            *self._binary,
            "exec",
            "-C",
            str(sess.cwd),
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if sess.model:
            cmd += ["-m", sess.model]
        cmd += _mcp_overrides(sess.mcp_servers)
        cmd.append(text)
        return self._stream(session, cmd)

    async def _stream(self, session: SessionId, cmd: list[str]) -> AsyncIterator[Event]:
        sess = self._sessions[session]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sess.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain stderr concurrently so a chatty child never blocks on a full
        # pipe and a non-zero exit can report its cause (same as both peers).
        stderr_chunks: list[bytes] = []

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            data = await proc.stderr.read()
            if data:
                stderr_chunks.append(data)

        stderr_task = asyncio.ensure_future(_drain_stderr())
        items: dict[str, str] = {}
        text_parts: list[str] = []
        error_msgs: list[str] = []
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Error items are non-events (codex emits non-fatal ones every
            # run); remember them in case the process exits non-zero.
            item = obj.get("item") or {}
            if obj.get("type") == "item.completed" and item.get("type") == "error":
                error_msgs.append(item.get("message", ""))
            for ev in parse_codex_line(obj, items):
                if isinstance(ev, SessionStarted):
                    sess.harness_session_id = ev.session_id
                if isinstance(ev, MessageChunk):
                    text_parts.append(ev.text)
                yield ev
        returncode = await proc.wait()
        await stderr_task
        # Codex has no single "result" event; synthesize Done at stream end.
        if returncode != 0:
            tail = b"".join(stderr_chunks).decode(errors="replace").strip()
            # Last two error items only: codex can emit several per run; cap to
            # keep the failure message readable.
            detail = "; ".join(filter(None, [*error_msgs[-2:], tail[-500:] if tail else ""]))
            result = "".join(text_parts)
            suffix = f": {detail}" if detail else ""
            yield Done(
                result=f"{result}\n[codex exited {returncode}{suffix}]".strip(),
                is_error=True,
            )
        else:
            yield Done(result="".join(text_parts), is_error=False)

    async def resume(self, session: SessionId) -> SessionId:
        # Codex-native resume/fork deferred (spec: out of scope); the handle
        # remains valid, matching the other adapters' MVP stance.
        return session

    async def cancel(self, session: SessionId) -> None:
        self._sessions.pop(session, None)
