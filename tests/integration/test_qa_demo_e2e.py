import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


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


async def test_qa_demo_completes_with_one_answered_question(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    ws = load_workspace(EXAMPLE)
    assert "orchestrator" in ws.roles  # reserved role loaded
    repo = _repo(tmp_path)
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    sched = DeterministicScheduler(ws, reg, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = ws.pipelines["qa-demo"]
    ctx = await sched.run(pipe, {"task": "add a widget"}, "run-qa-1")
    assert ctx.status == RunStatus.COMPLETED
    kinds = [m.kind for m in sched.bus.log]
    assert "classify" in kinds and "question" in kinds and "answer" in kinds
