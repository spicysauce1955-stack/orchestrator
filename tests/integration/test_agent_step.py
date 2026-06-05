import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Step
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import (
    SPAN_SESSION,
    SPAN_STEP,
    SPAN_TOOL_CALL,
    configure_tracing,
)
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext
from orchestrator.runtime.template import TemplateError
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
    assert "/implement/" in artifact.branch  # branch now carries an attempt suffix


async def test_success_criteria_retries_then_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("ORCH_FAKE_CALLS", str(calls))

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    # success_criteria fails on attempt 1 (counter=1), passes on attempt 2 (counter>=2).
    step = Step.model_validate({
        "id": "impl_retry",
        "role": "implementer",
        "prompt": "do the work",
        "success_criteria": (
            "c=$(cat .c 2>/dev/null || echo 0); c=$((c+1)); echo $c > .c; test $c -ge 2"
        ),
        "max_retries": 2,
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="rtry", inputs={"task": "t"})

    artifact = await run_agent_step(
        ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter
    )

    assert artifact.is_error is False           # passed within retry budget
    # Each invocation logs prompt[:60]; count entries starting with base prompt.
    log_lines = calls.read_text().splitlines()
    invocations = sum(1 for ln in log_lines if ln.startswith("do the work"))
    assert invocations == 2                     # harness re-prompted once
    assert artifact.cost_usd > 0.01             # cost summed across 2 attempts


async def test_success_criteria_fails_after_exhausting_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "impl_fail",
        "role": "implementer",
        "prompt": "do the work",
        "success_criteria": "false",
        "max_retries": 1,
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="fail", inputs={"task": "t"})

    artifact = await run_agent_step(
        ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter
    )
    assert artifact.is_error is True


async def test_bad_template_ref_raises_template_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "impl_bad_ref",
        "role": "implementer",
        "prompt": "use {{nonexistent}}",
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="tmpl", inputs={"task": "t"})

    with pytest.raises(TemplateError):
        await run_agent_step(
            ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter
        )


async def test_repeated_agent_step_uses_distinct_branches(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({"id": "implement", "role": "implementer", "prompt": "do the work"})
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="reentry", inputs={"task": "t"})

    a1 = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)
    a2 = await run_agent_step(ws, ws.pipelines["feature"], step, ctx, repo=repo, adapter=adapter)

    assert a1.branch != a2.branch
    assert a1.branch.endswith("/1")
    assert a2.branch.endswith("/2")
    assert ctx.attempts["implement"] == 2
