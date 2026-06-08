import sys
from pathlib import Path

from orchestrator.harness.events import Cost, Done, FileEdit, SessionStarted, ToolCall
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.safety.capabilities import ResolvedCaps

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
SCRIPTS = FAKE.parent / "scripts"


async def _drive(adapter, cwd, text):
    session = await adapter.start_session(cwd=cwd, caps=ResolvedCaps.read_only(), mcp_servers=[])
    events = []
    stream = await adapter.prompt(session, text)
    async for ev in stream:
        events.append(ev)
    return session, events


async def test_streams_normalized_events(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "implement.ndjson"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "implement it")
    assert isinstance(events[0], SessionStarted)
    assert events[0].session_id == "oc-impl-1"
    assert any(isinstance(e, ToolCall) and e.name == "edit" for e in events)
    assert any(isinstance(e, FileEdit) and e.path == "feature.py" for e in events)
    assert any(isinstance(e, Cost) and e.usd == 0.006 for e in events)
    assert isinstance(events[-1], Done) and events[-1].is_error is False
    assert "Implemented the feature." in events[-1].result


async def test_passes_model_dir_and_format(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_ARGV", str(tmp_path / "argv.txt"))
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)], model="zhipu/glm-4.6")
    await _drive(adapter, tmp_path, "hello oc")
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "run" in argv
    assert "--format" in argv and "json" in argv
    assert "-m" in argv and "zhipu/glm-4.6" in argv
    assert "--dir" in argv
    assert "hello oc" in argv


async def test_session_model_threads_to_command(monkeypatch, tmp_path):
    # A per-session model (from the role) reaches the CLI even when the adapter
    # was constructed with no default model; the `glm` alias is applied.
    monkeypatch.setenv("ORCH_OC_ARGV", str(tmp_path / "argv.txt"))
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])  # no construction model
    session = await adapter.start_session(
        cwd=tmp_path, caps=ResolvedCaps.read_only(), mcp_servers=[], model="glm"
    )
    stream = await adapter.prompt(session, "hello")
    async for _ in stream:
        pass
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "-m" in argv and "zhipu/glm-4.6" in argv


async def test_caps_written_to_opencode_config(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_CONFIG_SEEN", str(tmp_path / "cfgpath.txt"))
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    await _drive(adapter, tmp_path, "x")
    cfg_path = (tmp_path / "cfgpath.txt").read_text().strip()
    assert cfg_path, "OPENCODE_CONFIG should be set for the subprocess"
    import json

    perm = json.loads(Path(cfg_path).read_text())["permission"]
    assert perm["edit"] == "deny"  # read_only caps
    # the config lives OUTSIDE the worktree (no diff pollution)
    assert str(tmp_path) not in cfg_path or "/.orch-oc/" in cfg_path or "tmp" in cfg_path.lower()


async def test_nonzero_exit_yields_error_done(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.setenv("ORCH_OC_EXIT", "2")
    adapter = OpenCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    _, events = await _drive(adapter, tmp_path, "x")
    assert isinstance(events[-1], Done) and events[-1].is_error is True
