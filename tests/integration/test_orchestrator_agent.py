import sys
from pathlib import Path

from orchestrator.agents.message_bus import MessageBus
from orchestrator.agents.orchestrator_agent import OrchestratorAgent
from orchestrator.config.loader import Workspace
from orchestrator.config.schemas import Config, Harness, Pipeline, Step, StepType
from orchestrator.harness.claude_code import ClaudeCodeCLIAdapter
from orchestrator.harness.registry import HarnessRegistry
from orchestrator.runtime.state import RunContext

FAKE = Path(__file__).parent.parent / "fixtures" / "fake_harness" / "fake_harness.py"
SCRIPTS = FAKE.parent / "scripts"


def _agent(tmp_path):
    ws = Workspace(config=Config())
    reg = HarnessRegistry.single(ClaudeCodeCLIAdapter(binary=[sys.executable, str(FAKE)]))
    bus = MessageBus()
    return OrchestratorAgent(workspace=ws, registry=reg, bus=bus, repo=tmp_path), bus, ws


def test_default_role_is_read_only_claude(tmp_path):
    agent, _, _ = _agent(tmp_path)
    assert agent.role.harness == Harness.claude_code
    assert agent.role.permissions.value == "read-only"


async def test_run_task_records_artifact_and_emits_classify(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "classify.ndjson"))
    agent, bus, ws = _agent(tmp_path)
    ctx = RunContext(run_id="r1", inputs={"task": "add a flag"}, pipeline_name="p")
    step = Step(id="classify", type=StepType.task,
                prompt='Classify {{task}}. Reply JSON {"kind":"feature"}.',
                output_schema={"kind": "enum[bugfix,feature,refactor]"})
    pipe = Pipeline(name="p", steps=[step])
    art = await agent.run_task(pipe, step, ctx)
    assert ctx.artifacts["classify"] is art
    assert [m.kind for m in bus.log] == ["classify"]
    assert bus.log[0].frm == "orchestrator" and bus.log[0].to == "run"


async def test_answer_drives_harness_and_emits_question_then_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_FAKE_SCRIPT", str(SCRIPTS / "plan.ndjson"))
    agent, bus, ws = _agent(tmp_path)
    answer = await agent.answer("Which database should I use?", from_step="implement")
    assert isinstance(answer, str) and answer
    assert [m.kind for m in bus.log] == ["question", "answer"]
    assert bus.log[0].frm == "implement" and bus.log[0].to == "orchestrator"
    assert bus.log[1].frm == "orchestrator" and bus.log[1].to == "implement"


def test_relay_verdict_records_feedback_and_emits_span(tmp_path):
    agent, bus, ws = _agent(tmp_path)
    ctx = RunContext(run_id="r1", pipeline_name="p")
    agent.relay_verdict("reject: missing tests", to_step="implement", ctx=ctx)
    assert ctx.relayed_feedback["implement"] == "reject: missing tests"
    assert bus.log[0].kind == "verdict"
    assert bus.log[0].to == "implement"
