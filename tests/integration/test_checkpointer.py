import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


async def test_run_sets_pipeline_name_and_writes_checkpoint(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)
    ctx = await sched.run(ws.pipelines["review-demo"], {"task": "add x"}, "run-ckpt-1")
    assert ctx.pipeline_name == "review-demo"
    assert ctx.status == RunStatus.COMPLETED
    assert db.exists()
