import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.scheduler import DeterministicScheduler
from tests.fixtures.repo import make_repo

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _loop_pipeline() -> Pipeline:
    # implement -> review (reject->implement) -> test. Minimal cycle.
    return Pipeline.model_validate({
        "name": "loop",
        "mode": "declarative",
        "inputs": {"task": "string"},
        "steps": [
            {"id": "implement", "role": "implementer", "prompt": "Implement {{task}}",
             "success_criteria": "true", "max_retries": 2},
            {"id": "review", "role": "reviewer", "needs": ["implement"],
             "prompt": "Please review {{implement.output}}",
             "output_schema": {"verdict": "enum[approve,reject]"},
             "on_reject": "implement"},
            {"id": "test", "role": "implementer", "needs": ["review"],
             "prompt": "Run the checks", "success_criteria": "true"},
        ],
    })


async def test_review_loop_rejects_then_approves(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state.json"))
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("ORCH_FAKE_CALLS", str(calls))
    configure_tracing(exporter=InMemorySpanExporter())

    repo = make_repo(tmp_path / "repo")
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    scheduler = DeterministicScheduler(ws, adapter, repo)

    ctx = await scheduler.run(_loop_pipeline(), {"task": "add a widget"}, run_id="loop1")

    # implement ran twice (initial + one reject), review ran twice, test ran once.
    assert ctx.attempts["implement"] == 2
    assert ctx.attempts["review"] == 2
    assert "test" in ctx.artifacts
    assert ctx.artifacts["review"].output_data == {"verdict": "approve"}  # last verdict
    assert ctx.artifacts["test"].is_error is False
