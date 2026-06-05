from orchestrator.compile.ir import build_ir
from orchestrator.config.schemas import Pipeline, Step, StepType


def test_gate_step_outgoing_edges_are_conditional():
    pipe = Pipeline(
        name="p",
        steps=[
            Step(id="audit", type=StepType.task, prompt="x"),
            Step(id="approve", type=StepType.gate, require_approval=True, needs=["audit"]),
            Step(id="merge", type=StepType.task, needs=["approve"], merge_strategy="sequential-rebase"),  # noqa: E501
        ],
    )
    ir = build_ir(pipe)
    approve_edges = [e for e in ir.edges if e.source == "approve"]
    assert approve_edges, "gate must have an outgoing edge"
    assert all(e.conditional for e in approve_edges), "gate edges must be conditional"
    assert any(e.target == "merge" for e in approve_edges)
