from orchestrator.runtime.state import Artifact, RunContext


def test_artifact_carries_structured_output_data():
    from orchestrator.runtime.state import Artifact

    a = Artifact(
        step_id="classify", output='{"kind": "feature"}', diff="", branch="",
        cost_usd=0.001, tokens=25, is_error=False, output_data={"kind": "feature"},
    )
    assert a.output_data == {"kind": "feature"}


def test_artifact_output_data_defaults_none():
    from orchestrator.runtime.state import Artifact

    a = Artifact("s", "o", "", "b", 0.0, 0, False)
    assert a.output_data is None


def test_graph_state_holds_run_context():
    from orchestrator.runtime.state import GraphState, RunContext

    ctx = RunContext(run_id="r1", inputs={"task": "t"})
    state: GraphState = {"ctx": ctx}
    assert state["ctx"].run_id == "r1"


def test_artifact_fields():
    a = Artifact(
        step_id="plan",
        output="the plan",
        diff="",
        branch="orch/run1/plan",
        cost_usd=0.012,
        tokens=150,
        is_error=False,
    )
    assert a.step_id == "plan"
    assert a.cost_usd == 0.012


def test_run_context_records_artifacts_and_rolls_up_cost():
    ctx = RunContext(run_id="run1", inputs={"task": "do it"})
    assert ctx.total_cost_usd == 0.0
    ctx.record(
        Artifact("plan", "p", "", "b1", 0.01, 10, False)
    )
    ctx.record(
        Artifact("impl", "i", "diff", "b2", 0.02, 20, False)
    )
    assert set(ctx.artifacts) == {"plan", "impl"}
    assert round(ctx.total_cost_usd, 4) == 0.03
    assert ctx.artifacts["impl"].diff == "diff"
