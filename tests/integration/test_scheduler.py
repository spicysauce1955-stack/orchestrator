import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.scheduler import DeterministicScheduler
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


async def test_linear_pipeline_runs_end_to_end(tmp_path, monkeypatch):
    # Route classify -> classify.ndjson (JSON kind), other steps -> default.ndjson.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    configure_tracing(exporter=InMemorySpanExporter())

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    pipeline = ws.pipelines["triage"]
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])

    scheduler = DeterministicScheduler(ws, adapter, repo)
    ctx = await scheduler.run(pipeline, {"task": "add a widget"}, run_id="run1")

    # all three steps produced artifacts
    assert set(ctx.artifacts) == {"classify", "plan", "implement"}
    assert ctx.artifacts["classify"].output_data == {"kind": "feature"}
    assert ctx.artifacts["implement"].is_error is False
    # cost rolled up across steps
    assert ctx.total_cost_usd > 0
