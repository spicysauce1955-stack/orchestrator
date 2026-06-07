import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Role, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _ws():
    ws = Workspace(config=Config())
    ws.roles = {"implementer": Role(name="implementer", harness=Harness.claude_code)}
    return ws


async def test_relayed_feedback_is_injected_and_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    ws = _ws()
    repo = _repo(tmp_path)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", inputs={"task": "x"}, pipeline_name="p")
    ctx.relayed_feedback["implement"] = "reject: add a test for the new flag"
    step = Step(id="implement", role="implementer", type=StepType.agent, prompt="do {{task}}")
    await run_agent_step(
        ws, Pipeline(name="p", steps=[step]), step, ctx, repo=repo, adapter=adapter
    )
    argv = (tmp_path / "argv.txt").read_text()
    assert "add a test for the new flag" in argv      # relayed feedback reached the prompt
    assert "implement" not in ctx.relayed_feedback      # consumed (one-shot)


async def test_no_relayed_feedback_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "edit.ndjson"))
    monkeypatch.setenv("ORCH_FAKE_ARGV", str(tmp_path / "argv.txt"))
    ws = _ws()
    repo = _repo(tmp_path)
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ctx = RunContext(run_id="r1", inputs={"task": "x"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent, prompt="do {{task}}")
    await run_agent_step(
        ws, Pipeline(name="p", steps=[step]), step, ctx, repo=repo, adapter=adapter
    )
    argv = (tmp_path / "argv.txt").read_text()
    assert "Reviewer feedback" not in argv
