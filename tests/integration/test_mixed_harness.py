import sys
from pathlib import Path

from orchestrator.config.schemas import Harness, Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.opencode import OpenCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.scheduler import DeterministicScheduler
from orchestrator.runtime.state import RunStatus
from tests.fixtures.repo import commit_all, init_git_repo

CLAUDE_FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
CLAUDE_SCRIPTS = CLAUDE_FAKE.parent / "scripts"
OC_FAKE = Path(__file__).parent.parent / "fixtures" / "fake_opencode" / "fake_opencode.py"
OC_SCRIPTS = OC_FAKE.parent / "scripts"


def _repo(tmp_path):
    repo = init_git_repo(tmp_path / "repo")
    (repo / "README.md").write_text("base\n")
    commit_all(repo)
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


async def test_role_model_threads_to_opencode(tmp_path, monkeypatch):
    # The opencoder role declares `model: zhipu/glm-4.6`; it must reach the CLI.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(CLAUDE_SCRIPTS))
    monkeypatch.setenv("ORCH_OC_SCRIPT", str(OC_SCRIPTS / "implement.ndjson"))
    monkeypatch.setenv("ORCH_OC_ARGV", str(tmp_path / "argv.txt"))

    from orchestrator.config.loader import load_workspace

    ws = load_workspace(
        Path(__file__).parents[2] / "examples" / "feature-pipeline" / ".orchestrator"
    )
    registry = HarnessRegistry(
        {
            Harness.claude_code: ClaudeCodeCLIAdapter(binary=[sys.executable, str(CLAUDE_FAKE)]),
            Harness.opencode: OpenCodeCLIAdapter(binary=[sys.executable, str(OC_FAKE)]),
        }
    )
    repo = _repo(tmp_path)
    sched = DeterministicScheduler(ws, registry, repo, checkpoint_db=tmp_path / "c.sqlite")
    pipe = Pipeline(
        name="mixed",
        steps=[
            Step(id="classify", type=StepType.task, prompt="classify {{task}}"),
            Step(id="implement", role="opencoder", needs=["classify"], prompt="impl {{task}}"),
        ],
    )
    await sched.run(pipe, {"task": "add widget"}, "run-mixed-model")
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert "-m" in argv and "zhipu/glm-4.6" in argv  # role.model honored


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
