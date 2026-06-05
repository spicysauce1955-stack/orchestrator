import subprocess
import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
GH = Path(__file__).parents[1] / "fixtures" / "fake_gh" / "fake_gh.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path, *, with_origin):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    if with_origin:
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    return repo


def _sched(tmp_path, monkeypatch, repo):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")
    monkeypatch.setenv("ORCH_GH_BIN", f"{sys.executable} {GH}")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    return DeterministicScheduler(ws, adapter, repo, checkpoint_db=db), ws


async def test_full_pipeline_pause_resume_merge(tmp_path, monkeypatch):
    repo = _repo(tmp_path, with_origin=True)
    sched, ws = _sched(tmp_path, monkeypatch, repo)
    ctx = await sched.run(ws.pipelines["full"], {"task": "add a feature"}, "run-full-1")
    assert ctx.status == RunStatus.PAUSED
    assert ctx.pending_interrupt["step_id"] == "approve"
    assert "merge" not in ctx.artifacts

    ctx2 = await sched.resume("run-full-1", "approve")
    assert ctx2.status == RunStatus.COMPLETED, ctx2.artifacts["merge"].output
    assert ctx2.artifacts["merge"].output_data["pr_url"]
    branch = ctx2.artifacts["merge"].output_data["branch"]
    show = subprocess.run(["git", "show", f"{branch}:feature.py"], cwd=repo,
                          capture_output=True, text=True)
    assert show.returncode == 0


async def test_full_pipeline_reject_at_gate_skips_merge(tmp_path, monkeypatch):
    repo = _repo(tmp_path, with_origin=True)
    sched, ws = _sched(tmp_path, monkeypatch, repo)
    await sched.run(ws.pipelines["full"], {"task": "add a feature"}, "run-full-2")
    ctx = await sched.resume("run-full-2", "reject")
    assert ctx.status == RunStatus.COMPLETED
    assert "merge" not in ctx.artifacts  # reject routed to END, merge never ran
