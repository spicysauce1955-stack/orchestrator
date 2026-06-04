"""The harness swappability seam: a uniform adapter Protocol (spec §5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from orchestrator.harness.events import Event

if TYPE_CHECKING:
    from orchestrator.safety.capabilities import ResolvedCaps

SessionId = str


@dataclass(frozen=True)
class McpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class HarnessAdapter(Protocol):
    """Drives a coding-agent harness uniformly. Implementations own diff
    capture and capability translation (harnesses don't expose them cleanly)."""

    async def start_session(
        self,
        *,
        cwd: Path,
        caps: ResolvedCaps,
        mcp_servers: list[McpServer],
    ) -> SessionId: ...

    async def prompt(
        self,
        session: SessionId,
        text: str,
        *,
        output_schema: dict | None = None,
    ) -> AsyncIterator[Event]: ...

    async def resume(self, session: SessionId) -> SessionId: ...

    async def cancel(self, session: SessionId) -> None: ...
