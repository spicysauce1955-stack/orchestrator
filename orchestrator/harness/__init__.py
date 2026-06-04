"""Harness adapter layer: the swappability seam (spec §5)."""

from orchestrator.harness.adapter import HarnessAdapter, McpServer, SessionId
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter, parse_line
from orchestrator.harness.events import (
    Cost,
    Done,
    Event,
    FileEdit,
    MessageChunk,
    SessionStarted,
    ToolCall,
)

__all__ = [
    "HarnessAdapter",
    "McpServer",
    "SessionId",
    "ClaudeCodeCLIAdapter",
    "parse_line",
    "Event",
    "SessionStarted",
    "MessageChunk",
    "ToolCall",
    "FileEdit",
    "Cost",
    "Done",
]
