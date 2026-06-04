"""Normalized harness event model (spec §5).

Every adapter emits this set, deliberately shaped like ACP `session/update`
so the future ACPAdapter is a near-literal mapping.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionStarted:
    session_id: str


@dataclass(frozen=True)
class MessageChunk:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    status: str  # pending | in_progress | completed | failed


@dataclass(frozen=True)
class FileEdit:
    path: str
    kind: str  # create | modify | delete


@dataclass(frozen=True)
class Cost:
    usd: float
    tokens: int


@dataclass(frozen=True)
class Done:
    result: str
    is_error: bool


Event = SessionStarted | MessageChunk | ToolCall | FileEdit | Cost | Done
