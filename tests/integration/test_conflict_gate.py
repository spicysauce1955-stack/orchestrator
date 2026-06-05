import subprocess

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command

from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.runtime.executors import run_merge_step
from orchestrator.runtime.state import (
    CHECKPOINT_SERDE_MODULES,
    Artifact,
    GraphState,
    RunContext,
)

SERDE = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_SERDE_MODULES)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "shared.txt").write_text("alpha\nbeta\ngamma\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def _conflicting_diff(repo) -> str:
    """A diff editing shared.txt's middle line, captured off the ORIGINAL base."""
    wt = repo / ".worktrees" / "seed"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "HEAD"], cwd=repo, check=True)
    (wt / "shared.txt").write_text("alpha\nMINE\ngamma\n")
    subprocess.run(["git", "add", "-A", "-N"], cwd=wt, check=True)
    diff = subprocess.run(["git", "diff"], cwd=wt, capture_output=True, text=True).stdout
    subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, check=True)
    return diff


def _pipeline():
    return Pipeline(
        name="conflict",
        steps=[
            Step(id="implement", role="implementer", prompt="x", success_criteria="true"),
            Step(id="merge", type=StepType.task, needs=["implement"],
                 merge_strategy="sequential-rebase"),
        ],
    )


def _seeded_ctx(repo):
    ctx = RunContext(run_id="run-conflict-1", pipeline_name="conflict")
    ctx.record(Artifact(step_id="implement", output="did work",
                        diff=_conflicting_diff(repo), branch="", cost_usd=0.0,
                        tokens=0, is_error=False))
    return ctx


def _build(saver, repo, pipe):
    merge_step = pipe.steps[-1]

    async def merge_node(state):
        await run_merge_step(None, pipe, merge_step, state["ctx"], repo=repo, adapter=None)
        return {"ctx": state["ctx"]}

    b = StateGraph(GraphState)
    b.add_node("merge", merge_node)
    b.add_edge("__start__", "merge")
    b.add_edge("merge", END)
    return b.compile(checkpointer=saver)


async def test_merge_conflict_pauses_then_aborts(tmp_path):
    repo = _repo(tmp_path)
    pipe = _pipeline()
    ctx = _seeded_ctx(repo)
    # Advance base on the SAME line so the seeded diff no longer applies.
    (repo / "shared.txt").write_text("alpha\nTHEIRS\ngamma\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "advance"], cwd=repo, check=True)

    db = tmp_path / ".orch" / "checkpoints.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    config = {"configurable": {"thread_id": "run-conflict-1"}, "recursion_limit": 100}

    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        saver.serde = SERDE
        graph = _build(saver, repo, pipe)
        result = await graph.ainvoke({"ctx": ctx}, config)
        assert result.get("__interrupt__"), "merge conflict should pause the run"
        assert result["__interrupt__"][0].value["kind"] == "conflict"

    # Separate saver instance (simulates `orch resume` in a fresh process).
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver2:
        saver2.serde = SERDE
        graph2 = _build(saver2, repo, pipe)
        result2 = await graph2.ainvoke(Command(resume="reject"), config)
        merge_art = result2["ctx"].artifacts["merge"]
        assert merge_art.is_error
        assert "conflict" in merge_art.output.lower()
