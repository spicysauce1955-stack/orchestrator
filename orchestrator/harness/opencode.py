"""OpenCodeCLIAdapter: drive `opencode run --format json` (spec §5, 2nd adapter).

Proves harness != model: OpenCode reaches 75+ providers (e.g. zhipu/glm-4.6).
Mirrors ClaudeCodeCLIAdapter: pure NDJSON parser + async streaming + caps
translation. OpenCode has no OS sandbox, so the worktree is the isolation
boundary; caps translate to an OpenCode permission config (best-effort).
"""

from __future__ import annotations

from orchestrator.harness.events import (
    Cost,
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


def parse_opencode_line(obj: dict, tool_names: dict[str, str]) -> list[Event]:
    """Map one decoded OpenCode JSON event to normalized events.

    `tool_names` is mutated (tool id → name) for symmetry with the Claude
    parser; OpenCode reports tool completion on `step_finish`/separate events
    which the adapter does not currently surface as completed ToolCalls.
    """
    kind = obj.get("type")

    if kind == "step_start":
        return [SessionStarted(obj.get("sessionID", ""))]

    if kind == "text":
        return [MessageChunk(obj.get("text", ""))]

    if kind == "tool_use":
        name = obj.get("tool", "") or obj.get("name", "")
        tool_id = obj.get("id", "")
        if tool_id:
            tool_names[tool_id] = name
        events: list[Event] = [ToolCall(name, "in_progress")]
        if name in _EDIT_TOOLS:
            path = (obj.get("input", {}) or {}).get("path", "") or (
                obj.get("input", {}) or {}
            ).get("file_path", "")
            if path:
                events.append(FileEdit(path, _EDIT_TOOLS[name]))
        return events

    if kind == "step_finish":
        return [Cost(usd=float(obj.get("cost", 0.0)), tokens=int(obj.get("tokens", 0)))]

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
