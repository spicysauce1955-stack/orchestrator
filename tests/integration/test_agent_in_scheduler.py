import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Role, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "t"]):
        subprocess.run(c, cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _ws():
    ws = Workspace(config=Config())
    ws.roles = {
        "implementer": Role(name="implementer", harness=Harness.claude_code),
        "reviewer": Role(name="reviewer", harness=Harness.claude_code),
    }
    return ws


async def test_classify_emits_message_and_run_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    ws = _ws()
    repo = _repo(tmp_path)
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    sched = DeterministicScheduler(ws, reg, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(name="p", steps=[
        Step(id="classify", type=StepType.task, prompt="classify {{task}}",
             output_schema={"kind": "enum[bugfix,feature,refactor]"}),
    ])
    ctx = await sched.run(pipe, {"task": "add a flag"}, "run-c1")
    assert ctx.status == RunStatus.COMPLETED
    assert any(m.kind == "classify" for m in sched.bus.log)


async def test_reject_cycle_relays_verdict_to_implement(tmp_path, monkeypatch):
    # review.1 rejects, review.2 approves (the M4 numbered-state fake).
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    ws = _ws()
    repo = _repo(tmp_path)
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    sched = DeterministicScheduler(ws, reg, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(name="p", steps=[
        Step(id="implement", role="implementer", needs=[], prompt="implement {{task}}",
             success_criteria="true", max_retries=2),
        Step(id="review", role="reviewer", needs=["implement"], prompt="review",
             output_schema={"verdict": "enum[approve,reject]"}, on_reject="implement"),
    ])
    ctx = await sched.run(pipe, {"task": "x"}, "run-r1")
    assert ctx.status == RunStatus.COMPLETED
    assert any(m.kind == "verdict" and m.to == "implement" for m in sched.bus.log)
