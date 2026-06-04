import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import (
    SPAN_SESSION,
    SPAN_STEP,
    SPAN_TOOL_CALL,
    configure_tracing,
)
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


async def test_plan_step_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    exporter = InMemorySpanExporter()
    configure_tracing(exporter=exporter)

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    pipeline = ws.pipelines["feature"]
    step = next(s for s in pipeline.steps if s.id == "plan")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="run1", inputs={"task": "add a feature"})

    artifact = await run_agent_step(
        ws, pipeline, step, ctx, repo=repo, adapter=adapter
    )

    # artifact captured
    assert artifact.step_id == "plan"
    assert "1. do X" in artifact.output
    assert artifact.is_error is False
    assert artifact.cost_usd == 0.012
    assert artifact.diff == ""  # read-only planner makes no edits
    assert ctx.artifacts["plan"] is artifact
    assert ctx.total_cost_usd == 0.012

    # spans emitted
    names = [s.name for s in exporter.get_finished_spans()]
    assert SPAN_STEP in names
    assert SPAN_SESSION in names
    assert SPAN_TOOL_CALL in names  # the Read tool call


async def test_agent_step_captures_diff_when_harness_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    pipeline = ws.pipelines["feature"]
    step = next(s for s in pipeline.steps if s.id == "implement")
    # Make the fake harness write a file inside whatever worktree it runs in.
    # ORCH_FAKE_TOUCH is resolved relative to the harness CWD (the worktree).
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "note.txt")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="run2", inputs={"task": "edit something"})

    artifact = await run_agent_step(
        ws, pipeline, step, ctx, repo=repo, adapter=adapter
    )

    assert "note.txt" in artifact.diff
    assert artifact.branch.endswith("implement")
