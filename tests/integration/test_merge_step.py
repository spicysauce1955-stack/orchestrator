import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.executors import run_merge_step
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import Artifact, RunContext, RunStatus

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
GH = Path(__file__).parents[1] / "fixtures" / "fake_gh" / "fake_gh.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _repo(tmp_path, *, with_origin=True):
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


@pytest.mark.asyncio
async def test_merge_creates_branch_and_opens_pr(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(FAKE.parent / "scripts"))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ORCH_FAKE_TOUCH", "feature.py")
    monkeypatch.setenv("ORCH_GH_BIN", f"{sys.executable} {GH}")
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)])
    ws = load_workspace(EXAMPLE)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=db)
    pipe = Pipeline(
        name="mergetest",
        steps=[
            Step(id="implement", role="implementer", prompt="do {{task}}", success_criteria="true"),
            Step(id="merge", type=StepType.task, needs=["implement"],
                 merge_strategy="sequential-rebase"),
        ],
    )
    ctx = await sched.run(pipe, {"task": "add feature"}, "run-merge-1")
    assert ctx.status == RunStatus.COMPLETED
    merge_art = ctx.artifacts["merge"]
    assert not merge_art.is_error
    assert merge_art.output_data and merge_art.output_data.get("pr_url")
    # the implement diff (feature.py) made it onto the integration branch
    branch = merge_art.output_data["branch"]
    show = subprocess.run(["git", "show", f"{branch}:feature.py"], cwd=repo,
                          capture_output=True, text=True)
    assert show.returncode == 0


@pytest.mark.asyncio
async def test_merge_refuses_on_reject_verdict(tmp_path):
    """Verdict guard: a non-approve terminal review verdict blocks merge."""
    repo = _repo(tmp_path, with_origin=False)
    ctx = RunContext(run_id="r1", pipeline_name="p")
    ctx.record(Artifact(step_id="implement", output="did work", diff="", branch="",
                        cost_usd=0.0, tokens=0, is_error=False))
    ctx.record(Artifact(step_id="review", output="nope", diff="", branch="",
                        cost_usd=0.0, tokens=0, is_error=False,
                        output_data={"verdict": "reject"}))
    pipe = Pipeline(
        name="p",
        steps=[
            Step(id="implement", role="implementer", prompt="x", success_criteria="true"),
            Step(id="review", role="reviewer", needs=["implement"], prompt="r",
                 output_schema={"verdict": "enum[approve,reject]"}),
            Step(id="merge", type=StepType.task, needs=["review"],
                 merge_strategy="sequential-rebase"),
        ],
    )
    merge_step = pipe.steps[-1]
    art = await run_merge_step(None, pipe, merge_step, ctx, repo=repo, adapter=None)
    assert art.is_error
    assert "verdict" in art.output.lower()
