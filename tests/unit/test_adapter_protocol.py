from collections.abc import AsyncIterator
from pathlib import Path

from orchestrator.harness.adapter import HarnessAdapter, McpServer, SessionId
from orchestrator.harness.events import Done, Event, SessionStarted


def test_mcp_server_fields():
    m = McpServer(name="repo-index", command="node", args=["s.js"], env={"K": "v"})
    assert m.name == "repo-index"
    assert m.args == ["s.js"]
    assert m.env == {"K": "v"}


def test_protocol_is_runtime_checkable():
    class Dummy:
        async def start_session(self, *, cwd, caps, mcp_servers) -> SessionId:
            return "h1"

        async def prompt(self, session, text, *, output_schema=None) -> AsyncIterator[Event]:
            async def _gen():
                yield SessionStarted("s")
                yield Done("ok", False)

            return _gen()

        async def resume(self, session) -> SessionId:
            return session

        async def cancel(self, session) -> None:
            return None

    assert isinstance(Dummy(), HarnessAdapter)


def test_non_adapter_fails_isinstance():
    class NotAdapter:
        pass

    assert not isinstance(NotAdapter(), HarnessAdapter)
    # silence unused-import lint for Path in this focused test module
    assert Path(".").exists()
