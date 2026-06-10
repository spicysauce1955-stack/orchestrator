"""CodexCLIAdapter: drive `codex exec --json` (spec §5, 3rd adapter).

Design: docs/superpowers/specs/2026-06-10-codex-adapter-design.md.
Mirrors OpenCodeCLIAdapter (no single result event → synthesized Done; no
usable OS sandbox → the worktree is the isolation boundary). Knowledge MCP is
wired via `-c mcp_servers.*` overrides layered on the user's real config —
a temp CODEX_HOME would break auth.json.
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
