import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Step
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.executors import run_task_step
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


async def test_classify_task_parses_enum_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "classify", "type": "task",
        "prompt": "Classify {{task}} as: bugfix | feature | refactor",
        "output_schema": {"kind": "enum[bugfix,feature,refactor]"},
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", inputs={"task": "add a widget"})

    artifact = await run_task_step(
        ws, ws.pipelines["feature"], step, ctx, repo=tmp_path, adapter=adapter
    )

    assert artifact.is_error is False
    assert artifact.output_data == {"kind": "feature"}
    assert ctx.artifacts["classify"].output_data["kind"] == "feature"


async def test_task_invalid_enum_value_is_error(tmp_path, monkeypatch):
    # classify.ndjson returns "feature"; constrain the enum so it's NOT allowed.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate({
        "id": "classify", "type": "task",
        "prompt": "x", "output_schema": {"kind": "enum[bugfix,refactor]"},
    })
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r2", inputs={"task": "t"})
    artifact = await run_task_step(
        ws, ws.pipelines["feature"], step, ctx, repo=tmp_path, adapter=adapter
    )
    assert artifact.is_error is True


async def test_merge_task_step_rejected_until_m5(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    configure_tracing(exporter=InMemorySpanExporter())
    ws = load_workspace(EXAMPLE)
    step = Step.model_validate(
        {"id": "merge", "type": "task", "merge_strategy": "sequential-rebase"}
    )
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r3", inputs={})
    with pytest.raises(NotImplementedError):
        await run_task_step(ws, ws.pipelines["feature"], step, ctx, repo=tmp_path, adapter=adapter)
