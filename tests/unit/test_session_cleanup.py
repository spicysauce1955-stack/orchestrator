from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orchestrator.harness.events import Cost, Done, MessageChunk
from orchestrator.observability.spans import configure_tracing, get_tracer
from orchestrator.runtime.executors import _drive_harness
from orchestrator.safety.capabilities import ResolvedCaps


class _FakeAdapter:
    def __init__(self, *, raise_on_prompt: bool = False) -> None:
        self.cancelled: list[str] = []
        self._raise = raise_on_prompt

    async def start_session(self, *, cwd, caps, mcp_servers):
        return "sess-1"

    async def prompt(self, session, text, *, output_schema):
        if self._raise:
            raise RuntimeError("boom")

        async def _gen():
            yield MessageChunk("hi")
            yield Cost(usd=0.1, tokens=10)
            yield Done(result="done", is_error=False)

        return _gen()

    async def resume(self, session):  # pragma: no cover - unused here
        return session

    async def cancel(self, session) -> None:
        self.cancelled.append(session)


def _caps():
    # ResolvedCaps is a frozen dataclass with all-default fields; the simplest
    # valid construction is the no-arg form (equivalent to ResolvedCaps.read_only()
    # but without the deny lists, which don't affect cleanup behaviour).
    return ResolvedCaps()


def test_session_cancelled_on_success(tmp_path: Path) -> None:
    configure_tracing(exporter=None)
    adapter = _FakeAdapter()
    asyncio.run(_drive_harness(adapter, _caps(), tmp_path, "go", None, get_tracer()))
    assert adapter.cancelled == ["sess-1"]


def test_session_cancelled_on_error(tmp_path: Path) -> None:
    configure_tracing(exporter=None)
    adapter = _FakeAdapter(raise_on_prompt=True)
    with pytest.raises(RuntimeError):
        asyncio.run(_drive_harness(adapter, _caps(), tmp_path, "go", None, get_tracer()))
    assert adapter.cancelled == ["sess-1"]
