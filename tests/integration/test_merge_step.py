import subprocess
import sys
from pathlib import Path

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.runtime.executors import run_merge_step
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import (
    CHECKPOINT_SERDE_MODULES,
    Artifact,
    GraphState,
    RunContext,
    RunStatus,
)

SERDE = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_SERDE_MODULES)

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


# ---------------------------------------------------------------------------
# FIX 2: nothing-to-merge short-circuit
# ---------------------------------------------------------------------------

def _bare_repo(tmp_path):
    """Minimal git repo, no origin needed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


@pytest.mark.asyncio
async def test_merge_nothing_to_merge(tmp_path):
    """When all agent diffs are empty, merge short-circuits with a non-error artifact."""
    repo = _bare_repo(tmp_path)
    ctx = RunContext(run_id="r-empty", pipeline_name="p")
    # Agent artifact with an empty diff — nothing to integrate.
    ctx.record(Artifact(step_id="implement", output="did work", diff="", branch="",
                        cost_usd=0.0, tokens=0, is_error=False))
    pipe = Pipeline(
        name="p",
        steps=[
            Step(id="implement", role="implementer", prompt="x", success_criteria="true"),
            Step(id="merge", type=StepType.task, needs=["implement"],
                 merge_strategy="sequential-rebase"),
        ],
    )
    merge_step = pipe.steps[-1]
    art = await run_merge_step(None, pipe, merge_step, ctx, repo=repo, adapter=None)
    assert not art.is_error
    assert "nothing to merge" in art.output.lower()
    assert art.output_data is not None
    assert art.output_data["pr_url"] is None


# ---------------------------------------------------------------------------
# FIX 1: conflict-retry records error instead of crashing
# ---------------------------------------------------------------------------

def _conflicting_diff_for_repo(repo) -> str:
    """A diff editing shared.txt's middle line, captured off the ORIGINAL base."""
    wt = repo / ".worktrees" / "seed"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "HEAD"], cwd=repo, check=True)
    (wt / "shared.txt").write_text("alpha\nMINE\ngamma\n")
    subprocess.run(["git", "add", "-A", "-N"], cwd=wt, check=True)
    diff = subprocess.run(["git", "diff"], cwd=wt, capture_output=True, text=True).stdout
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=True)
    return diff


def _conflict_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "shared.txt").write_text("alpha\nbeta\ngamma\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _conflict_pipeline():
    return Pipeline(
        name="conflict",
        steps=[
            Step(id="implement", role="implementer", prompt="x", success_criteria="true"),
            Step(id="merge", type=StepType.task, needs=["implement"],
                 merge_strategy="sequential-rebase"),
        ],
    )


def _build_graph(saver, repo, pipe):
    merge_step = pipe.steps[-1]

    async def merge_node(state):
        await run_merge_step(None, pipe, merge_step, state["ctx"], repo=repo, adapter=None)
        return {"ctx": state["ctx"]}

    b = StateGraph(GraphState)
    b.add_node("merge", merge_node)
    b.add_edge("__start__", "merge")
    b.add_edge("merge", END)
    return b.compile(checkpointer=saver)


@pytest.mark.asyncio
async def test_merge_conflict_retry_still_conflicts_records_error(tmp_path):
    """Resume 'approve' without resolving the base: retry MergeConflict → error artifact, no crash.
    """
    repo = _conflict_repo(tmp_path)
    pipe = _conflict_pipeline()

    ctx = RunContext(run_id="run-retry-conflict", pipeline_name="conflict")
    ctx.record(Artifact(step_id="implement", output="did work",
                        diff=_conflicting_diff_for_repo(repo), branch="", cost_usd=0.0,
                        tokens=0, is_error=False))

    # Advance base on the SAME line so the seeded diff no longer applies.
    (repo / "shared.txt").write_text("alpha\nTHEIRS\ngamma\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "advance"], cwd=repo, check=True)

    db = tmp_path / ".orch" / "checkpoints.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    config = {"configurable": {"thread_id": "run-retry-conflict"}, "recursion_limit": 100}

    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        saver.serde = SERDE
        graph = _build_graph(saver, repo, pipe)
        result = await graph.ainvoke({"ctx": ctx}, config)
        assert result.get("__interrupt__"), "merge conflict should pause the run"
        assert result["__interrupt__"][0].value["kind"] == "conflict"

    # Resume with "approve" but do NOT resolve the conflict in the base.
    # The retry apply_diffs should still conflict → error artifact, NOT a crash.
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver2:
        saver2.serde = SERDE
        graph2 = _build_graph(saver2, repo, pipe)
        # This previously raised MergeConflict (unhandled). After the fix it completes.
        result2 = await graph2.ainvoke(Command(resume="approve"), config)

    merge_art = result2["ctx"].artifacts["merge"]
    assert merge_art.is_error
    out = merge_art.output.lower()
    assert "still conflicts" in out or "not resolved" in out
