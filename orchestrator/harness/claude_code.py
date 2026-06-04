"""ClaudeCodeCLIAdapter: drive `claude -p --output-format stream-json` (spec §5).

Split into three concerns:
- `parse_line`        : pure NDJSON-object → normalized events (this task)
- `ClaudeCodeCLIAdapter.translate` : ResolvedCaps → CLI flags (Task 10)
- `ClaudeCodeCLIAdapter` async streaming + diff capture (Task 6)
"""

from __future__ import annotations

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
