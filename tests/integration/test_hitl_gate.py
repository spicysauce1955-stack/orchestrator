import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _gate_pipeline() -> Pipeline:
    return Pipeline(
        name="gateonly",
        steps=[
            Step(id="audit", type=StepType.task, prompt="audit {{task}}"),
            Step(id="approve", type=StepType.gate, require_approval=True, needs=["audit"]),
        ],
    )


def _sched(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    repo = _git_repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    return DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)


async def test_run_pauses_at_gate(tmp_path, monkeypatch):
    sched = _sched(tmp_path, monkeypatch)
    ctx = await sched.run(_gate_pipeline(), {"task": "ship it"}, "run-gate-1")
    assert ctx.status == RunStatus.PAUSED
    assert ctx.pending_interrupt is not None
    assert ctx.pending_interrupt.get("step_id") == "approve"
    assert "approve" not in ctx.gate_decisions


async def test_resume_approve_completes(tmp_path, monkeypatch):
    sched = _sched(tmp_path, monkeypatch)
    await sched.run(_gate_pipeline(), {"task": "ship it"}, "run-gate-2")
    ctx = await sched.resume("run-gate-2", "approve")
    assert ctx.status == RunStatus.COMPLETED
    assert ctx.gate_decisions["approve"] == "approve"


async def test_resume_reject_ends_run(tmp_path, monkeypatch):
    sched = _sched(tmp_path, monkeypatch)
    await sched.run(_gate_pipeline(), {"task": "ship it"}, "run-gate-3")
    ctx = await sched.resume("run-gate-3", "reject")
    assert ctx.status == RunStatus.COMPLETED
    assert ctx.gate_decisions["approve"] == "reject"
