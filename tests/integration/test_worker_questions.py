import subprocess
import sys
from pathlib import Path

from orchestrator.agents.message_bus import MessageBus
from orchestrator.agents.orchestrator_agent import OrchestratorAgent
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Role, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.executors import run_agent_step
from orchestrator.runtime.state import RunContext

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


def _setup(tmp_path):
    ws = Workspace(config=Config())
    ws.roles = {"implementer": Role(name="implementer", harness=Harness.claude_code)}
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    bus = MessageBus()
    agent = OrchestratorAgent(workspace=ws, registry=reg, bus=bus, repo=tmp_path)
    return ws, reg, bus, agent


async def test_worker_question_is_answered_and_step_completes(tmp_path, monkeypatch):
    # Numbered-state fake: worker call 1 asks (question.1), the orchestrator's
    # answer routes to default (no keyword), worker call 2 proceeds (question.2).
    monkeypatch.setenv("ORCH_FAKE_SCRIPT_DIR", str(SCRIPTS))
    monkeypatch.setenv("ORCH_FAKE_STATE", str(tmp_path / "state"))
    ws, reg, bus, agent = _setup(tmp_path)
    repo = _repo(tmp_path)
    adapter = reg.adapter_for(Harness.claude_code)
    ctx = RunContext(run_id="r1", inputs={"task": "add widget"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent,
                prompt="question {{task}}", output_schema={"question": "string"},
                max_questions=1, success_criteria="true")
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter, agent=agent)
    assert not art.is_error
    kinds = [m.kind for m in bus.log]
    assert kinds.count("question") == 1 and kinds.count("answer") == 1
    assert not (art.output_data or {}).get("question")


async def test_question_without_agent_does_not_loop(tmp_path, monkeypatch):
    # No agent → question handling skipped (back-compat); step ends on the asking result.
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "question.1.ndjson"))
    ws, reg, bus, agent = _setup(tmp_path)
    repo = _repo(tmp_path)
    adapter = reg.adapter_for(Harness.claude_code)
    ctx = RunContext(run_id="r2", inputs={"task": "x"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent,
                prompt="question {{task}}", output_schema={"question": "string"},
                max_questions=1)
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter)  # no agent=
    assert (art.output_data or {}).get("question")
    assert bus.log == []


async def test_max_questions_zero_never_answers_even_with_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "question.1.ndjson"))
    ws, reg, bus, agent = _setup(tmp_path)
    repo = _repo(tmp_path)
    adapter = reg.adapter_for(Harness.claude_code)
    ctx = RunContext(run_id="r3", inputs={"task": "x"}, pipeline_name="p")
    step = Step(id="implement", role="implementer", type=StepType.agent,
                prompt="question {{task}}", output_schema={"question": "string"},
                max_questions=0)
    art = await run_agent_step(ws, Pipeline(name="p", steps=[step]), step, ctx,
                               repo=repo, adapter=adapter, agent=agent)
    assert (art.output_data or {}).get("question")  # asked, but never answered
    assert bus.log == []                             # max_questions=0 → no Q&A
