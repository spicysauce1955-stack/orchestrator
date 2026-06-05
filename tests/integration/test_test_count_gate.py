import subprocess
import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Step
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.spans import configure_tracing
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "scripts"
EXAMPLE = "examples/feature-pipeline/.orchestrator"


def _repo_with_tests(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)

    def git(*a):
        subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@e.com")
    git("config", "user.name", "T")
    git("config", "commit.gpgsign", "false")
    (path / "test_sample.py").write_text(
        "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n"
    )
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return path


def _step():
    return Step.model_validate({
        "id": "implement", "role": "implementer", "prompt": "work",
        "success_criteria": "true",  # criteria itself passes
    })


async def test_gate_fails_when_tests_deleted(tmp_path, monkeypatch):
    configure_tracing(exporter=InMemorySpanExporter())
    repo = _repo_with_tests(tmp_path / "repo")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    # The harness deletes the test file inside its worktree cwd.
    monkeypatch.setenv("ORCH_FAKE_DELETE", "test_sample.py")
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="gate1", inputs={"task": "t"})

    art = await run_agent_step(
        ws, ws.pipelines["feature"], _step(), ctx, repo=repo, adapter=adapter
    )
    assert art.is_error is True
    assert "test-count" in art.output.lower()
    assert "2->0" in art.output  # the gate reports the actual regression (2 tests -> 0)


async def test_gate_passes_when_tests_intact(tmp_path, monkeypatch):
    configure_tracing(exporter=InMemorySpanExporter())
    repo = _repo_with_tests(tmp_path / "repo")
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "default.ndjson"))
    monkeypatch.delenv("ORCH_FAKE_DELETE", raising=False)
    ws = load_workspace(EXAMPLE)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="gate2", inputs={"task": "t"})

    art = await run_agent_step(
        ws, ws.pipelines["feature"], _step(), ctx, repo=repo, adapter=adapter
    )
    assert art.is_error is False
