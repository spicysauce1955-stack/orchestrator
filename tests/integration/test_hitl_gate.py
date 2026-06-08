import sys
from pathlib import Path

from orchestrator.config.loader import load_workspace
from orchestrator.config.schemas import Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.observability.query import run_status
from orchestrator.observability.spans import configure_tracing
from orchestrator.observability.store import SqliteSpanExporter
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus
from tests.fixtures.repo import commit_all, init_git_repo

FAKE = Path(__file__).parents[1] / "fixtures" / "fake_harness" / "fake_harness.py"
EXAMPLE = Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"


def _git_repo(tmp_path):
    repo = init_git_repo(tmp_path / "repo")
    (repo / "README.md").write_text("base\n")
    commit_all(repo)
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
    # A human-rejected gate is terminal-but-distinct from a merged COMPLETED run.
    assert ctx.status == RunStatus.REJECTED
    assert ctx.gate_decisions["approve"] == "reject"


def _gateflow_pipeline() -> Pipeline:
    """A task step AFTER the gate, so resume executes (and must record) real work."""
    return Pipeline(
        name="gateflow",
        steps=[
            Step(id="audit", type=StepType.task, prompt="audit {{task}}"),
            Step(id="approve", type=StepType.gate, require_approval=True, needs=["audit"]),
            Step(id="after", type=StepType.task, prompt="finalize {{task}}", needs=["approve"]),
        ],
    )


async def test_resumed_steps_are_resolvable_in_status(tmp_path, monkeypatch):
    # The post-gate step executes during resume; its span must be reachable from
    # the same run_id (M6d follow-up: resume now opens its own SPAN_RUN).
    db = tmp_path / "spans.sqlite"
    configure_tracing(exporter=SqliteSpanExporter(db))
    sched = _sched(tmp_path, monkeypatch)
    await sched.run(_gateflow_pipeline(), {"task": "x"}, "run-vis")
    await sched.resume("run-vis", "approve")

    view = run_status(db, "run-vis")
    assert view is not None
    step_ids = {s.step_id for s in view.steps}
    assert "audit" in step_ids  # from the original run
    assert "after" in step_ids  # executed during resume


async def test_rejected_run_reports_rejected_in_status(tmp_path, monkeypatch):
    db = tmp_path / "spans.sqlite"
    configure_tracing(exporter=SqliteSpanExporter(db))
    sched = _sched(tmp_path, monkeypatch)
    await sched.run(_gate_pipeline(), {"task": "x"}, "run-rej")
    await sched.resume("run-rej", "reject")

    view = run_status(db, "run-rej")
    assert view is not None
    assert view.status == "rejected"
