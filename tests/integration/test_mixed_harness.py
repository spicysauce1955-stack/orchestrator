import subprocess
import sys
from pathlib import Path

from orchestrator.config.schemas import Harness, Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus

CLAUDE_FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
CLAUDE_SCRIPTS = CLAUDE_FAKE.parent / "scripts"
OC_FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
OC_SCRIPTS = OC_FAKE.parent / "scripts"


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


async def test_mixed_harness_routes_by_role(tmp_path, monkeypatch):
    # The OpenCode implement step touches feature.py; assert its diff was captured.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(CLAUDE_SCRIPTS))
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(OC_SCRIPTS / "implement.ndjson"))
    monkeypatch.setenv("ORCH_OC_TOUCH", "feature.py")

    # Build a workspace in code with two roles on two harnesses.
    from orchestrator.config.loader import load_workspace

    ws = load_workspace(
        Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"
    )
    # ws must contain an 'opencoder' role with harness: opencode (added in Task 7).
    assert "opencoder" in ws.roles and ws.roles["opencoder"].harness == Harness.opencode

    registry = HarnessRegistry(
        {
            Harness.claude_code: ClaudeCodeCLIAdapter(binary=[sys.executable, str(CLAUDE_FAKE)]),
            Harness.opencode: OpenCodeCLIAdapter(binary=[sys.executable, str(OC_FAKE)]),
        }
    )
    repo = _repo(tmp_path)
    db = tmp_path / ".orch" / "checkpoints.sqlite"
    sched = DeterministicScheduler(ws, registry, repo, checkpoint_db=db)

    pipe = Pipeline(
        name="mixed",
        steps=[
            Step(id="classify", type=StepType.task, prompt="classify {{task}}"),
            Step(
                id="implement",
                role="opencoder",
                needs=["classify"],
                prompt="implement {{task}}",
                success_criteria="true",
            ),
        ],
    )
    ctx = await sched.run(pipe, {"task": "add widget"}, "run-mixed-1")
    assert ctx.status == RunStatus.COMPLETED
    impl = ctx.artifacts["implement"]
    assert not impl.is_error
    assert "feature.py" in impl.diff  # OpenCode's edit was captured


async def test_bare_adapter_still_works_backcompat(tmp_path, monkeypatch):
    # Passing a single adapter (pre-M6a call style) must still run.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(CLAUDE_SCRIPTS))
    from orchestrator.config.loader import load_workspace

    ws = load_workspace(
        Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"
    )
    adapter = ClaudeCodeCLIAdapter(binary=[sys.executable, str(CLAUDE_FAKE)])
    repo = _repo(tmp_path)
    sched = DeterministicScheduler(ws, adapter, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(
        name="p", steps=[Step(id="classify", type=StepType.task, prompt="c {{task}}")]
    )
    ctx = await sched.run(pipe, {"task": "x"}, "run-bc-1")
    assert ctx.status == RunStatus.COMPLETED
